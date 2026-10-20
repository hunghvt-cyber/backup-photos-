import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from recover_daily_report import reconstruct,REPO

class RecoveryTests(unittest.TestCase):
    def fixture(self):
        run={'id':101,'repository':{'full_name':REPO},'path':'.github/workflows/daily.yml','head_branch':'main','event':'schedule','status':'completed','run_attempt':1,'run_started_at':'2026-10-19T23:45:48Z','updated_at':'2026-10-19T23:50:06Z'}
        jobs={'jobs':[{'name':'daily','run_id':101,'steps':[{'name':name,'conclusion':'success'} for name in ('Incremental backup','Daily health report','Upload daily health artifact')]}]}
        health={'run_id':'101','run_url':f'https://github.com/{REPO}/actions/runs/101','status':'SUCCESS','backup_step':'success','summary_present':True,'generated_at_utc':'2026-10-19T23:49:58.980068+00:00','discovered':8,'attempted':8,'uploaded':8,'skipped':0,'errors':0,'boundary_seen':False,'bootstrap_complete':True}
        return run,jobs,health
    def test_preserves_original_identity_time_and_metrics(self):
        run,jobs,health=self.fixture()
        report=reconstruct(run,jobs,health)
        self.assertEqual(report['run_id'],101)
        self.assertEqual(report['finished_at'],health['generated_at_utc'])
        self.assertEqual(report['metrics']['uploaded'],8)
    def test_rejects_wrong_source_incomplete_and_mismatched_artifact(self):
        run,jobs,health=self.fixture()
        for patch in ({'path':'.github/workflows/backfill.yml'},{'event':'pull_request'},{'run_attempt':2},{'head_branch':'unreviewed'}):
            with self.assertRaises(ValueError):reconstruct({**run,**patch},jobs,health)
        for patch in ({'run_id':'102'},{'errors':1},{'summary_present':False},{'generated_at_utc':'2026-10-20T23:49:58Z'}):
            with self.assertRaises(ValueError):reconstruct(run,jobs,{**health,**patch})
        broken=copy.deepcopy(jobs);broken['jobs'][0]['steps'][0]['conclusion']='failure'
        with self.assertRaises(ValueError):reconstruct(run,broken,health)
