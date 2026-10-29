import contextlib, io, json, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch
from gpwc import Client
from src.gphotos_sync import DB
from src.gphotos_web_backup import (BoundedClient, browser_bootstrap, validated_bootstrap,
                                    execute, main, safe_navigation_location, navigation_diagnostics)


def bootstrap():
    return dict(FdrFJe='synthetic-session',cfb2h='synthetic-build',SNlM0e='private-token',
                Im6cmf='/_/PhotosUi',oPEP7c='private@example.invalid')

class BootstrapTests(unittest.TestCase):
    def test_navigation_location_allowlists_host_and_redacts_unknown_path(self):
        safe = safe_navigation_location('https://www.google.com/sorry/private@example.invalid?token=secret#frag')
        self.assertEqual(safe, {'host': 'www.google.com', 'path': '/sorry/[redacted]'})
        self.assertEqual(safe_navigation_location('https://evil.invalid/private?token=secret'),
                         {'host': '[other-host]', 'path': '/[redacted]'})

    def test_navigation_chain_records_only_main_frame_safe_location_and_status(self):
        page = MagicMock(); page.main_frame = object()
        chain = navigation_diagnostics(page)
        handlers = {call.args[0]: call.args[1] for call in page.on.call_args_list}
        request = MagicMock(); request.is_navigation_request.return_value = True
        request.frame = page.main_frame
        request.url = 'https://accounts.google.com/private@example.invalid?token=secret'
        handlers['request'](request)
        response = MagicMock(); response.request = request; response.status = 302
        handlers['response'](response)
        self.assertEqual(chain, [{'host': 'accounts.google.com', 'path': '/[redacted]', 'http_status': 302}])

    def test_bootstrap_only_skips_engine_state_and_reports_sanitized_navigation(self):
        with tempfile.TemporaryDirectory() as temp:
            page = MagicMock(); page.url = 'https://www.google.com/sorry/private?token=secret'
            page.goto.return_value = NS(status=429)
            browser = MagicMock(); browser.pages = [page]
            pw = MagicMock(); pw.chromium.launch_persistent_context.return_value = browser
            manager = MagicMock(); manager.__enter__.return_value = pw
            out = io.StringIO()
            with patch('sys.argv', ['worker', '--bootstrap-only']), \
                 patch.dict('os.environ', {'GPHOTOS_PROFILE_DIR': temp}), \
                 patch('src.gphotos_web_backup.Engine') as engine, \
                 patch('src.gphotos_web_backup.sync_playwright', return_value=manager), \
                 contextlib.redirect_stdout(out):
                result = main()
            self.assertEqual(result, 1)
            engine.assert_not_called()
            self.assertIn("executable_path='/usr/bin/google-chrome-stable'", str(pw.chromium.launch_persistent_context.call_args))
            text = out.getvalue()
            self.assertNotIn('secret', text)
            self.assertIn('"path":"/sorry/[redacted]","http_status":429', text)
            self.assertIn('WEB_BOOTSTRAP_STATUS=CHALLENGE_REQUIRED', text)
    def test_upstream_missing_script_reproduces_indexerror(self):
        with self.assertRaises(IndexError):
            Client.__new__(Client).parse_main_page('<html><script>window.WIZ_global_data = {};</script></html>')

    def test_browser_wait_does_not_require_script_attribute_or_media_tiles(self):
        page=MagicMock();page.url='https://photos.google.com/';page.evaluate.side_effect=[None,bootstrap()]
        out=io.StringIO()
        with contextlib.redirect_stdout(out):data=browser_bootstrap(page,timeout_ms=1000)
        self.assertEqual(data,bootstrap());page.wait_for_timeout.assert_called_once_with(500)
        page.locator.assert_not_called();self.assertEqual(out.getvalue(),'WEB_BOOTSTRAP_STATUS=READY\n')

    def test_login_or_consent_never_logs_private_url(self):
        for host,code in [('accounts.google.com','AUTH_REQUIRED'),('consent.google.com','CONSENT_REQUIRED')]:
            page=MagicMock();page.url='https://'+host+'/private@example.invalid?token=private-token';out=io.StringIO()
            with contextlib.redirect_stdout(out),self.assertRaisesRegex(RuntimeError,'WEB_'+code):browser_bootstrap(page)
            page.evaluate.assert_not_called();page.wait_for_timeout.assert_not_called()
            self.assertEqual(out.getvalue(),'WEB_BOOTSTRAP_STATUS='+code+'\n')

    def test_missing_or_invalid_metadata_fails_closed_with_bounded_wait(self):
        page=MagicMock();page.url='https://photos.google.com/';page.evaluate.return_value={'SNlM0e':'private-token'}
        with self.assertRaisesRegex(RuntimeError,'WEB_BOOTSTRAP_UNAVAILABLE'):browser_bootstrap(page,timeout_ms=1000)
        self.assertEqual(page.wait_for_timeout.call_count,2)
        for invalid in [None,{},dict(bootstrap(),Im6cmf='//evil.invalid'),dict(bootstrap(),FdrFJe=1)]:
            with self.assertRaisesRegex(RuntimeError,'WEB_BOOTSTRAP_INCOMPLETE'):validated_bootstrap(invalid)

    def test_account_display_field_is_optional_for_rpc_bootstrap(self):
        data=bootstrap();del data['oPEP7c']
        self.assertEqual(validated_bootstrap(data)['oPEP7c'],'redacted')

    def test_google_challenge_stops_without_trying_another_route(self):
        page=MagicMock();page.url='https://www.google.com/sorry/index?private-token'
        out=io.StringIO()
        with contextlib.redirect_stdout(out),self.assertRaisesRegex(RuntimeError,'WEB_CHALLENGE_REQUIRED'):
            browser_bootstrap(page)
        page.evaluate.assert_not_called();page.wait_for_timeout.assert_not_called()
        self.assertNotIn('private-token',out.getvalue())

    def test_client_reuses_tokens_without_second_html_fetch(self):
        with tempfile.TemporaryDirectory() as temp:
            cookies=Path(temp)/'cookies.txt';cookies.write_text('# Netscape HTTP Cookie File\n');cookies.chmod(0o600)
            with patch('requests.Session.get',side_effect=AssertionError('second HTML fetch')) as get:
                client=BoundedClient(cookies,bootstrap_data=bootstrap(),log_level='CRITICAL')
            get.assert_not_called();self.assertEqual(client.global_data,bootstrap())
            self.assertEqual(client.session.request.keywords['timeout'],(30,120));client.session.close()

    def test_rpc_shape_error_is_not_empty_inventory(self):
        payload=NS(execute=MagicMock(side_effect=IndexError('private-token')))
        with self.assertRaisesRegex(RuntimeError,'^WEB_RPC_SCHEMA_CHANGED$'):execute(object(),payload)

    def test_fatal_bootstrap_preserves_real_counts_and_attempts_no_upload(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);db=DB(root/'state.sqlite')
            db.touch('uploaded-id','photo','private',None,None);db.done('uploaded-id','private.jpg',8,'hash','private')
            db.touch('pending-id','photo','private',None,None)
            e=NS(sd=root,wd=root/'downloads',db=db,stats=dict(discovered=0,attempted=0,uploaded=0,skipped=0,errors=0),flush=MagicMock(),one=MagicMock())
            e.wd.mkdir();page=MagicMock();page.url='https://accounts.google.com/login?private-token'
            browser=MagicMock();browser.pages=[page]
            pw=MagicMock();pw.chromium.launch_persistent_context.return_value=browser
            manager=MagicMock();manager.__enter__.return_value=pw;out=io.StringIO()
            with patch('sys.argv',['worker','--maxitems','1']),patch('src.gphotos_web_backup.Engine',return_value=e),patch('src.gphotos_web_backup.sync_playwright',return_value=manager),contextlib.redirect_stdout(out):result=main()
            self.assertEqual(result,1);e.one.assert_not_called();browser.close.assert_called_once()
            text=out.getvalue();self.assertNotIn('private-token',text);self.assertNotIn('private.jpg',text)
            self.assertIn('stage=browser_bootstrap',text)
            report=json.loads(next(x.split('=',1)[1] for x in text.splitlines() if x.startswith('WEB_SUMMARY=')))
            self.assertEqual(report['manifest_uploaded_total'],1);self.assertEqual(report['pending_seen'],1)
            self.assertFalse(report['inventory_complete']);self.assertTrue(report['inventory_error'])
            self.assertFalse((root/'web-cookies.txt').exists())

if __name__=='__main__':unittest.main()
