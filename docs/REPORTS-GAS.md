# GAS report transport (opt-in)

Only the final sanitized gphotos aggregate report transport changes. The backup/sync
engine, schedule, credentials, rclone state and media paths stay unchanged.

Default repository variable REPORT_BACKEND is blob. To opt in after Google and
end-to-end tests pass, set REPORT_BACKEND=gas-drive, repository variable
REPORT_GAS_URL to the existing reporting /exec URL, and repository secret
REPORT_GAS_KEY to its dedicated BACKUP_GPHOTOS_KEY value. Never put the key in
chat, files, logs or workflow inputs. Keep BLOB_READ_WRITE_TOKEN for rollback.

scripts/publish_gas_report.py is stdlib-only and is copied unchanged from
Homepage-nas/reporting/publish_backup_report.py. No Blob SDK is installed in the
GAS path. It validates the fixed repository and workflow, sanitized fields,
run_number/run_attempt/run_id, signs requests, validates signed ack and retries
at most three times with the same mutation identity. Old/conflicting terminal
reports are refused, not overwritten. run_number ordering is scoped to the
approved workflow; do not call this publisher from backfill/reconcile.

Existing reporting continue-on-error and engine outcome conditions remain.
Moving the report does not fix private GitHub Actions billing/runner limits.
This branch has not published a real report to Google or changed production.

Local test: python3 -m unittest discover -s tests -p 'test_report_gas.py'

Complete architecture/Google deployment and Homepage cutover gates live in
Homepage-nas/docs/BACKUP-REPORTS-GAS-20261018.md. Current Google v12 does not yet
contain these backup handlers. Do not select GAS until the matching backend
is deployed, isolated synthetic qualification passes, and this workflow can run.
