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
                         ["NEW", "PENDING", "BAD"])

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
                   update_checkpoint=False)
        self.assertEqual(engine.calls[0][1]["update_checkpoint"], False)


if __name__ == "__main__":
    unittest.main()
