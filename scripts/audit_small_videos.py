"""One-off read-only audit. Never writes provider state or prints private fields."""
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
import urllib.request
from urllib.parse import urlparse

REPO = 'hunghvt-cyber/google-photos-koofr'
JOB = 119544330852
ROOT = 'koofr_remote:/Google Photos/'


def command(*args):
    result = subprocess.run(args, capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError('READ_COMMAND_FAILED_' + args[1].upper())
    return result.stdout


def job_log():
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            return None
    request = urllib.request.Request(f'https://api.github.com/repos/{REPO}/actions/jobs/{JOB}/logs',
        headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'], 'Accept': 'application/vnd.github+json'})
    try:
        response = urllib.request.build_opener(NoRedirect).open(request, timeout=30)
    except urllib.error.HTTPError as error:
        if error.code != 302:
            raise RuntimeError('LOG_READ_FAILED') from None
        url = error.headers['Location']
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.username or parsed.password:
            raise RuntimeError('LOG_REDIRECT_REJECTED')
        # No GitHub bearer is sent to signed storage.
        response = urllib.request.urlopen(url, timeout=30)
    with response:
        data = response.read(4 * 1024 * 1024 + 1)
    if len(data) > 4 * 1024 * 1024:
        raise RuntimeError('LOG_TOO_LARGE')
    return data.decode('utf-8', errors='replace')


def select_targets(log):
    rows = re.findall(r'UPLOAD_OK id=(\S+) file=(.*?) size=(\d+) reused=(?:True|False)', log)
    targets = [(media, int(size)) for media, name, size in rows
               if name.lower().endswith('.mp4') and int(size) <= 4096]
    if len(targets) != 2 or len({row[0] for row in targets}) != 2:
        raise RuntimeError('TARGET_SET_CHANGED')
    return targets


def inspect_bytes(data):
    prefix = data[:512].lstrip().lower()
    return 'html' if prefix.startswith((b'<!doctype html', b'<html')) or b'<html' in prefix else 'other'


def inspect_file(path):
    probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
        'format=format_name,duration:stream=codec_type,codec_name,duration', '-of', 'json', str(path)],
        capture_output=True, timeout=30)
    try:
        parsed = json.loads(probe.stdout)
    except (ValueError, TypeError):
        parsed = {}
    streams = parsed.get('streams', [])
    return {'ffprobe_ok': probe.returncode == 0,
            'video_streams': sum(s.get('codec_type') == 'video' for s in streams),
            'audio_streams': sum(s.get('codec_type') == 'audio' for s in streams),
            'duration': parsed.get('format', {}).get('duration'),
            'format': parsed.get('format', {}).get('format_name')}


def main():
    targets = select_targets(job_log())
    with tempfile.TemporaryDirectory(prefix='media-audit-') as folder:
        work = Path(folder)
        manifest = work / 'manifest.sqlite'
        command('rclone', 'copyto', ROOT + '.gphotos-sync/manifest.sqlite', str(manifest),
                '--retries', '2', '--timeout', '30s')
        db = sqlite3.connect(manifest.as_uri() + '?mode=ro&immutable=1', uri=True)
        try:
            reports = []
            for index, (media, log_size) in enumerate(targets, 1):
                row = db.execute('SELECT remote,size,sha256,status FROM media WHERE id=?', (media,)).fetchone()
                if not row or not row[0].startswith(ROOT + 'Photos/') or '/..' in row[0]:
                    raise RuntimeError('MANIFEST_TARGET_UNVERIFIED')
                remote, expected, digest, status = row
                info = json.loads(command('rclone', 'lsjson', remote, '--stat', '--retries', '2', '--timeout', '30s'))
                size = info['Size']
                if not 0 <= size <= 65536:
                    raise RuntimeError('TARGET_SIZE_CHANGED')
                content = command('rclone', 'cat', remote, '--head', '65537', '--retries', '2', '--timeout', '30s')
                if len(content) != size:
                    raise RuntimeError('TARGET_READ_INCOMPLETE')
                path = work / f'sample-{index}.bin'
                path.write_bytes(content)
                report = {'sample': index, 'log_size': log_size, 'manifest_status': status,
                          'remote_bytes': size, 'manifest_size_matches': size == expected,
                          'manifest_hash_matches': hashlib.sha256(content).hexdigest() == digest,
                          'payload_kind': inspect_bytes(content), **inspect_file(path)}
                reports.append(report)
            db.close()
            # Source metadata only. The encrypted profile is restored to temporary
            # storage and is never refreshed/uploaded by this audit.
            try:
                from playwright.sync_api import sync_playwright
                from src.gphotos_web_backup import BoundedClient, export_cookies, execute
                from gpwc import payloads
                profile = Path(os.path.expanduser('~/gphotos-profile'))
                cookies = work / 'cookies.txt'
                with sync_playwright() as pw:
                    context = pw.chromium.launch_persistent_context(str(profile),
                        executable_path=os.environ['CHROME_BIN'], headless=True,
                        args=['--disable-dev-shm-usage', '--no-first-run'])
                    try:
                        page = context.pages[0] if context.pages else context.new_page()
                        page.goto('https://photos.google.com/', wait_until='domcontentloaded', timeout=90000)
                        page.wait_for_timeout(3000)
                        export_cookies(context, cookies)
                    finally:
                        context.close()
                logging.disable(logging.CRITICAL)
                client = BoundedClient(cookies, log_level='CRITICAL')
                for report, (media, _) in zip(reports, targets):
                    try:
                        ext = execute(client, payloads.GetItemInfoExt(media_key=media))
                        source_size = getattr(ext, 'size', None)
                        report['source_metadata_read'] = True
                        report['source_bytes'] = source_size
                        report['source_size_matches'] = source_size == report['remote_bytes'] if source_size else None
                    except Exception:
                        report['source_metadata_read'] = False
            except Exception:
                for report in reports:
                    report.setdefault('source_metadata_read', False)
            for report in reports:
                report['usable_video_confirmed'] = bool(report['ffprobe_ok'] and report['video_streams']
                    and report['payload_kind'] != 'html' and report.get('source_size_matches') is not False)
            print('MEDIA_AUDIT=' + json.dumps({'read_only': True, 'samples': reports}, sort_keys=True))
        finally:
            db.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Do not print provider messages, paths, URLs, cookies or media IDs.
        code = str(exc) if isinstance(exc, RuntimeError) and re.fullmatch('[A-Z_]+', str(exc)) else type(exc).__name__
        print('MEDIA_AUDIT_FAILED code=' + code)
        raise SystemExit(1)
