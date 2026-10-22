"""Publish allowlisted Backfill aggregates to an isolated GitHub report branch."""
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

REPO='hunghvt-cyber/google-photos-koofr'
BRANCH='reports/backfill'
REPORT_PATH='backfill-latest.json'
COUNTS={'uploaded_total':'manifest_uploaded_total','pending_seen':'pending_seen','pending_errors':'pending_errors',
        'inventoried_total':'inventoried_total','albums':'albums','album_memberships':'album_memberships',
        'attempted_this_run':'attempted','uploaded_this_run':'uploaded','errors_this_run':'errors'}


def stamp(value):
    parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    if parsed.utcoffset().total_seconds()!=0:raise ValueError('INVALID_TIMESTAMP')
    return parsed


def normalize(health,run,outcome):
    if (run.get('repository',{}).get('full_name')!=REPO or run.get('head_branch')!='main'
        or run.get('path')!='.github/workflows/backfill.yml' or outcome not in ('success','failure','cancelled')):
        raise ValueError('UNVERIFIED_BACKFILL_RUN')
    for key in ('id','run_number','run_attempt'):
        if type(run.get(key)) is not int or run[key]<=0:raise ValueError('INVALID_RUN_IDENTITY')
    if not re.fullmatch('[a-f0-9]{40}',run.get('head_sha','')):raise ValueError('INVALID_SOURCE_SHA')
    measured=health.get('generated_at_utc')
    if not isinstance(measured,str) or not stamp(run['created_at'])<=stamp(measured):raise ValueError('INVALID_MEASUREMENT_TIME')
    if stamp(measured).timestamp()>time.time()+300:raise ValueError('FUTURE_MEASUREMENT')
    metrics={}
    for public,private in COUNTS.items():
        value=health.get(private)
        if type(value) is not int or not 0<=value<=9007199254740991:raise ValueError('MISSING_BACKFILL_SUMMARY')
        metrics[public]=value
    if type(health.get('inventory_complete')) is not bool:raise ValueError('MISSING_BACKFILL_SUMMARY')
    metrics['inventory_complete']=health['inventory_complete']
    if metrics['uploaded_this_run']+metrics['errors_this_run']>metrics['attempted_this_run']:raise ValueError('INCONSISTENT_COUNTS')
    return dict(schema_version=1,source='gphotos-backfill',run_id=run['id'],run_number=run['run_number'],
                run_attempt=run['run_attempt'],run_url=f'https://github.com/{REPO}/actions/runs/{run["id"]}',
                source_sha=run['head_sha'],measured_at=measured,outcome=outcome,metrics=metrics)


def is_newer(new,old):
    if old is None:return True
    if new['run_number']==old['run_number'] and new['run_id']!=old['run_id']:raise ValueError('RUN_ID_MISMATCH')
    order=(new['run_number'],new['run_attempt']);prior=(old['run_number'],old['run_attempt'])
    if order<prior:raise ValueError('STALE_REPORT')
    if order==prior:
        if new!=old:raise ValueError('REPORT_CONFLICT')
        return False
    return True


def api(path,method='GET',data=None):
    raw=None if data is None else json.dumps(data).encode()
    request=urllib.request.Request('https://api.github.com/repos/'+REPO+path,data=raw,method=method,
        headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json','Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=30) as response:
        value=response.read(1000000)
    return json.loads(value)


def publish(report):
    for attempt in range(3):
        existing=api('/contents/'+REPORT_PATH+'?ref=reports%2Fbackfill')
        old=json.loads(base64.b64decode(existing['content']))
        if not is_newer(report,old):return False
        payload=dict(message='Update Backfill aggregate from run '+str(report['run_id']),branch=BRANCH,
                     sha=existing['sha'],content=base64.b64encode((json.dumps(report,separators=(',',':'))+'\n').encode()).decode())
        try:
            api('/contents/'+REPORT_PATH,'PUT',payload)
            return True
        except urllib.error.HTTPError as exc:
            if exc.code not in (409,422) or attempt==2:raise
    raise ValueError('PUBLICATION_UNCONFIRMED')


def main():
    if os.environ.get('GITHUB_REPOSITORY')!=REPO or os.environ.get('GITHUB_WORKFLOW_REF')!=REPO+'/.github/workflows/backfill.yml@refs/heads/main':
        raise ValueError('WRONG_WORKFLOW')
    run_id=os.environ['GITHUB_RUN_ID']
    if not run_id.isdecimal():raise ValueError('INVALID_RUN')
    run=api('/actions/runs/'+run_id)
    report=normalize(json.loads(Path('progress-data/daily-health.json').read_text()),run,os.environ['BACKFILL_RESULT'])
    result=publish(report)
    print(json.dumps({'backfill_progress_published':result,'run_id':report['run_id']}))


if __name__=='__main__':
    try:main()
    except Exception as exc:
        code=str(exc) if isinstance(exc,ValueError) and re.fullmatch('[A-Z_]+',str(exc)) else type(exc).__name__
        print('BACKFILL_PROGRESS_FAILED code='+code)
        raise SystemExit(1)
