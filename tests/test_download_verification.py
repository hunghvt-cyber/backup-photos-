"""Fault regressions: never turn uncertain media or stalled scans into success."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch
from src.gphotos_sync import DB, Engine
from src.gphotos_web_backup import WebBackup, DownloadError


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.e = Engine.__new__(Engine)
        self.e.db = DB(Path(self.tmp.name) / 'state.sqlite')
        self.e.wd = Path(self.tmp.name)
        self.e.left = lambda: 1000
        self.e.flush = MagicMock()
        self.e.stats = dict(discovered=0, attempted=0, uploaded=0, skipped=0, errors=0)
        self.e.a = NS(maxitems=100, root='koofr:media')
        self.e.cp = dict(newest_id='boundary', bootstrap_complete=True)
        self.e.seen = set()

    def tearDown(self):
        self.e.db.c.close()
        self.tmp.cleanup()

    def response(self, data, content_type='image/jpeg'):
        r = MagicMock()
        r.__enter__.return_value = r
        r.headers = {'Content-Type': content_type}
        r.iter_content.return_value = [data]
        return r

    def web(self, responses):
        client = NS(session=NS(get=MagicMock(side_effect=responses)))
        return WebBackup(self.e, client)

    def metadata(self, size=8):
        return [NS(download_original_url=None, download_url='https://lh3.googleusercontent.com/first'),
                NS(file_name='photo.jpg', size=size),
                [[None, 'https://video-downloads.googleusercontent.com/second']]]

    def test_wrong_size_uses_second_route_and_keeps_validated_file(self):
        w = self.web([self.response(b'bad'), self.response(b'original')])
        with patch('src.gphotos_web_backup.execute', side_effect=self.metadata()) as rpc:
            path, _ = w.download(None, '', 'media')
        self.assertEqual(path.read_bytes(), b'original')
        self.assertEqual(rpc.call_args.args[1].rpcid, 'pLFTfd')
        self.assertEqual(w.client.session.get.call_count, 2)

    def test_both_routes_wrong_size_leave_no_file(self):
        w = self.web([self.response(b'bad'), self.response(b'bad')])
        with patch('src.gphotos_web_backup.execute', side_effect=self.metadata()):
            with self.assertRaisesRegex(RuntimeError, 'ORIGINAL_SIZE_MISMATCH'):
                w.download(None, '', 'media')
        self.assertFalse((self.e.wd / 'media__photo.jpg').exists())

    def test_html_and_403_can_use_valid_original_fallback(self):
        for first in (self.response(b'<html>', 'text/html'), self.response(b'')):
            if first.headers['Content-Type'] != 'text/html':
                first.raise_for_status.side_effect = RuntimeError('secret signed URL')
            w = self.web([first, self.response(b'original')])
            with patch('src.gphotos_web_backup.execute', side_effect=self.metadata()):
                path, _ = w.download(None, '', 'media')
            self.assertEqual(path.read_bytes(), b'original')
            path.unlink()

    def test_reserve_does_not_request_or_leave_partial_file(self):
        w = self.web([])
        self.e.left = lambda: 100
        with patch('src.gphotos_web_backup.execute', side_effect=self.metadata()):
            with self.assertRaisesRegex(RuntimeError, 'STOP_RESERVE'):
                w.download(None, '', 'media')
        w.client.session.get.assert_not_called()

    def test_fallback_never_accepts_thumbnail_host(self):
        w = self.web([self.response(b'bad')])
        meta = self.metadata()
        meta[-1] = ['https://untrusted.invalid/picture']
        with patch('src.gphotos_web_backup.execute', side_effect=meta):
            with self.assertRaisesRegex(RuntimeError, 'ORIGINAL_URL_REJECTED'):
                w.download(None, '', 'media')
        self.assertEqual(w.client.session.get.call_count, 1)

    def test_temporary_remote_listing_failure_retries_without_upload(self):
        with patch('src.gphotos_sync.cmd', side_effect=[NS(returncode=1, stdout=''), NS(returncode=0, stdout=''), NS(returncode=0, stdout='8 photo.jpg')]) as run, patch('src.gphotos_sync.time.sleep'):
            self.e.verify_remote_size('koofr:file', 8)
        self.assertEqual(run.call_count, 3)
        self.assertTrue(all(c.args[1] == 'lsl' for c in run.call_args_list))

    def test_unconfirmed_or_wrong_remote_never_marks_uploaded(self):
        for result in (NS(returncode=0, stdout=''), NS(returncode=0, stdout='7 photo.jpg')):
            f = self.e.wd / 'download'; f.write_bytes(b'original')
            self.e.download = MagicMock(return_value=(f, 'photo.jpg'))
            self.e.remote = MagicMock(return_value=('koofr:file', True))
            with patch('src.gphotos_sync.cmd', return_value=result), patch('src.gphotos_sync.time.sleep'):
                self.e.one(None, 'media', 'photo', 'url', None, None)
            self.assertFalse(self.e.db.uploaded('media'))
            self.assertEqual(self.e.db.c.execute('SELECT status FROM media WHERE id=?', ('media',)).fetchone()[0], 'error')

    def test_stalled_scan_preserves_boundary_and_never_claims_bootstrap(self):
        self.e.scan = MagicMock(return_value=[])
        with patch('src.gphotos_sync.sync_playwright', return_value=MagicMock()):
            report = self.e.daily()
        self.assertEqual(report['scan_status'], 'SCAN_STALLED')
        self.assertFalse(self.e.cp['bootstrap_complete'])
        self.assertEqual(self.e.cp['newest_id'], 'boundary')
        self.assertEqual(self.e.scan.call_count, 3)

    def test_boundary_advances_only_after_error_free_batch(self):
        for errors in (0, 1):
            self.e.stats['errors'] = errors
            self.e.cp['newest_id'] = 'boundary'
            self.e.seen = set()
            self.e.scan = MagicMock(return_value=[('new', 'photo', 'url', None, None), ('boundary', 'photo', 'url', None, None)])
            self.e.one = MagicMock()
            with patch('src.gphotos_sync.sync_playwright', return_value=MagicMock()):
                report = self.e.daily()
            self.assertEqual(report['scan_status'], 'BOUNDARY_REACHED')
            self.assertEqual(self.e.cp['newest_id'], 'new' if errors == 0 else 'boundary')

    def test_browser_403_fallback_uses_completed_browser_download(self):
        import urllib.error
        context = MagicMock()
        page = MagicMock()
        context.pages = [page]
        request = NS(url='https://lh3.googleusercontent.com/media', all_headers=lambda: {})
        download = NS(suggested_filename='photo.jpg', save_as=lambda dest: Path(dest).write_bytes(b'original'))
        page.expect_request.return_value.__enter__.return_value.value = request
        page.expect_download.return_value.__enter__.return_value.value = download
        pw = NS(chromium=NS(launch_persistent_context=MagicMock(return_value=context)))
        self.e.a.profile = 'unused'; self.e.a.chrome = 'unused'
        with patch('src.gphotos_sync.urllib.request.urlopen', side_effect=urllib.error.HTTPError(request.url, 403, 'Forbidden', {}, None)):
            path, name = self.e.download(pw, 'https://photos.google.com/photo/media', 'media')
        self.assertEqual(path.read_bytes(), b'original')
        self.assertEqual(name, 'photo.jpg')
        context.close.assert_called_once()

    def test_scan_collects_intermediate_viewports_before_closing_profile(self):
        context = MagicMock()
        page = MagicMock()
        context.pages = [page]
        page.locator.return_value.count.return_value = 1
        pw = NS(chromium=NS(launch_persistent_context=MagicMock(return_value=context)))
        self.e.a.profile = 'unused'; self.e.a.chrome = 'unused'
        rows = [[(str(i), 'photo', 'url', None, None)] for i in range(4)]
        self.e.visible = MagicMock(side_effect=rows)
        with patch('src.gphotos_backfill_grid.advance_gallery'):
            found = self.e.scan(pw)
        self.assertEqual([r[0] for r in found], ['0', '1', '2', '3'])
        context.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
