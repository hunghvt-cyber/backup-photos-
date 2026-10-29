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
import traceback
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright
from gpwc import Client, payloads
from src.gphotos_sync import Engine, now


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
    try:
        response = payload.execute(client)
    except (IndexError, KeyError, TypeError):
        raise RuntimeError('WEB_RPC_SCHEMA_CHANGED') from None
    if not response.success or response.data is None:
        raise RuntimeError('Empty/failed web API response')
    return response.data


def taken(item):
    ts = getattr(item, 'timestamp', None)
    offset = getattr(item, 'timezone_offset', None) or 0
    return (datetime.fromtimestamp(ts / 1000, timezone.utc) + timedelta(seconds=offset)).replace(tzinfo=None).isoformat() if ts else None


def first_https(value):
    if isinstance(value, str) and value.startswith('https://'):
        return value
    if isinstance(value, list):
        for child in value:
            found = first_https(child)
            if found:
                return found
    return None


class DownloadError(RuntimeError):
    """Safe diagnostic code without URLs or credentials."""


BOOTSTRAP_KEYS = ('FdrFJe', 'cfb2h', 'SNlM0e', 'Im6cmf')
NAV_HOSTS = {'photos.google.com', 'www.google.com', 'accounts.google.com', 'consent.google.com'}
NAV_PATH_SEGMENTS = {'sorry', 'signin', 'ServiceLogin', 'v3', 'challenge', 'consent',
                     'photos', 'photo', 'accounts', 'CheckCookie', 'SetSID', 'lookup',
                     'identifier', 'auth', 'user', '0'}


def safe_navigation_location(raw_url):
    """Return only an allowlisted Google host and non-identifying path segments."""
    location = urlparse(raw_url)
    host = (location.hostname or '').lower()
    safe_host = host if host in NAV_HOSTS else '[other-host]'
    segments = [segment for segment in location.path.split('/') if segment]
    safe_segments = [segment if segment in NAV_PATH_SEGMENTS else '[redacted]' for segment in segments]
    path = '/' + '/'.join(safe_segments) if safe_segments else '/'
    return {'host': safe_host, 'path': path}


def navigation_diagnostics(page):
    """Attach main-frame listeners and retain sanitized redirect/status facts only."""
    events = []
    seen = {}

    def is_main_frame(request):
        try:
            return request.is_navigation_request() and request.frame == page.main_frame
        except Exception:
            return False

    def on_request(request):
        if is_main_frame(request):
            item = safe_navigation_location(request.url)
            item['http_status'] = None
            seen[request] = item
            events.append(item)

    def on_response(response):
        request = response.request
        if request in seen:
            seen[request]['http_status'] = int(response.status)

    page.on('request', on_request)
    page.on('response', on_response)
    return events


def validated_bootstrap(value):
    # Values contain session material: keep in memory and never log/serialize it.
    if not isinstance(value, dict) or any(not isinstance(value.get(k), str) or not value[k] for k in BOOTSTRAP_KEYS):
        raise RuntimeError('WEB_BOOTSTRAP_INCOMPLETE')
    if not value['Im6cmf'].startswith('/') or value['Im6cmf'].startswith('//'):
        raise RuntimeError('WEB_BOOTSTRAP_INCOMPLETE')
    return {**{key: value[key] for key in BOOTSTRAP_KEYS},
            'oPEP7c': value.get('oPEP7c') if isinstance(value.get('oPEP7c'), str) else 'redacted'}


def browser_bootstrap(page, timeout_ms=30000, poll_ms=500, navigation=None):
    """Read the existing browser session, independent of media-tile selectors."""
    remaining = timeout_ms
    value = None

    def emit_navigation():
        if navigation is not None:
            print('WEB_NAVIGATION_CHAIN=' + json.dumps(navigation, separators=(',', ':')), flush=True)

    while True:
        location = urlparse(page.url)
        host = (location.hostname or '').lower()
        if host == 'www.google.com' and location.path.startswith('/sorry/'):
            emit_navigation()
            print('WEB_BOOTSTRAP_STATUS=CHALLENGE_REQUIRED', flush=True)
            raise RuntimeError('WEB_CHALLENGE_REQUIRED')
        if host in ('accounts.google.com', 'consent.google.com'):
            code = 'AUTH_REQUIRED' if host == 'accounts.google.com' else 'CONSENT_REQUIRED'
            emit_navigation()
            print('WEB_BOOTSTRAP_STATUS=' + code, flush=True)
            raise RuntimeError('WEB_' + code)
        if host == 'photos.google.com':
            value = page.evaluate('() => window.WIZ_global_data || null')
            try:
                result = validated_bootstrap(value)
            except RuntimeError:
                pass
            else:
                emit_navigation()
                print('WEB_BOOTSTRAP_STATUS=READY', flush=True)
                return result
        if remaining <= 0:
            signin_form = bool(page.locator('input[type="email"],input[name="Passwd"]').count())
            challenge_frame = bool(page.locator('iframe[src*="recaptcha"],#captcha-form,[id*="captcha"]').count())
            consent_indicator = bool(page.locator('form[action*="consent"],button[name*="accept"],#consent-bump').count())
            diagnostic = {'photos_host': host == 'photos.google.com',
                          'host_class': host if host in NAV_HOSTS else ('blank' if location.scheme == 'about' else 'other'),
                          'signin_form': signin_form,
                          'consent_indicator': consent_indicator,
                          'challenge_frame': challenge_frame,
                          'challenge_path': host == 'www.google.com' and location.path.startswith('/sorry/'),
                          'global_present': isinstance(value, dict),
                          'field_types': {k: type(value.get(k)).__name__ if isinstance(value, dict) else 'absent'
                                          for k in BOOTSTRAP_KEYS}}
            emit_navigation()
            print('WEB_BOOTSTRAP_DIAGNOSTIC=' + json.dumps(diagnostic), flush=True)
            print('WEB_BOOTSTRAP_STATUS=UNAVAILABLE', flush=True)
            raise RuntimeError('WEB_BOOTSTRAP_UNAVAILABLE')
        wait = min(poll_ms, remaining)
        page.wait_for_timeout(wait)
        remaining -= wait


class BoundedClient(Client):
    def __init__(self, *args, bootstrap_data, **kwargs):
        self._browser_bootstrap = validated_bootstrap(bootstrap_data)
        super().__init__(*args, **kwargs)

    def get_global_data(self):
        # Reuse tokens from the same browser that exported the cookies. Avoid
        # a second requests-only HTML login/bootstrap parse with xpath(...)[0].
        self.session.request = functools.partial(self.session.request, timeout=(30, 120))
        return dict(self._browser_bootstrap)


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
        self.db.execute('CREATE TABLE IF NOT EXISTS web_inventory_meta(key TEXT PRIMARY KEY,value TEXT)')
        self.db.commit()

    def inventory(self, seconds):
        self.inventory_pages = 0
        self.inventory_flushes = 0
        started = time.monotonic()
        try:
            return self._inventory(seconds)
        finally:
            print('INVENTORY_PERF=' + json.dumps({'pages': self.inventory_pages,
                  'remote_checkpoints': self.inventory_flushes,
                  'seconds': round(time.monotonic() - started, 3)}), flush=True)

    def _inventory(self, seconds):
        until = time.monotonic() + seconds
        failed_tasks = set()
        args = getattr(self.e, 'a', None)
        refresh = getattr(args, 'inventory_refresh_seconds', 0)
        batch = getattr(args, 'inventory_checkpoint_pages', 1)
        # Only defer a completed, recently timestamped pass while media remain.
        # Partial traversals ALWAYS resume, including after a failed checkpoint.
        if not self.db.execute('SELECT 1 FROM web_tasks WHERE done=0').fetchone():
            stamp = self.db.execute("SELECT value FROM web_inventory_meta WHERE key='completed_at'").fetchone()
            try:
                age = time.time() - float(stamp[0]) if stamp else None
            except (ValueError, TypeError):
                age = None
            backlog = self.db.execute("SELECT 1 FROM media WHERE status!='uploaded' LIMIT 1").fetchone()
            if refresh and age is not None and 0 <= age < refresh and backlog:
                print('INVENTORY_DEFERRED recent_complete_with_backlog=True', flush=True)
                return

            self.db.execute('UPDATE web_tasks SET page=NULL,done=0')
            self.db.commit()
        pending_pages = 0
        last_flush = time.monotonic()
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
                self.inventory_flushes += 1
                pending_pages = 0
                last_flush = time.monotonic()
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
            pending_pages += 1
            self.inventory_pages += 1
            if pending_pages >= batch or time.monotonic() - last_flush >= 60:
                self.e.flush()
                self.inventory_flushes += 1
                pending_pages = 0
                last_flush = time.monotonic()
            print('WEB_PAGE=' + json.dumps({'source': kind if kind != 'timeline' else key, 'items': len(result.items), 'more': bool(token)}), flush=True)

        if not failed_tasks and not self.db.execute('SELECT 1 FROM web_tasks WHERE done=0').fetchone():
            self.db.execute("INSERT OR REPLACE INTO web_inventory_meta VALUES('completed_at',?)", (str(time.time()),))
            self.db.commit()
            # Timestamp and final cursors travel in the same SQLite snapshot.
            pending_pages = max(pending_pages, 1)
        if pending_pages:
            self.e.flush()
            self.inventory_flushes += 1

    def download(self, unused, url, media_id):
        try:
            return self.download_original(media_id)
        except Exception as exc:
            raise RuntimeError("Web original download failed: " + (str(exc) if isinstance(exc, DownloadError) else type(exc).__name__)) from None

    def download_original(self, media_id):
        row = self.db.execute('SELECT album FROM web_items WHERE id=?', (media_id,)).fetchone()
        info = execute(self.client, payloads.GetItemInfo(media_key=media_id, album_media_key=row[0] if row else None))
        ext = execute(self.client, payloads.GetItemInfoExt(media_key=media_id))
        name = Path(ext.file_name or '').name
        if not name or name in ('.', '..'):
            raise DownloadError('ORIGINAL_FILENAME_MISSING')
        dst = self.e.wd / (media_id + '__' + name)
        original = info.download_original_url or (info.download_url if ext.size else None)
        last_error = None
        # Try the signed original RPC after a rejected metadata URL as well as
        # when that URL is absent. Never relax source-size verification.
        for route in range(2):
            if self.e.left() < 180:
                raise DownloadError('STOP_RESERVE')
            if route == 1:
                request = payloads.GetUnsupportedVideoDownloadUrl(media_keys=[media_id], parse_response=False)
                request.data = [[media_id], [1]]
                original = first_https(execute(self.client, request))
            if not original:
                last_error = DownloadError('ORIGINAL_URL_MISSING')
                continue
            try:
                self.fetch_original(original, dst, ext.size, route=route)
                last_error = None
                return dst, name
            except DownloadError as exc:
                last_error = exc
                if str(exc) == 'STOP_RESERVE':
                    raise
            except Exception as exc:
                # Do not expose signed URLs or response bodies in logs.
                last_error = DownloadError('ORIGINAL_TRANSPORT_' + type(exc).__name__)
            finally:
                if last_error is not None:
                    dst.unlink(missing_ok=True)
            if route == 0:
                print('ORIGINAL_FALLBACK reason=' + str(last_error), flush=True)
        raise last_error or DownloadError('ORIGINAL_URL_MISSING')

    def fetch_original(self, original, dst, expected_size, route=0):
        def allowed(url):
            parsed = urlparse(url)
            return (parsed.scheme == 'https' and not parsed.username and not parsed.password
                    and any((parsed.hostname or '').endswith('.' + domain)
                            for domain in ('googleusercontent.com', 'google.com', 'googlevideo.com')))
        if not allowed(original):
            raise DownloadError('ORIGINAL_URL_REJECTED')
        try:
            with self.client.session.get(original, stream=True, timeout=(30, 120)) as response:
                response.raise_for_status()
                if 'text/html' in response.headers.get('Content-Type', '').lower():
                    raise DownloadError('HTML_INSTEAD_OF_MEDIA')
                with dst.open('wb') as out:
                    for chunk in response.iter_content(1024 * 1024):
                        if self.e.left() < 180:
                            raise DownloadError('STOP_RESERVE')
                        out.write(chunk)
                actual = dst.stat().st_size
                if not actual or (expected_size and actual != expected_size):
                    # Numeric diagnostics only: never expose signed URLs or filenames.
                    print('ORIGINAL_SIZE_DIAGNOSTIC=' + json.dumps({
                        'route': route, 'expected_bytes': expected_size,
                        'actual_bytes': actual}), flush=True)
                    raise DownloadError('ORIGINAL_SIZE_MISMATCH')
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
            if os.environ.get('WEB_RETRY_ONLY') == '1':
                rows = [r for r in rows if self.db.execute("SELECT status FROM media WHERE id=?", (r[0],)).fetchone()[0] == 'error']
            for row in rows:
                if self.e.left() < 300 or self.e.stats['attempted'] >= self.e.a.maxitems:
                    break
                self.db.execute('UPDATE web_items SET last_attempt=? WHERE id=?', (now(), row[0]))
                self.db.commit()
                self.e.one(None, *row, update_checkpoint=False, flush_state=False)
                if self.e.stats['attempted'] % 10 == 0:
                    self.e.flush()
        self.e.flush()
        self.report(inventory_error, probe)
        return int(inventory_error or self.e.stats['errors'] > 0)

    def report(self, inventory_error=False, probe=False):
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
        return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--probe', action='store_true')
    parser.add_argument('--maxitems', type=int, default=int(os.environ.get('MAX_ITEMS', '10000')))
    parser.add_argument('--seconds', type=int, default=int(os.environ.get('MAX_RUNTIME_SECONDS', '18000')))
    parser.add_argument('--scan-seconds', type=int, default=1200)
    parser.add_argument('--inventory-refresh-seconds', type=int, default=0)
    parser.add_argument('--inventory-checkpoint-pages', type=int, default=1)
    parser.add_argument('--bootstrap-only', action='store_true', help=argparse.SUPPRESS)
    a = parser.parse_args()
    if not 0 <= a.inventory_refresh_seconds <= 86400 or not 1 <= a.inventory_checkpoint_pages <= 10:
        parser.error('inventory refresh must be 0..86400 seconds; checkpoint batch must be 1..10 pages')
    a.profile = os.path.expanduser(os.environ.get('GPHOTOS_PROFILE_DIR', '~/gphotos-profile'))
    a.chrome = os.environ.get('CHROME_BIN', '/usr/bin/google-chrome-stable')
    a.state, a.work = '/tmp/gphotos-state', '/tmp/gphotos-downloads'
    a.root, a.sroot = 'koofr_remote:/Google Photos/Photos', 'koofr_remote:/Google Photos/.gphotos-sync'
    if a.bootstrap_only:
        stage = 'browser_bootstrap'
        try:
            with sync_playwright() as pw:
                context = pw.chromium.launch_persistent_context(a.profile, executable_path=a.chrome,
                    headless=True, args=['--disable-dev-shm-usage','--no-first-run'])
                try:
                    page = context.pages[0] if context.pages else context.new_page()
                    navigation = navigation_diagnostics(page)
                    response = page.goto('https://photos.google.com/', wait_until='domcontentloaded', timeout=90000)
                    if response is not None and not navigation:
                        item = safe_navigation_location(page.url)
                        item['http_status'] = int(response.status)
                        navigation.append(item)
                    browser_bootstrap(page, navigation=navigation)
                finally:
                    context.close()
            print('WEB_BOOTSTRAP_ONLY=COMPLETE', flush=True)
            return 0
        except Exception as exc:
            print('WEB_FATAL type=' + type(exc).__name__ + ' stage=' + stage, flush=True)
            frames = [{'file': Path(f.filename).name, 'line': f.lineno, 'function': f.name}
                      for f in traceback.extract_tb(exc.__traceback__)[-6:]]
            print('WEB_FATAL_FRAMES=' + json.dumps(frames), flush=True)
            return 1
    e = Engine(a)
    cookie_path = e.sd / 'web-cookies.txt'
    web = None
    stage = 'manifest_schema'
    try:
        web = WebBackup(e, None)
        stage = 'browser_bootstrap'
        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(a.profile, executable_path=a.chrome, headless=True, args=['--disable-dev-shm-usage','--no-first-run'])
            try:
                page = context.pages[0] if context.pages else context.new_page()
                navigation = navigation_diagnostics(page)
                response = page.goto('https://photos.google.com/', wait_until='domcontentloaded', timeout=90000)
                if response is not None and not navigation:
                    item = safe_navigation_location(page.url)
                    item['http_status'] = int(response.status)
                    navigation.append(item)
                bootstrap = browser_bootstrap(page, navigation=navigation)
                if not a.bootstrap_only:
                    export_cookies(context, cookie_path)
            finally:
                context.close()
        if a.bootstrap_only:
            print('WEB_BOOTSTRAP_ONLY=COMPLETE', flush=True)
            return 0
        # gpwc logs the account email at INFO. Disable before constructing it.
        logging.disable(logging.CRITICAL)
        stage = 'web_client'
        client = BoundedClient(cookie_path, bootstrap_data=bootstrap, log_level='CRITICAL')
        stage = 'inventory_and_upload'
        web.client = client
        return web.run(a.scan_seconds, a.probe)
    except Exception as exc:
        print('WEB_FATAL type=' + type(exc).__name__ + ' stage=' + stage, flush=True)
        # Frame metadata only: never exception text, locals, cookies or DOM.
        frames = [{'file': Path(f.filename).name, 'line': f.lineno, 'function': f.name}
                  for f in traceback.extract_tb(exc.__traceback__)[-6:]]
        print('WEB_FATAL_FRAMES=' + json.dumps(frames), flush=True)
        if web is not None:
            web.report(inventory_error=True, probe=a.probe)
        return 1
    finally:
        cookie_path.unlink(missing_ok=True)
        e.flush()
        e.db.c.close()
        shutil.rmtree(e.wd, ignore_errors=True)


if __name__ == '__main__':
    raise SystemExit(main())
