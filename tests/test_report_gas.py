import hashlib
import hmac
import json
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from publish_gas_report import normalize, publish, endpoint

KEY='d'*64
def fixture(source='gdrive'):
    repo='hunghvt-cyber/'+('my-backup-gdrive-koofr' if source=='gdrive' else 'google-photos-koofr')
    workflow='bisync.yml' if source=='gdrive' else 'daily.yml'
    env={'GITHUB_REPOSITORY':repo,'GITHUB_RUN_ID':'101','GITHUB_RUN_NUMBER':'3','GITHUB_RUN_ATTEMPT':'2',
         'GITHUB_WORKFLOW_REF':repo+'/.github/workflows/'+workflow+'@refs/heads/main',
         'REPORT_GAS_URL':'https://script.google.com/macros/s/'+'x'*30+'/exec','REPORT_GAS_KEY':KEY}
    metrics=({'transferred_gib':1.2,'speed_mib_s':2,'ignored_count':0,'new_ignored_count':None} if source=='gdrive'
             else {'discovered':2,'attempted':2,'uploaded':2,'skipped':0,'errors':0,'boundary_seen':True,'bootstrap_complete':True})
    report={'schema_version':1,'source':source+'-koofr','run_id':101,'run_url':'https://github.com/'+repo+'/actions/runs/101',
            'status':'success','started_at':None,'finished_at':'2026-10-18T07:00:00.123456Z','metrics':metrics,'warnings':[]}
    return report,env

def ack(body,**changes):
    envelope=json.loads(body)
    assert envelope['signature']==hmac.new(KEY.encode(),envelope['payload'].encode(),hashlib.sha256).hexdigest()
    request=json.loads(envelope['payload']);report=json.loads(request['reportText'])
    value={'ok':True,'requestId':request['requestId'],'sha256':hashlib.sha256(request['reportText'].encode()).hexdigest(),
           **{k:report[k] for k in ('run_id','run_number','run_attempt')},**changes}
    payload=json.dumps(value,separators=(',',':'))
    return {'payload':payload,'signature':hmac.new(KEY.encode(),payload.encode(),hashlib.sha256).hexdigest()}

class BackupPublisherTests(unittest.TestCase):
    def test_both_sources_add_ordering_from_actual_workflow(self):
        for source in ('gdrive','gphotos'):
            report,env=fixture(source);actual,normalized=normalize(report,env)
            self.assertEqual(actual,source);self.assertEqual(normalized['run_number'],3);self.assertEqual(normalized['run_attempt'],2)
            self.assertNotIn('run_number',report)

    def test_private_fields_wrong_run_and_backfill_are_rejected(self):
        report,env=fixture()
        for invalid in ({**report,'private_path':'private'}, {**report,'run_id':102}, {**report,'warnings':['private filename']}):
            with self.assertRaises(ValueError):normalize(invalid,env)
        report,env=fixture('gphotos');env['GITHUB_WORKFLOW_REF']=env['GITHUB_WORKFLOW_REF'].replace('daily.yml','backfill.yml')
        with self.assertRaisesRegex(ValueError,'UNAPPROVED_WORKFLOW'):normalize(report,env)

    def test_metrics_reject_bool_for_counts_and_nonfinite_numbers(self):
        report,env=fixture()
        for name,value in (('ignored_count',True),('transferred_gib',float('nan')),('speed_mib_s',-1)):
            with self.assertRaisesRegex(ValueError,'INVALID_REPORT_METRICS'):normalize({**report,'metrics':{**report['metrics'],name:value}},env)

    def test_endpoint_and_key_validation_before_network(self):
        report,env=fixture()
        for url in ('https://script.google.com.evil.test/macros/s/x/exec','http://script.google.com/macros/s/x/exec',env['REPORT_GAS_URL']+'?key=secret'):
            with self.assertRaises(ValueError):endpoint(url)
        with self.assertRaisesRegex(ValueError,'INVALID_REPORT_KEY'):publish(report,{**env,'REPORT_GAS_KEY':'bad'},request=lambda *a:self.fail('network'))

    def test_verified_ack_and_lost_ack_retry_keep_exact_mutation(self):
        report,env=fixture();sent=[];pauses=[]
        def request(url,body):
            sent.append(json.loads(json.loads(body)['payload']))
            result=ack(body,replay=len(sent)>1)
            if len(sent)==1:raise TimeoutError('synthetic lost response')
            return result
        result=publish(report,env,request=request,pause=pauses.append)
        self.assertTrue(result['published']);self.assertTrue(result['replay']);self.assertEqual(pauses,[1])
        for key in ('requestId','reportText'):self.assertEqual(sent[0][key],sent[1][key])
        self.assertNotIn(KEY,json.dumps(result))

    def test_bad_ack_is_not_success_and_retry_is_bounded(self):
        report,env=fixture();calls=[]
        def request(url,body):calls.append(1);return ack(body,sha256='wrong')
        with self.assertRaisesRegex(ValueError,'ACK_WRONG_CONTENT'):publish(report,env,request=request,pause=lambda n:None)
        self.assertEqual(len(calls),3)

    def test_old_report_refusal_is_not_retried(self):
        report,env=fixture();calls=[]
        def request(url,body):calls.append(1);return ack(body,ok=False,code='STALE_REPORT')
        with self.assertRaisesRegex(ValueError,'STALE_REPORT'):publish(report,env,request=request,pause=lambda n:self.fail('no retry'))
        self.assertEqual(len(calls),1)
