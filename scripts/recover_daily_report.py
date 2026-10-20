"""Republish a verified original daily health artifact; never runs a backup."""
import json
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from publish_gas_report import normalize, publish, safe_error

REPO = 'hunghvt-cyber/google-photos-koofr'

def reconstruct(run, jobs, health):
    run_id = run['id']
    if (run.get('repository', {}).get('full_name') != REPO or run.get('path') != '.github/workflows/daily.yml'
        or run.get('head_branch') != 'main' or run.get('event') != 'schedule'
        or run.get('status') != 'completed' or run.get('run_attempt') != 1
        or str(health.get('run_id')) != str(run_id)
        or health.get('run_url') != f'https://github.com/{REPO}/actions/runs/{run_id}'
        or health.get('status') != 'SUCCESS' or health.get('backup_step') != 'success'
        or health.get('summary_present') is not True or health.get('errors') != 0):
        raise ValueError('UNVERIFIED_BACKUP')
    daily = [job for job in jobs['jobs'] if job.get('name') == 'daily' and job.get('run_id') == run_id]
    if len(daily) != 1:
        raise ValueError('UNVERIFIED_BACKUP')
    steps = {step['name']: step for step in daily[0]['steps']}
    for name in ('Incremental backup', 'Daily health report', 'Upload daily health artifact'):
        if steps.get(name, {}).get('conclusion') != 'success':
            raise ValueError('UNVERIFIED_BACKUP')
    stamp = health['generated_at_utc']
    if not run['run_started_at'] <= stamp <= run['updated_at']:
        raise ValueError('UNVERIFIED_BACKUP_TIME')
    return {'schema_version':1,'source':'gphotos-koofr','run_id':run_id,
            'run_url':health['run_url'],'status':'success','started_at':None,
            'finished_at':stamp,'metrics':{key:health[key] for key in
              ('discovered','attempted','uploaded','skipped','errors','boundary_seen','bootstrap_complete')},'warnings':[]}

def api(path):
    request=Request('https://api.github.com/repos/'+REPO+path,
        headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json'})
    with urlopen(request,timeout=20) as response:
        raw=response.read(1024*1024+1)
    if len(raw)>1024*1024:
        raise ValueError('RESPONSE_TOO_LARGE')
    return json.loads(raw)

def main():
    run_id=os.environ['ORIGINAL_RUN_ID']
    if not run_id.isdecimal():
        raise ValueError('INVALID_RUN')
    run=api('/actions/runs/'+run_id)
    jobs=api('/actions/runs/'+run_id+'/jobs')
    report=reconstruct(run,jobs,json.loads(Path('recovery/daily-health.json').read_text()))
    env={**os.environ,'GITHUB_REPOSITORY':REPO,'GITHUB_RUN_ID':run_id,
         'GITHUB_RUN_NUMBER':str(run['run_number']),'GITHUB_RUN_ATTEMPT':str(run['run_attempt']),
         'GITHUB_WORKFLOW_REF':REPO+'/.github/workflows/daily.yml@refs/heads/main'}
    normalize(report,env)
    print(json.dumps(publish(report,env),separators=(',',':')))

if __name__=='__main__':
    try:
        main()
    except Exception as error:
        print('REPORT_RECOVERY_FAILED: '+safe_error(error),file=sys.stderr)
        raise SystemExit(1)
