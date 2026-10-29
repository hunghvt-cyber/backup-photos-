import contextlib
import io
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from src.gphotos_sync import wait_for_library, Engine


class LibraryReadinessTests(unittest.TestCase):
    def page(self, counts, url='https://photos.google.com/'):
        page=MagicMock()
        page.url=url
        page.locator.return_value.count.side_effect=counts
        return page

    def test_slow_library_waits_without_changing_location_or_credentials(self):
        page=self.page([0,0,1])
        wait_for_library(page,timeout_ms=1500,poll_ms=500)
        self.assertEqual(page.wait_for_timeout.call_count,2)
        page.goto.assert_not_called()

    def test_login_and_consent_fail_immediately_without_private_urls_in_log(self):
        for host,code in [('accounts.google.com','AUTH_REQUIRED'),('consent.google.com','CONSENT_REQUIRED')]:
            page=self.page([],url='https://'+host+'/secret-account?private=hidden')
            out=io.StringIO()
            with contextlib.redirect_stdout(out),self.assertRaisesRegex(RuntimeError,'GOOGLE_PHOTOS_'+code):
                wait_for_library(page)
            self.assertEqual(out.getvalue(),'PHOTOS_LIBRARY_STATUS='+code+'\n')
            page.wait_for_timeout.assert_not_called()

    def test_empty_or_changed_gallery_is_failure_not_success(self):
        page=self.page([0,0,0])
        with self.assertRaisesRegex(RuntimeError,'GOOGLE_PHOTOS_GALLERY_NOT_READY'):
            wait_for_library(page,timeout_ms=1000,poll_ms=500)
        self.assertEqual(page.wait_for_timeout.call_count,2)

    def test_auth_redirect_after_initial_loading_is_detected(self):
        page=self.page([0])
        page.wait_for_timeout.side_effect=lambda _:setattr(page,'url','https://accounts.google.com/login')
        with self.assertRaisesRegex(RuntimeError,'GOOGLE_PHOTOS_AUTH_REQUIRED'):
            wait_for_library(page,timeout_ms=1000)

    def test_failed_scan_closes_browser_and_does_not_enumerate(self):
        engine=Engine.__new__(Engine)
        engine.a=SimpleNamespace(profile='synthetic',chrome='synthetic')
        engine.visible=MagicMock()
        page=self.page([],url='https://accounts.google.com/login')
        context=MagicMock();context.pages=[page]
        pw=MagicMock();pw.chromium.launch_persistent_context.return_value=context
        with self.assertRaisesRegex(RuntimeError,'GOOGLE_PHOTOS_AUTH_REQUIRED'):
            engine.scan(pw)
        context.close.assert_called_once()
        engine.visible.assert_not_called()
