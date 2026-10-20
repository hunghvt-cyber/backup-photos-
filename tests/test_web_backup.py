import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch, MagicMock
from src.gphotos_sync import DB
from src.gphotos_web_backup import WebBackup


def item(key):
    return NS(media_key=key, timestamp=1700000000000, timezone_offset=0, video_duration=None)


class WebInventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = DB(Path(self.tmp.name) / 'state.sqlite')
        self.e = NS(db=db, left=lambda: 9999, flush=lambda: None,
                    stats={'discovered': 0, 'attempted': 0, 'errors': 0})
        self.web = WebBackup(self.e, object())

    def tearDown(self):
        self.e.db.c.close()
        self.tmp.cleanup()

    def test_archive_library_albums_and_existing_uploaded_preserved(self):
        self.e.db.touch('same', 'photo', 'old', None, None)
        self.e.db.done('same', 'x.jpg', 1, 'hash', 'remote')
        def respond(client, request):
            if request.rpcid == 'lcxiM':
                return NS(items=[item('same')], next_page_id=None)
            if request.rpcid == 'Z5xsfc':
                return NS(items=[NS(media_key='album', title='Private title', item_count=1)], next_page_id=None)
            return NS(items=[item('same')], next_page_id=None)
        with patch('src.gphotos_web_backup.execute', side_effect=respond):
            self.web.inventory(5)
        self.assertTrue(self.e.db.uploaded('same'))
        self.assertEqual(self.e.db.c.execute('SELECT COUNT(*) FROM media').fetchone()[0], 1)
        self.assertEqual(self.e.db.c.execute('SELECT * FROM web_album_items').fetchall(), [('album', 'same')])
        self.assertFalse(self.e.db.c.execute('SELECT 1 FROM web_tasks WHERE done=0').fetchone())

    def test_cursor_saved_only_after_page_success_and_resumes(self):
        self.e.db.c.execute("UPDATE web_tasks SET done=1 WHERE key!='archive'")
        calls = []
        def respond(client, request):
            calls.append(request.data)
            if len(calls) == 1:
                return NS(items=[item('a')], next_page_id='page2')
            raise RuntimeError('network')
        with patch('src.gphotos_web_backup.execute', side_effect=respond):
            self.web.inventory(5)
        self.assertEqual(self.web.inventory_failures, 1)
        row = self.e.db.c.execute("SELECT page,done FROM web_tasks WHERE key='archive'").fetchone()
        self.assertEqual(row, ('page2', 0))
        restarted = WebBackup(self.e, object())
        with patch('src.gphotos_web_backup.execute', side_effect=RuntimeError) as get:
            restarted.inventory(5)
        self.assertEqual(get.call_args.args[1].data[0], 'page2')
        self.assertEqual(get.call_args.args[1].data[-1], 2)

    def test_large_archive_does_not_starve_library_or_album_index(self):
        calls = []
        def respond(client, request):
            calls.append((request.rpcid, request.data))
            if len(calls) == 4:
                self.e.left = lambda: 0
                raise RuntimeError('stop fixture')
            return NS(items=[], next_page_id='next-' + str(len(calls)))
        with patch('src.gphotos_web_backup.execute', side_effect=respond):
            self.web.inventory(5)
        self.assertEqual(calls[0][1][-1], 2)
        self.assertEqual(calls[1][1][-1], 1)
        self.assertEqual(calls[2][0], 'Z5xsfc')

    def test_failed_archive_keeps_cursor_and_other_sources_continue(self):
        def respond(client, request):
            if request.rpcid == 'lcxiM' and request.data[-1] == 2:
                raise RuntimeError('unavailable archive')
            return NS(items=[], next_page_id=None)
        with patch('src.gphotos_web_backup.execute', side_effect=respond):
            self.web.inventory(5)
        rows = dict(self.e.db.c.execute('SELECT key,done FROM web_tasks'))
        self.assertEqual(rows, {'archive': 0, 'library': 1, 'index': 1})
        self.assertEqual(self.web.inventory_failures, 1)

    def test_unedited_original_requires_matching_source_size(self):
        self.e.wd = Path(self.tmp.name)
        response = MagicMock()
        response.__enter__.return_value = response
        response.headers = {'Content-Type': 'image/jpeg'}
        response.iter_content.return_value = [b'original']
        client = NS(session=NS(get=MagicMock(return_value=response)))
        self.web.client = client
        metadata = [NS(download_original_url=None, download_url='https://lh3.googleusercontent.com/original'),
                    NS(file_name='photo.jpg', size=8)]
        with patch('src.gphotos_web_backup.execute', side_effect=metadata):
            path, name = self.web.download(None, '', 'x')
        self.assertEqual(path.read_bytes(), b'original')
        self.assertEqual(name, 'photo.jpg')
        response.iter_content.return_value = [b'bad']
        with patch('src.gphotos_web_backup.execute', side_effect=metadata):
            with self.assertRaises(RuntimeError):
                self.web.download(None, '', 'x')
        self.assertFalse(path.exists())

    def test_signed_original_rpc_fallback_preserves_size_check(self):
        self.e.wd = Path(self.tmp.name)
        response = MagicMock()
        response.__enter__.return_value = response
        response.headers = {'Content-Type': 'video/mp4'}
        response.iter_content.return_value = [b'video']
        self.web.client = NS(session=NS(get=MagicMock(return_value=response)))
        with patch('src.gphotos_web_backup.execute', side_effect=[
                NS(download_original_url=None, download_url=None),
                NS(file_name='clip.mp4', size=5),
                [[None, 'https://video-downloads.googleusercontent.com/original']]]) as rpc:
            path, name = self.web.download(None, '', 'video')
        self.assertEqual(path.read_bytes(), b'video')
        request = rpc.call_args.args[1]
        self.assertEqual(request.rpcid, 'pLFTfd')
        self.assertEqual(request.data, [['video'], [1]])

    def test_missing_original_never_downloads_thumbnail(self):
        with patch('src.gphotos_web_backup.execute', side_effect=[NS(download_original_url=None, download_url=None), NS(size=123), []]):
            with self.assertRaisesRegex(RuntimeError, 'Web original download failed'):
                self.web.download(None, 'unused', 'a')


if __name__ == '__main__':
    unittest.main()
