"""Standalone stdlib publisher, copied unchanged to each backup repository.
Only sanitized terminal summaries from the approved workflow may be published.
"""
import hashlib
import hmac
import json
import math
import os
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, HTTPRedirectHandler, build_opener

SOURCES = {
    'hunghvt-cyber/backup-photos': ('gdrive', 'gdrive-koofr', 'bisync.yml'),
    'hunghvt-cyber/backup-drive': ('gphotos', 'gphotos-koofr', 'daily.yml'),
    'hunghvt-cyber/my-backup-gdrive-koofr': ('gdrive', 'gdrive-koofr', 'bisync.yml'),
    'hunghvt-cyber/google-photos-koofr': ('gphotos', 'gphotos-koofr', 'daily.yml'),
}
# Keep the deployed GAS/reader contract stable: old GitHub names redirect to
# the same verified repositories. Validate actual workflow identity BEFORE
# translating this public link; never accept arbitrary repo or workflow names.
WIRE_REPOS = {'gdrive': 'hunghvt-cyber/my-backup-gdrive-koofr',
              'gphotos': 'hunghvt-cyber/google-photos-koofr'}
MAX_INT = 9007199254740991


def endpoint(value):
    u = urlparse(value)
    if (u.scheme != 'https' or u.netloc != 'script.google.com' or u.query or u.fragment
            or not re.fullmatch(r'/macros/s/[\w-]{20,200}/exec', u.path)):
        raise ValueError('INVALID_REPORT_URL')
    return value


def normalize(report, env):
    repo = env.get('GITHUB_REPOSITORY')
    if repo not in SOURCES:
        raise ValueError('UNAPPROVED_REPOSITORY')
    source, label, workflow = SOURCES[repo]
    if not env.get('GITHUB_WORKFLOW_REF', '').startswith(repo+'/.github/workflows/'+workflow+'@refs/'):
        raise ValueError('UNAPPROVED_WORKFLOW')
    fields = {'schema_version','source','run_id','run_url','status','started_at','finished_at','metrics','warnings'}
    if not isinstance(report, dict) or set(report) != fields:
        raise ValueError('INVALID_REPORT_FIELDS')
    ids = {}
    for name in ('run_id','run_number','run_attempt'):
        raw = env.get('GITHUB_'+name.upper(), '')
        if not re.fullmatch(r'[1-9][0-9]*', raw) or int(raw) > MAX_INT:
            raise ValueError('INVALID_RUN_IDENTITY')
        ids[name] = int(raw)
    if (type(report['schema_version']) is not int or report['schema_version'] != 1
            or type(report['run_id']) is not int or report['run_id'] != ids['run_id']
            or report['source'] != label
            or report['run_url'] != 'https://github.com/'+repo+'/actions/runs/'+str(ids['run_id'])
            or report['status'] not in ('success','paused','failure','unknown')):
        raise ValueError('INVALID_REPORT_IDENTITY')
    for name in ('started_at','finished_at'):
        value = report[name]
        if name == 'started_at' and value is None:
            continue
        if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)', value):
            raise ValueError('INVALID_REPORT_TIME')
        datetime.fromisoformat(value.replace('Z','+00:00'))
    expected = ({'transferred_gib','speed_mib_s','ignored_count','new_ignored_count'} if source == 'gdrive'
                else {'discovered','attempted','uploaded','skipped','errors','boundary_seen','bootstrap_complete'})
    metrics = report['metrics']
    if not isinstance(metrics, dict) or set(metrics) != expected:
        raise ValueError('INVALID_REPORT_METRICS')
    for name, value in metrics.items():
        if value is None:
            continue
        if source == 'gphotos' and name == 'bootstrap_complete':
            valid = type(value) is bool
        elif source == 'gphotos' and name == 'boundary_seen' and type(value) is bool:
            valid = True
        elif name in ('transferred_gib','speed_mib_s'):
            valid = type(value) in (int,float) and math.isfinite(value) and 0 <= value <= MAX_INT
        else:
            valid = type(value) is int and 0 <= value <= MAX_INT
        if not valid:
            raise ValueError('INVALID_REPORT_METRICS')
    warnings = ['Có shortcut bị hỏng.'] if source == 'gdrive' else ['Backup chưa hoàn tất hoặc có lỗi; xem GitHub Actions.']
    if not isinstance(report['warnings'], list) or len(report['warnings']) > 4 or any(x not in warnings for x in report['warnings']):
        raise ValueError('INVALID_REPORT_WARNINGS')
    return source, {**report, **ids,
                    'run_url': 'https://github.com/'+WIRE_REPOS[source]+'/actions/runs/'+str(ids['run_id'])}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(url, body):
    opener = build_opener(NoRedirect)
    try:
        response = opener.open(Request(url, data=body, headers={'Content-Type':'application/json'}, method='POST'), timeout=10)
    except HTTPError as error:
        if error.code not in (301,302,303):
            raise ValueError('REPORT_HTTP_FAILED') from None
        target = error.headers.get('Location','')
        error.close()
        u = urlparse(target)
        if u.scheme != 'https' or u.netloc != 'script.googleusercontent.com':
            raise ValueError('REPORT_REDIRECT_FORBIDDEN')
        response = opener.open(Request(target, method='GET'), timeout=10)
    with response:
        if response.status != 200:
            raise ValueError('REPORT_HTTP_FAILED')
        raw = response.read(16385)
        if len(raw) > 16384:
            raise ValueError('REPORT_RESPONSE_TOO_LARGE')
        return json.loads(raw)


def publish(report, env, request=request_json, pause=time.sleep):
    source, normalized = normalize(report, env)
    url = endpoint(env.get('REPORT_GAS_URL',''))
    key = env.get('REPORT_GAS_KEY','')
    if not re.fullmatch(r'[a-f0-9]{64}', key):
        raise ValueError('INVALID_REPORT_KEY')
    text = json.dumps(normalized, ensure_ascii=True, separators=(',',':'), allow_nan=False)
    if len(text.encode()) > 8192:
        raise ValueError('REPORT_TOO_LARGE')
    digest = hashlib.sha256(text.encode()).hexdigest()
    request_id = str(uuid.uuid5(uuid.NAMESPACE_URL, env['GITHUB_REPOSITORY']+':'+digest))
    for attempt in range(3):
        payload = json.dumps({'version':1,'source':source,'op':'publish','issuedAt':int(time.time()*1000),
                             'requestId':request_id,'reportText':text}, separators=(',',':'))
        body = json.dumps({'payload':payload,'signature':hmac.new(key.encode(),payload.encode(),hashlib.sha256).hexdigest()}, separators=(',',':')).encode()
        try:
            result = request(url, body)
            signed, signature = result.get('payload'), result.get('signature')
            if not isinstance(signed,str) or not isinstance(signature,str):
                raise ValueError('ACK_UNSIGNED')
            expected = hmac.new(key.encode(),signed.encode(),hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected,signature):
                raise ValueError('ACK_INVALID')
            ack = json.loads(signed)
            if ack.get('requestId') != request_id:
                raise ValueError('ACK_WRONG_REQUEST')
            if ack.get('ok') is not True:
                code = ack.get('code')
                if code in ('STALE_REPORT','REPORT_CONFLICT','RUN_ID_MISMATCH','IDEMPOTENCY_MISMATCH'):
                    raise ValueError(code)
                raise ValueError('REPORT_REJECTED')
            if ack.get('sha256') != digest or any(type(ack.get(k)) is not int or ack[k] != normalized[k] for k in ('run_id','run_number','run_attempt')):
                raise ValueError('ACK_WRONG_CONTENT')
            return {'published':True,'source':source,'run_id':normalized['run_id'],'run_attempt':normalized['run_attempt'],'replay':ack.get('replay') is True}
        except Exception as error:
            if str(error) in ('STALE_REPORT','REPORT_CONFLICT','RUN_ID_MISMATCH','IDEMPOTENCY_MISMATCH') or attempt == 2:
                raise
            pause(attempt+1)


SAFE_ERRORS = frozenset(('ACK_UNSIGNED','ACK_INVALID','ACK_WRONG_REQUEST','ACK_WRONG_CONTENT',
    'AUTH_DENIED','NOT_CONFIGURED','BUSY','REQUEST_EXPIRED','REPORT_REJECTED',
    'STALE_REPORT','REPORT_CONFLICT','RUN_ID_MISMATCH','IDEMPOTENCY_MISMATCH',
    'INVALID_REPORT_KEY','INVALID_REPORT_URL','REPORT_HTTP_FAILED','REPORT_REDIRECT_FORBIDDEN',
    'REPORT_RESPONSE_TOO_LARGE','INVALID_BACKUP_REPORT',
    'UNAPPROVED_REPOSITORY','UNAPPROVED_WORKFLOW','INVALID_REPORT_IDENTITY'))

def safe_error(error):
    return str(error) if str(error) in SAFE_ERRORS else 'REQUEST_FAILED'

def probe(env):
    source = SOURCES[env['GITHUB_REPOSITORY']][0]
    key = env.get('REPORT_GAS_KEY','')
    if not re.fullmatch(r'[a-f0-9]{64}',key):
        raise ValueError('INVALID_REPORT_KEY')
    payload = json.dumps({'version':1,'source':source,'op':'logs','issuedAt':int(time.time()*1000),
                          'requestId':str(uuid.uuid4())},separators=(',',':'))
    body=json.dumps({'payload':payload,'signature':hmac.new(key.encode(),payload.encode(),hashlib.sha256).hexdigest()}).encode()
    result=request_json(endpoint(env.get('REPORT_GAS_URL','')),body)
    signed,signature=result.get('payload'),result.get('signature')
    if not isinstance(signed,str) or not isinstance(signature,str):
        code=result.get('code')
        raise ValueError(code if code in ('AUTH_DENIED','NOT_CONFIGURED') else 'ACK_UNSIGNED')
    if not hmac.compare_digest(hmac.new(key.encode(),signed.encode(),hashlib.sha256).hexdigest(),signature):
        raise ValueError('ACK_INVALID')
    ack=json.loads(signed)
    if ack.get('requestId') != json.loads(payload)['requestId']:
        raise ValueError('ACK_WRONG_REQUEST')
    if ack.get('ok') is not True:
        raise ValueError(ack.get('code') if ack.get('code') in SAFE_ERRORS else 'REPORT_REJECTED')
    print(json.dumps({'source':source,'signed_ack':True,'codes':[e.get('code') for e in ack.get('events',[]) if e.get('code') in ('COMMITTED','REPLAY','INVALID_BACKUP_REPORT')]}))


def main():
    if len(sys.argv) != 2:
        raise ValueError('REPORT_FILE_REQUIRED')
    if sys.argv[1] == '--probe':
        return probe(os.environ)
    path = Path(sys.argv[1])
    with path.open('rb') as handle:
        raw = handle.read(8193)
    if len(raw) > 8192:
        raise ValueError('REPORT_TOO_LARGE')
    result = publish(json.loads(raw), os.environ)
    print(json.dumps(result,separators=(',',':')))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('BACKUP_REPORT_PUBLISH_FAILED: '+safe_error(error),file=sys.stderr)
        raise SystemExit(1)
