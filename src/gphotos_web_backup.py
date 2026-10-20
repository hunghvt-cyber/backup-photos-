"""Read-only web inventory of Photos, Archive and albums; existing Koofr manifest."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone, timedelta
import functools
import json
import logging
import os
from pathlib import Path
import shutil
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright
from gpwc import Client, payloads
from src.gphotos_sync import Engine, cmd, now


def export_cookies(context, path):
    lines = ['# Netscape HTTP Cookie File']
    for c in context.cookies():
        if not (c['domain'].lstrip('.').endswith('google.com')):
            continue
        lines.append('\t'.join([c['domain'], 'TRUE' if c['domain'].startswith('.') else 'FALSE',
                                c['path'], 'TRUE' if c['secure'] else 'FALSE',
                                str(max(0, int(c.get('expires', 0)))), c['name'], c['value']]))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as out:
        out.write('\n'.join(lines) + '\n')


def execute(client, payload):
    response = payload.execute(client)
    if not response.success or response.data is None:
        raise RuntimeError('Empty/failed web API response')
    return response.data


def taken(item):
    ts = getattr(item, 'timestamp', None)
    offset = getattr(item, 'timezone_offset', None) or 0
    return (datetime.fromtimestamp(ts / 1000, timezone.utc) + timedelta(seconds=offset)).replace(tzinfo=None).isoformat() if ts else None


class DownloadError(RuntimeError):
    """Safe diagnostic code without URLs or credentials."""


class BoundedClient(Client):
    def get_global_data(self):
        # Bound authentication/bootstrap requests as well as subsequent RPCs.
        self.session.request = functools.partial(self.session.request, timeout=(30, 120))
        return super().get_global_data()


class WebBackup:
    def __init__(self, engine, client):
        self.e, self.client = engine, client
        self.inventory_failures = 0
        self.db = engine.db.c
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS web_tasks(kind TEXT,key TEXT,page TEXT,done INTEGER DEFAULT 0,PRIMARY KEY(kind,key));
        CREATE TABLE IF NOT EXISTS web_items(id TEXT PRIMARY KEY,album TEXT,last_attempt TEXT);
        CREATE TABLE IF NOT EXISTS web_albums(id TEXT PRIMARY KEY,title TEXT,item_count INTEGER);
        CREATE TABLE IF NOT EXISTS web_album_items(album TEXT,id TEXT,PRIMARY KEY(album,id));
        ''')
        if 'turn' not in {row[1] for row in self.db.execute('PRAGMA table_info(web_tasks)')}:
            self.db.execute('ALTER TABLE web_tasks ADD COLUMN turn INTEGER DEFAULT 0')
        for key in ('archive', 'library'):
            self.db.execute('INSERT OR IGNORE INTO web_tasks(kind,key) VALUES(?,?)', ('timeline', key))
        self.db.execute("INSERT OR IGNORE INTO web_tasks(kind,key) VALUES('albums','index')")
        self.db.commit()

    def inventory(self, seconds):
        until = time.monotonic() + seconds
        failed_tasks = set()
        # Repeat complete inventories on later runs; partial traversals resume exactly.
        if not self.db.execute('SELECT 1 FROM web_tasks WHERE done=0').fetchone():
            self.db.execute('UPDATE web_tasks SET page=NULL,done=0')
            self.db.commit()
        while time.monotonic() < until and self.e.left() > 300:
            tasks = self.db.execute("SELECT kind,key,page FROM web_tasks WHERE done=0 ORDER BY turn,CASE kind WHEN 'timeline' THEN 0 WHEN 'albums' THEN 1 ELSE 2 END,key").fetchall()
            task = next((t for t in tasks if t[:2] not in failed_tasks), None)
            if not task:
                break
            kind, key, page = task
            if kind == 'timeline':
                request = payloads.GetLibraryPageByTakenDate(page_id=page, source=key)
            elif kind == 'albums':
                request = payloads.GetAlbumsPage(page_id=page)
            else:
                request = payloads.GetAlbumPage(media_key=key, page_id=page)
            try:
                result = execute(self.client, request)
            except Exception as exc:
                # Keep this source cursor, but let other sources progress.
                failed_tasks.add((kind, key))
                self.inventory_failures += 1
                self.db.execute('UPDATE web_tasks SET turn=(SELECT COALESCE(MAX(turn),0)+1 FROM web_tasks) WHERE kind=? AND key=?', (kind, key))
                self.db.commit()
                self.e.flush()
                print('WEB_SOURCE_ERROR source=' + kind + ' type=' + type(exc).__name__, flush=True)
                continue
            if not hasattr(result, 'items') or not hasattr(result, 'next_page_id'):
                raise RuntimeError('Unexpected inventory response schema')
            for item in result.items:
                if not item.media_key:
                    raise RuntimeError('Inventory item missing media key')
                if kind == 'albums':
                    self.db.execute('INSERT OR REPLACE INTO web_albums VALUES(?,?,?)', (item.media_key, item.title, item.item_count))
                    self.db.execute("INSERT OR IGNORE INTO web_tasks(kind,key) VALUES('album',?)", (item.media_key,))
                else:
                    media_type = 'video' if item.video_duration is not None else 'photo'
                    self.e.db.touch(item.media_key, media_type, 'https://photos.google.com/photo/' + item.media_key, None, taken(item))
                    self.db.execute('INSERT OR IGNORE INTO web_items(id,album) VALUES(?,?)', (item.media_key, key if kind == 'album' else None))
                    if kind == 'album':
                        self.db.execute('INSERT OR IGNORE INTO web_album_items VALUES(?,?)', (key, item.media_key))
            token = result.next_page_id
            if token and token == page:
                raise RuntimeError('Inventory pagination stalled')
            self.db.execute('UPDATE web_tasks SET page=?,done=?,turn=(SELECT COALESCE(MAX(turn),0)+1 FROM web_tasks) WHERE kind=? AND key=?', (token, int(not token), kind, key))
            self.db.commit()
            self.e.stats['discovered'] += len(result.items) if kind != 'albums' else 0
            self.e.flush()
            print('WEB_PAGE=' + json.dumps({'source': kind if kind != 'timeline' else key, 'items': len(result.items), 'more': bool(token)}), flush=True)

    def download(self, unused, url, media_id):
        try:
            return self.download_original(media_id)
        except Exception as exc:
            raise RuntimeError("Web original download failed: " + (str(exc) if isinstance(exc, DownloadError) else type(exc).__name__)) from None

    def download_original(self, media_id):
        row = self.db.execute('SELECT album FROM web_items WHERE id=?', (media_id,)).fetchone()
        info = execute(self.client, payloads.GetItemInfo(media_key=media_id, album_media_key=row[0] if row else None))
        ext = execute(self.client, payloads.GetItemInfoExt(media_key=media_id))
        # For unedited owned media Google supplies only download_url. Require
        # its byte size to match source metadata before accepting that endpoint.
        original = info.download_original_url or (info.download_url if ext.size else None)
        if not original or urlparse(original).scheme != 'https' or not any((urlparse(original).hostname or '').endswith('.' + domain) for domain in ('googleusercontent.com', 'google.com')):
            raise DownloadError('ORIGINAL_URL_MISSING')
        name = Path(ext.file_name or '').name
        if not name or name in ('.', '..'):
            raise DownloadError('ORIGINAL_FILENAME_MISSING')
        dst = self.e.wd / (media_id + '__' + name)
        try:
            with self.client.session.get(original, stream=True, timeout=(30, 120)) as response:
                response.raise_for_status()
                if 'text/html' in response.headers.get('Content-Type', ''):
                    raise DownloadError('HTML_INSTEAD_OF_MEDIA')
                with dst.open('wb') as out:
                    for chunk in response.iter_content(1024 * 1024):
                        if self.e.left() < 180:
                            raise DownloadError('STOP_RESERVE')
                        out.write(chunk)
                if not dst.stat().st_size or (ext.size and dst.stat().st_size != ext.size):
                    raise DownloadError('ORIGINAL_SIZE_MISMATCH')
            return dst, name
        except BaseException:
            dst.unlink(missing_ok=True)
            raise

    def run(self, scan_seconds, probe=False):
        inventory_error = False
        try:
            self.inventory(scan_seconds)
        except Exception as exc:
            inventory_error = True
            # Do not log signed URLs, tokens, cookies or personal album titles.
            print('WEB_INVENTORY_ERROR type=' + type(exc).__name__, flush=True)
        inventory_error = inventory_error or self.inventory_failures > 0
        self.e.download = self.download
        if not probe:
            rows = self.db.execute("SELECT m.id,m.type,m.url,m.label,m.created FROM media m JOIN web_items w ON w.id=m.id WHERE m.status!='uploaded' ORDER BY COALESCE(w.last_attempt,''),m.first_seen,m.id").fetchall()
            for row in rows:
                if self.e.left() < 300 or self.e.stats['attempted'] >= self.e.a.maxitems:
                    break
                self.db.execute('UPDATE web_items SET last_attempt=? WHERE id=?', (now(), row[0]))
                self.db.commit()
                self.e.one(None, *row, update_checkpoint=False, flush_state=False)
                if self.e.stats['attempted'] % 10 == 0:
                    self.e.flush()
        self.e.flush()
        counts = dict(self.db.execute('SELECT status,COUNT(*) FROM media GROUP BY status').fetchall())
        complete = not bool(self.db.execute('SELECT 1 FROM web_tasks WHERE done=0').fetchone()) and not inventory_error
        report = {**self.e.stats, 'inventory_complete': complete, 'inventory_error': inventory_error,
                  'manifest_uploaded_total': counts.get('uploaded', 0),
                  'pending_seen': counts.get('seen', 0), 'pending_errors': counts.get('error', 0),
                  'inventoried_total': self.db.execute('SELECT COUNT(*) FROM web_items').fetchone()[0],
                  'albums': self.db.execute('SELECT COUNT(*) FROM web_albums').fetchone()[0],
                  'album_memberships': self.db.execute('SELECT COUNT(*) FROM web_album_items').fetchone()[0],
                  'probe': probe, 'status': 'PARTIAL' if inventory_error or self.e.stats['errors'] else 'PAUSED'}
        print('WEB_SUMMARY=' + json.dumps(report), flush=True)
        return int(inventory_error or self.e.stats['errors'] > 0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--probe', action='store_true')
    parser.add_argument('--maxitems', type=int, default=int(os.environ.get('MAX_ITEMS', '10000')))
    parser.add_argument('--seconds', type=int, default=int(os.environ.get('MAX_RUNTIME_SECONDS', '18000')))
    parser.add_argument('--scan-seconds', type=int, default=1200)
    a = parser.parse_args()
    a.profile = os.path.expanduser('~/gphotos-profile')
    a.chrome = os.environ.get('CHROME_BIN', '/usr/bin/google-chrome-stable')
    a.state, a.work = '/tmp/gphotos-state', '/tmp/gphotos-downloads'
    a.root, a.sroot = 'koofr_remote:/Google Photos/Photos', 'koofr_remote:/Google Photos/.gphotos-sync'
    e = Engine(a)
    cookie_path = e.sd / 'web-cookies.txt'
    try:
        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(a.profile, executable_path=a.chrome, headless=True, args=['--disable-dev-shm-usage','--no-first-run'])
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto('https://photos.google.com/', wait_until='domcontentloaded', timeout=90000)
                page.wait_for_timeout(3000)
                export_cookies(context, cookie_path)
            finally:
                context.close()
        # gpwc logs the account email at INFO. Disable before constructing it.
        logging.disable(logging.CRITICAL)
        client = BoundedClient(cookie_path, log_level='CRITICAL')
        return WebBackup(e, client).run(a.scan_seconds, a.probe)
    except Exception as exc:
        print('WEB_FATAL type=' + type(exc).__name__, flush=True)
        return 1
    finally:
        cookie_path.unlink(missing_ok=True)
        e.flush()
        e.db.c.close()
        shutil.rmtree(e.wd, ignore_errors=True)


if __name__ == '__main__':
    raise SystemExit(main())
