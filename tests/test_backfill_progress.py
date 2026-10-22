import unittest
from scripts.publish_backfill_progress import normalize,is_newer

class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.run=dict(repository={'full_name':'hunghvt-cyber/google-photos-koofr'},head_branch='main',path='.github/workflows/backfill.yml',id=100,run_number=15,run_attempt=1,head_sha='a'*40,created_at='2026-10-20T00:00:00Z')
        self.health=dict(generated_at_utc='2026-10-20T05:00:00Z',manifest_uploaded_total=1000,pending_seen=2000,pending_errors=3,inventoried_total=3000,albums=49,album_memberships=1234,attempted=11,uploaded=10,errors=1,inventory_complete=False,raw_cookie='must not leak')
    def test_filtered_partial_progress_without_complete_backup_claim(self):
        report=normalize(self.health,self.run,'failure')
        self.assertNotIn('raw_cookie',str(report));self.assertEqual(report['metrics']['uploaded_total'],1000)
        self.assertFalse(report['metrics']['inventory_complete'])
        self.assertNotIn('percent',report['metrics'])
    def test_wrong_workflow_or_missing_summary_rejected(self):
        self.run['path']='.github/workflows/daily.yml'
        with self.assertRaises(ValueError):normalize(self.health,self.run,'success')
        self.run['path']='.github/workflows/backfill.yml';del self.health['attempted']
        with self.assertRaises(ValueError):normalize(self.health,self.run,'success')
    def test_old_rerun_cannot_replace_later_result_and_replay_is_noop(self):
        report=normalize(self.health,self.run,'failure');self.assertFalse(is_newer(report,report))
        newer={**report,'run_number':16,'run_id':101}
        with self.assertRaisesRegex(ValueError,'STALE_REPORT'):is_newer(report,newer)
    def test_same_order_conflict_and_run_identity_rejected(self):
        report=normalize(self.health,self.run,'failure')
        with self.assertRaisesRegex(ValueError,'REPORT_CONFLICT'):is_newer({**report,'outcome':'success'},report)
        with self.assertRaisesRegex(ValueError,'RUN_ID_MISMATCH'):is_newer({**report,'run_id':101},report)
    def test_boolean_and_inconsistent_counts_rejected(self):
        self.health['attempted']=True
        with self.assertRaises(ValueError):normalize(self.health,self.run,'failure')
        self.health['attempted']=1
        with self.assertRaises(ValueError):normalize(self.health,self.run,'failure')

if __name__=='__main__':unittest.main()
