"""Upload one sanitized JSON report to the dedicated PUBLIC Vercel Blob store."""
import json, os, sys
from pathlib import Path
from datetime import datetime
from vercel.blob import put

def main():
    if len(sys.argv)!=3:
        raise SystemExit("Usage: publish_blob_report.py REPORT.json BLOB-PATH.json")
    token=os.getenv("BLOB_READ_WRITE_TOKEN","")
    if not token:
        print("::notice::BLOB_READ_WRITE_TOKEN missing; report publishing disabled")
        return
    path=Path(sys.argv[1])
    pathname=sys.argv[2]
    if pathname not in ("gdrive-backup-latest.json","gphotos-backup-latest.json"):
        raise ValueError("Unapproved public report pathname")
    report=json.loads(path.read_text(encoding="utf-8"))
    assert report.get("schema_version")==1
    assert report.get("source") in ("gdrive-koofr","gphotos-koofr")
    assert report.get("status") in ("success","paused","failure","unknown")
    assert isinstance(report.get("run_id"),int) and report["run_id"]>0
    assert isinstance(report.get("metrics"),dict)
    assert isinstance(report.get("warnings"),list)
    payload=(json.dumps(report,ensure_ascii=False,separators=(",",":"))+"\n").encode()
    if len(payload)>8192:
        raise ValueError("Public report too large")
    result=put(pathname,payload,access="public",add_random_suffix=False,overwrite=True,content_type="application/json",cache_control_max_age=60,token=token,multipart=False)
    print("Published",pathname,"to",result.url)

if __name__=="__main__":
    main()
