"""Reproduce tiny WebP payloads masquerading as MP4 originals."""
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import MagicMock, patch
from src.gphotos_sync import Engine, DB, validate_media


class MediaIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'sample'

    def tearDown(self):
        self.tmp.cleanup()

    def test_webp_preview_is_recognized_as_image_and_rejected_for_video(self):
        self.path.write_bytes(b'RIFF\x00\x00\x00\x00WEBP' + b'preview')
        self.assertEqual(validate_media(self.path, 'actual.webp'), 'photo')
        with self.assertRaisesRegex(RuntimeError, 'IMAGE_PREVIEW_INSTEAD_OF_VIDEO'):
            validate_media(self.path, 'original.mp4', 'photo')

    def test_source_video_type_cannot_be_disguised_by_image_filename(self):
        self.path.write_bytes(b'\xff\xd8\xffimage')
        with self.assertRaisesRegex(RuntimeError, 'IMAGE_PREVIEW_INSTEAD_OF_VIDEO'):
            validate_media(self.path, 'preview.jpg', 'video')

    def test_ffprobe_image_stream_is_not_a_video_confirmation(self):
        self.path.write_bytes(b'unknown bytes')
        probe=NS(returncode=0, stdout=json.dumps({'format': {'format_name': 'webp_pipe'}, 'streams': [{'codec_type': 'video'}]}))
        with patch('src.gphotos_sync.subprocess.run', return_value=probe):
            with self.assertRaisesRegex(RuntimeError, 'INVALID_OR_STILL_IMAGE_VIDEO'):
                validate_media(self.path, 'original.mp4')

    def test_browser_rejects_preview_before_returning_or_uploading(self):
        engine=Engine.__new__(Engine)
        engine.a=NS(profile='unused', chrome='unused')
        engine.wd=Path(self.tmp.name)
        page=MagicMock();context=MagicMock();context.pages=[page]
        download=NS(suggested_filename='clip.mp4',save_as=lambda p:Path(p).write_bytes(b'RIFF1234WEBPpreview'))
        page.expect_download.return_value.__enter__.return_value.value=download
        pw=NS(chromium=NS(launch_persistent_context=MagicMock(return_value=context)))
        with self.assertRaisesRegex(RuntimeError, 'IMAGE_PREVIEW_INSTEAD_OF_VIDEO'):
            engine.download(pw,'https://photos.google.com/photo/x','x')
        self.assertFalse((engine.wd/'x__clip.mp4').exists())
        context.close.assert_called_once()

    def test_preview_does_not_reach_remote_or_manifest_success(self):
        self.path.write_bytes(b'RIFF1234WEBPpreview')
        engine=Engine.__new__(Engine);engine.db=DB(Path(self.tmp.name)/'state.sqlite')
        engine.stats=dict(attempted=0,uploaded=0,errors=0,skipped=0)
        engine.download=MagicMock(return_value=(self.path,'clip.mp4'))
        engine.remote=MagicMock();engine.flush=MagicMock();engine.left=lambda:1000
        engine.one(None,'x','video','url',None,None)
        self.assertEqual(engine.stats['errors'],1)
        self.assertFalse(engine.db.uploaded('x'))
        engine.remote.assert_not_called()
        engine.db.c.close()

    def repair_engine(self, data, filename='clip.mp4', digest=None):
        import hashlib
        engine=Engine.__new__(Engine)
        engine.db=DB(Path(self.tmp.name)/'repair.sqlite')
        engine.db.touch('x','photo','url',None,None)
        engine.db.done('x',filename,len(data),digest or hashlib.sha256(data).hexdigest(),'koofr:Photos/'+filename)
        engine.a=NS(root='koofr:Photos')
        engine.left=lambda:1000
        engine.flush=MagicMock()
        return engine

    def test_requeue_requires_matching_bytes_and_preserves_old_file_reference(self):
        data=b'RIFF1234WEBPpreview'
        engine=self.repair_engine(data)
        before=engine.db.c.execute('SELECT remote,sha256,uploaded_at FROM media').fetchone()
        with patch('src.gphotos_sync.subprocess.run',return_value=NS(returncode=0,stdout=data)) as run:
            engine.recheck_small_video_records()
        self.assertEqual(engine.db.c.execute('SELECT status FROM media').fetchone()[0],'error')
        self.assertEqual(engine.db.c.execute('SELECT remote,sha256,uploaded_at FROM media').fetchone(),before)
        self.assertEqual(run.call_args.args[0][1],'cat')
        engine.flush.assert_called_once()
        engine.db.c.close()

    def test_requeue_refuses_unverified_bytes(self):
        data=b'RIFF1234WEBPpreview'
        engine=self.repair_engine(data,digest='wrong-hash')
        with patch('src.gphotos_sync.subprocess.run',return_value=NS(returncode=0,stdout=data)):
            engine.recheck_small_video_records()
        self.assertTrue(engine.db.uploaded('x'))
        engine.flush.assert_not_called()
        engine.db.c.close()

    def test_real_image_record_is_not_reclassified_or_requeued(self):
        engine=self.repair_engine(b'RIFF1234WEBPpreview',filename='image.webp')
        with patch('src.gphotos_sync.subprocess.run') as run:
            engine.recheck_small_video_records()
        run.assert_not_called()
        self.assertTrue(engine.db.uploaded('x'))
        engine.db.c.close()

    def test_verified_real_video_corrects_manifest_type(self):
        clip=Path(self.tmp.name)/'video.mp4'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=size=32x32:rate=2','-t','1','-c:v','mpeg4',str(clip)],check=True,capture_output=True)
        engine=Engine.__new__(Engine);engine.db=DB(Path(self.tmp.name)/'actual.sqlite')
        engine.stats=dict(attempted=0,uploaded=0,errors=0,skipped=0)
        engine.download=MagicMock(return_value=(clip,'clip.mp4'))
        engine.remote=MagicMock(return_value=('koofr:Photos/video.mp4',True))
        engine.verify_remote_size=MagicMock();engine.flush=MagicMock();engine.cp={}
        engine.one(None,'x','photo','url',None,None)
        self.assertEqual(engine.db.c.execute('SELECT type,status FROM media').fetchone(),('video','uploaded'))
        engine.db.c.close()

    def test_repair_collision_chooses_new_hash_path_preserving_old_objects(self):
        engine=Engine.__new__(Engine);engine.a=NS(root='koofr:Photos')
        engine.wd=Path(self.tmp.name)
        responses=[NS(returncode=0,stdout='1582 old.mp4'),NS(returncode=0,stdout='1234 old.mp4'),NS(returncode=4,stdout='')]
        with patch('src.gphotos_sync.cmd',side_effect=responses) as run:
            path,reused=engine.remote(None,'clip.mp4','media-id','0123456789abcdefxxx',1835388)
        self.assertIn('__0123456789abcdef.mp4',path)
        self.assertFalse(reused)
        self.assertTrue(all(call.args[1]=='lsl' for call in run.call_args_list))

    def test_remote_read_failure_is_not_permission_to_overwrite(self):
        engine=Engine.__new__(Engine);engine.a=NS(root='koofr:Photos')
        with patch('src.gphotos_sync.cmd',return_value=NS(returncode=1,stdout='')):
            with self.assertRaisesRegex(RuntimeError,'REMOTE_EXISTENCE_UNCONFIRMED'):
                engine.remote(None,'clip.mp4','media-id','hash',100)

    def test_real_mp4_with_duration_and_video_stream_is_accepted(self):
        clip=Path(self.tmp.name)/'real.mp4'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=size=32x32:rate=2','-t','1','-c:v','mpeg4',str(clip)],check=True,capture_output=True)
        self.assertEqual(validate_media(clip,'original.mp4','video'),'video')


if __name__=='__main__':
    unittest.main()
