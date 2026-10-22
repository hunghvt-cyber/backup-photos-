"""Compare exact inventories and restart state; never touch Google or Koofr."""
import contextlib
import io
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from src.gphotos_sync import DB
from src.gphotos_web_backup import WebBackup


class InventorySpeedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = DB(Path(self.tmp.name) / 'manifest.sqlite')
        self.remote = Path(self.tmp.name) / 'remote.sqlite'
        self.e = NS(db=self.db, left=lambda: 9999,
                    a=NS(inventory_refresh_seconds=86400, inventory_checkpoint_pages=10),
                    stats={'discovered': 0, 'attempted': 0, 'errors': 0})
        self.e.flush = Mock(side_effect=lambda: self.db.snapshot(self.remote))
        self.web = WebBackup(self.e, object())
        self.db.touch('backlog', 'photo', 'url', None, None)

    def tearDown(self):
        self.db.c.close()
        self.tmp.cleanup()

    def complete(self, stamp):
        self.db.c.execute('UPDATE web_tasks SET done=1')
        if stamp is not None:
            self.db.c.execute("INSERT OR REPLACE INTO web_inventory_meta VALUES('completed_at',?)", (str(stamp),))
        self.db.c.commit()

    @staticmethod
    def empty(client, request):
        return NS(items=[], next_page_id=None)

    def test_recent_completed_inventory_with_backlog_makes_no_requests(self):
        self.complete(time.time())
        with patch('src.gphotos_web_backup.execute') as rpc:
            self.web.inventory(10)
        rpc.assert_not_called()
        self.e.flush.assert_not_called()
        self.assertEqual(self.db.c.execute('SELECT COUNT(*) FROM media').fetchone()[0], 1)

    def test_expired_missing_invalid_future_stamps_do_not_skip(self):
        for stamp in (None, time.time()-86401, 'invalid', time.time()+100, 'nan'):
            with self.subTest(stamp=stamp):
                self.db.c.execute('DELETE FROM web_inventory_meta')
                self.complete(stamp)
                with patch('src.gphotos_web_backup.execute', side_effect=self.empty) as rpc:
                    self.web.inventory(10)
                self.assertEqual(rpc.call_count, 3)

    def test_no_backlog_still_refreshes_even_when_recent(self):
        self.complete(time.time())
        self.db.done('backlog', 'a.jpg', 1, 'h', 'remote')
        with patch('src.gphotos_web_backup.execute', side_effect=self.empty) as rpc:
            self.web.inventory(10)
        self.assertEqual(rpc.call_count, 3)

    def test_daily_defaults_refresh_even_with_recent_stamp(self):
        self.e.a = NS()
        self.complete(time.time())
        with patch('src.gphotos_web_backup.execute', side_effect=self.empty) as rpc:
            self.web.inventory(10)
        self.assertEqual(rpc.call_count, 3)

    def test_partial_cursor_always_resumes_and_final_batch_is_durable(self):
        self.complete(time.time())
        self.db.c.execute("UPDATE web_tasks SET done=0,page='resume-token' WHERE key='archive'")
        with patch('src.gphotos_web_backup.execute', side_effect=self.empty) as rpc:
            self.web.inventory(10)
        self.assertEqual(rpc.call_args.args[1].data[0], 'resume-token')
        with sqlite3.connect(self.remote) as saved:
            self.assertFalse(saved.execute('SELECT 1 FROM web_tasks WHERE done=0').fetchone())
            self.assertIsNotNone(saved.execute('SELECT value FROM web_inventory_meta').fetchone())

    def test_source_failure_checkpoints_successful_pages_and_keeps_failed_cursor(self):
        def result(client, request):
            if request.rpcid == 'lcxiM' and request.data[-1] == 2:
                raise RuntimeError('source unavailable')
            return self.empty(client, request)
        with patch('src.gphotos_web_backup.execute', side_effect=result):
            self.web.inventory(10)
        with sqlite3.connect(self.remote) as saved:
            self.assertEqual(saved.execute("SELECT done FROM web_tasks WHERE key='archive'").fetchone()[0], 0)
            self.assertFalse(saved.execute('SELECT 1 FROM web_inventory_meta').fetchone())
            self.assertEqual(saved.execute("SELECT done FROM web_tasks WHERE key='library'").fetchone()[0], 1)

    def test_batch_reduces_remote_writes_with_identical_final_rows(self):
        outputs = []
        for batch in (1, 10):
            self.db.c.execute('UPDATE web_tasks SET done=0,page=NULL')
            self.e.a.inventory_checkpoint_pages = batch
            self.e.flush.reset_mock()
            count = 0
            def result(client, request):
                nonlocal count
                count += 1
                # Only one source active, 100 pages, same media IDs for A/B.
                entry = NS(media_key='media-'+str(count),timestamp=None,timezone_offset=0,video_duration=None)
                return NS(items=[entry], next_page_id=str(count) if count < 100 else None)
            self.db.c.execute("UPDATE web_tasks SET done=1 WHERE key!='archive'")
            with contextlib.redirect_stdout(io.StringIO()), patch('src.gphotos_web_backup.execute', side_effect=result):
                self.web.inventory(10)
            with sqlite3.connect(self.remote) as saved:
                rows = saved.execute('SELECT id FROM web_items ORDER BY id').fetchall()
                cursor = saved.execute('SELECT kind,key,page,done FROM web_tasks ORDER BY kind,key').fetchall()
            outputs.append((self.e.flush.call_count, rows, cursor))
        self.assertEqual(outputs[0][1:], outputs[1][1:])
        self.assertEqual((outputs[0][0],outputs[1][0]), (101, 11))

    def test_slow_pages_checkpoint_after_sixty_seconds_before_batch_limit(self):
        self.db.c.execute("UPDATE web_tasks SET done=1 WHERE key!='archive'")
        clock = [0]
        saves = []
        def save():
            saves.append(self.db.c.execute('SELECT COUNT(*) FROM web_items').fetchone()[0])
        self.e.flush = Mock(side_effect=save)
        def result(client, request):
            clock[0] += 31
            number = clock[0] // 31
            entry = NS(media_key='slow-'+str(number), timestamp=None, timezone_offset=0, video_duration=None)
            if number == 3:
                self.e.left = lambda: 0
            return NS(items=[entry], next_page_id='next-'+str(number))
        with contextlib.redirect_stdout(io.StringIO()), patch('src.gphotos_web_backup.time.monotonic', side_effect=lambda: clock[0]), patch('src.gphotos_web_backup.execute', side_effect=result):
            self.web.inventory(1000)
        self.assertEqual(saves, [2, 3])

    def test_hard_stop_replays_only_uncheckpointed_pages(self):
        self.db.c.execute("UPDATE web_tasks SET done=1 WHERE key!='archive'")
        calls = 0
        def result(client, request):
            nonlocal calls
            calls += 1
            if calls == 13:
                raise KeyboardInterrupt('simulated hard stop')
            entry = NS(media_key='item-'+str(calls),timestamp=None,timezone_offset=0,video_duration=None)
            return NS(items=[entry], next_page_id='token-'+str(calls))
        with contextlib.redirect_stdout(io.StringIO()), patch('src.gphotos_web_backup.execute', side_effect=result):
            with self.assertRaises(KeyboardInterrupt):
                self.web.inventory(10)
        with sqlite3.connect(self.remote) as saved:
            self.assertEqual(saved.execute('SELECT COUNT(*) FROM web_items').fetchone()[0],10)
            self.assertEqual(saved.execute("SELECT page FROM web_tasks WHERE key='archive'").fetchone()[0],'token-10')
        # No upload is performed during inventory: repeating pages cannot lose media.
        self.assertEqual(self.db.c.execute('SELECT COUNT(*) FROM web_items').fetchone()[0],12)


if __name__ == '__main__':
    unittest.main()
