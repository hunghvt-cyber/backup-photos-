"""Fast unit checks that do not require a Google login or Koofr account."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from playwright.sync_api import TimeoutError as PlaywrightTimeout

from src.gphotos_backfill import Backfill, capture_date, media_url


class BackfillTests(unittest.TestCase):
    def test_media_url_accepts_google_photos_only(self):
        self.assertEqual(media_url("https://photos.google.com/photo/MEDIA123"), "MEDIA123")
        self.assertEqual(media_url("https://photos.google.com/u/0/photo/MEDIA123"), "MEDIA123")
        with self.assertRaises(ValueError):
            media_url("https://example.com/photo/MEDIA123")

    def test_filename_capture_date(self):
        with tempfile.TemporaryDirectory() as folder:
            empty = Path(folder) / "not-a-real-jpeg"
            empty.write_bytes(b"not an image")
            self.assertEqual(capture_date(empty, "Screenshot_20261012_142735.jpg", None),
                             "2026-10-12T00:00:00")
            self.assertIsNone(capture_date(empty, "image_without_date.png", None))

    def test_older_advances_only_on_different_photo(self):
        class Page:
            def __init__(self):
                self.url = "https://photos.google.com/photo/A"
                self.keyboard = SimpleNamespace(press=self.press)
            def press(self, key):
                self.url = "https://photos.google.com/photo/B"
            def wait_for_url(self, predicate, timeout):
                if not predicate(self.url):
                    raise PlaywrightTimeout("no navigation")
            def wait_for_timeout(self, milliseconds):
                pass

        downloader = Backfill.__new__(Backfill)
        self.assertEqual(downloader.older(Page(), "A"),
                         "https://photos.google.com/photo/B")

    def test_stalled_navigation_is_not_misreported_complete(self):
        class Page:
            url = "https://photos.google.com/photo/A"
            keyboard = SimpleNamespace(press=lambda key: None)
            def wait_for_url(self, predicate, timeout):
                raise PlaywrightTimeout("no navigation")
            def wait_for_timeout(self, milliseconds):
                pass

        downloader = Backfill.__new__(Backfill)
        self.assertIsNone(downloader.older(Page(), "A"))

    def test_download_saves_browser_file_without_http_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            class Download:
                suggested_filename = "IMG_20261014.jpg"
                def save_as(self, dest):
                    Path(dest).write_bytes(b"hello-photo")
            class Event:
                value = Download()
                def __enter__(self):
                    return self
                def __exit__(self, *_):
                    return False
            class Page:
                keyboard = SimpleNamespace(press=lambda key: None)
                def expect_download(self, timeout):
                    return Event()

            downloader = Backfill.__new__(Backfill)
            downloader.engine = SimpleNamespace(wd=Path(folder))
            path, name = downloader.download(Page(), "MEDIA123")
            self.assertEqual(path.read_bytes(), b"hello-photo")
            self.assertEqual(name, "IMG_20261014.jpg")


if __name__ == "__main__":
    unittest.main()
