"""Offline regression tests for the two-phase grid backfill."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from src.gphotos_backfill_grid import GridBackfill, parse_tiles


class GridBackfillTests(unittest.TestCase):
    def test_parse_tiles_deduplicates_ids_and_keeps_photo_and_video(self):
        tiles = [
            {"href": "./photo/ABC", "label": None},
            {"href": "https://photos.google.com/photo/ABC", "label": None},
            {"href": "/video/DEF", "label": None},
            {"href": None, "label": None},
            {"href": "https://photos.google.com/", "label": None},
        ]
        result = parse_tiles(tiles)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][:3], (
            "ABC", "photo", "https://photos.google.com/photo/ABC"))
        self.assertEqual(result[1][:3], (
            "DEF", "video", "https://photos.google.com/video/DEF"))

    def test_queue_prefers_scanned_items_before_old_errors(self):
        class Cursor:
            def execute(self, sql, args=()):
                if "status='seen'" in sql:
                    return [
                        ("PENDING", "photo", "https://photos.google.com/photo/PENDING",
                         None, None)
                    ]
                if "status='error'" in sql:
                    return [
                        ("BAD", "photo", "https://photos.google.com/photo/BAD",
                         None, None)
                    ]
                raise AssertionError(sql)
        job = GridBackfill.__new__(GridBackfill)
        job.pending = {
            "NEW": ("NEW", "photo", "https://photos.google.com/photo/NEW",
                    None, None)
        }
        job.args = SimpleNamespace(maxitems=3)
        job.engine = SimpleNamespace(db=SimpleNamespace(c=Cursor()))
        self.assertEqual([r[0] for r in job.queue()],
                         ["NEW", "PENDING"])

    def test_grid_upload_uses_existing_safe_downloader_and_preserves_daily_cursor(self):
        # Tests the core isolation contract without hitting a real Google account.
        class Engine:
            def __init__(self):
                self.calls = []
            def one(self, *args, **kwargs):
                self.calls.append((args, kwargs))
        engine = Engine()
        # The runtime keyword is a safety requirement, not an optional optimization.
        engine.one(object(), "ID", "photo", "url", None, None,
                   update_checkpoint=False, flush_state=False)
        self.assertEqual(engine.calls[0][1]["update_checkpoint"], False)
        self.assertEqual(engine.calls[0][1]["flush_state"], False)

    def test_virtualized_gallery_scans_past_known_uploaded_photos(self):
        from unittest.mock import patch

        class Cursor:
            def __init__(self):
                self.status = {f"OLD{i}": "uploaded" for i in range(24)}
            def execute(self, sql, args=()):
                if "SELECT status" in sql:
                    status = self.status.get(args[0])
                    return SimpleNamespace(fetchone=lambda: (status,) if status else None)
                raise AssertionError(sql)

        cursor = Cursor()
        class DB:
            c = cursor
            def touch(self, *args):
                pass

        class Locator:
            def __init__(self, driver):
                self.driver = driver
            def evaluate_all(self, expr):
                index = min(self.driver.round_index, 26)
                if index < 24:
                    return [{"href": f"/photo/OLD{index}", "label": None}]
                return [{"href": f"/photo/NEW{index}", "label": None}]

        class Page:
            def __init__(self):
                self.round_index = 0
            def set_viewport_size(self, obj):
                pass
            def goto(self, *args, **kwargs):
                pass
            def wait_for_timeout(self, milliseconds):
                pass
            def locator(self, selector):
                return Locator(self)

        page = Page()
        browser = SimpleNamespace(pages=[page], close=Mock())
        playwright = SimpleNamespace(chromium=SimpleNamespace(
            launch_persistent_context=Mock(return_value=browser)))
        job = GridBackfill.__new__(GridBackfill)
        job.engine = SimpleNamespace(left=lambda: 8000, db=DB())
        job.args = SimpleNamespace(maxitems=10, profile="/unused", chrome="/unused")
        job.pending = {}
        job.stats = {"discovered": 0}
        job.scanned_unique = set()
        job.scan_rounds = 0
        job.scan_status = "NOT_STARTED"
        job.anchor_id = None

        def advance(page_obj, iteration):
            page_obj.round_index += 1
            return {"before": 0, "after": 100, "max": 1000, "diagnostics": []}

        with patch("src.gphotos_backfill_grid.advance_gallery", side_effect=advance):
            job.scan(playwright)

        self.assertEqual(job.stats["discovered"], 27)
        self.assertEqual(len(job.pending), 3)
        self.assertEqual(job.scan_status, "SCROLL_STALLED")
        self.assertEqual(job.scan_rounds, 42)
        self.assertEqual(browser.close.call_count, 1)


    def test_engine_batch_flush_does_not_write_checkpoint_per_media(self):
        from src.gphotos_sync import Engine
        from unittest.mock import patch
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            filepath = Path(temp) / "picture.jpg"
            filepath.write_bytes(b"JPEG")
            fake = Engine.__new__(Engine)
            fake.db = SimpleNamespace(
                touch=Mock(), uploaded=Mock(return_value=False),
                done=Mock(), err=Mock())
            fake.stats = dict(attempted=0, uploaded=0, errors=0, skipped=0)
            fake.cp = {"newest_id": "DAILY_MEDIA"}
            fake.download = Mock(return_value=(filepath, "picture.jpg"))
            fake.remote = Mock(return_value=("koofr_remote:/Photos/picture.jpg", False))
            fake.flush = Mock()
            fake.left = Mock(return_value=2000)

            def cmd_fake(*args, **kwargs):
                if args[:2] == ("rclone", "lsl"):
                    return SimpleNamespace(returncode=0, stdout="4 2026-10-15 00:00:00 picture.jpg")
                return SimpleNamespace(stdout="", returncode=0)

            with patch("src.gphotos_sync.cmd", side_effect=cmd_fake), \
                 patch("src.gphotos_sync.sha", return_value="deadbeef"):
                fake.one(None, "MEDIA1", "photo",
                         "https://photos.google.com/photo/MEDIA1",
                         None, None, update_checkpoint=False, flush_state=False)
            self.assertEqual(fake.stats["uploaded"], 1)
            self.assertEqual(fake.stats["errors"], 0)
            self.assertEqual(fake.cp["newest_id"], "DAILY_MEDIA")
            fake.db.done.assert_called_once()
            fake.flush.assert_not_called()

    def test_engine_batch_flush_preserves_error_in_manifest(self):
        from src.gphotos_sync import Engine
        fake = Engine.__new__(Engine)
        fake.db = SimpleNamespace(
            touch=Mock(), uploaded=Mock(return_value=False),
            done=Mock(), err=Mock())
        fake.stats = dict(attempted=0, uploaded=0, errors=0, skipped=0)
        fake.cp = {"newest_id": "DAILY_MEDIA"}
        fake.download = Mock(side_effect=RuntimeError("unexpected test download error"))
        fake.flush = Mock()
        fake.one(None, "MEDIA1", "photo",
                 "https://photos.google.com/photo/MEDIA1",
                 None, None, update_checkpoint=False, flush_state=False)
        fake.db.err.assert_called_once()
        fake.flush.assert_not_called()
        self.assertEqual(fake.stats["errors"], 1)


if __name__ == "__main__":
    unittest.main()
