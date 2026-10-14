"""Convert existing daily-health.json to a minimal public status report."""
import json,os
from pathlib import Path
from datetime import datetime,timezone
p=Path(os.environ["RUNNER_TEMP"])/"daily-health.json"
health=json.loads(p.read_text()) if p.exists() else {}
def metric(key):
    v=health.get(key)
    return v if type(v) in (int,bool) and (type(v)==bool or v>=0) else None
raw=health.get("status")
status="success" if raw=="SUCCESS" else ("failure" if raw=="FAILED / INCOMPLETE" else "unknown")
run_id=int(os.environ["GITHUB_RUN_ID"])
report={"schema_version":1,"source":"gphotos-koofr","run_id":run_id,
"run_url":f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{run_id}",
"status":status,"started_at":None,
"finished_at":health.get("generated_at_utc") or datetime.now(timezone.utc).isoformat(),
"metrics":{k:metric(k) for k in ("discovered","attempted","uploaded","skipped","errors","boundary_seen","bootstrap_complete")},
"warnings":[] if status=="success" else ["Backup chưa hoàn tất hoặc có lỗi; xem GitHub Actions."]}
Path("gphotos-backup-summary.json").write_text(json.dumps(report,ensure_ascii=False)+"\n")
print("Prepared public Google Photos summary",run_id,status)
