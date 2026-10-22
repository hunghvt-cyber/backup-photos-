# Final Backfill aggregate publication — 22 October 2026

The Backfill-completed workflow_run callback reads the existing final health artifact. It
has no Koofr/Google secrets; only this job receives GitHub contents:write and
reads the current run's health artifact. The engine retains contents:read.
The publisher validates fixed repo/workflow/ref, original run identity and SHA,
measurement time and exact safe metric types. It publishes counts only to
reports/backfill:backfill-latest.json. That branch contains no workflows.
Old order cannot overwrite newer (run_number,run_attempt); exact replay is no-op;
same-order different content or run identity fails. File SHA prevents lost writes.
It does not publish a Daily report, access media, or alter GAS/manifest/profile.

Initial snapshot is real final WEB_SUMMARY from completed run 39519576698:
2026-10-21T05:12:03.006913Z, manifest 1640 uploaded, 45515 seen pending,
105 errors, 47247 inventoried, 49 albums, inventory_complete=false.
These counts do not prove original media identity or full library coverage.

Homepage's separate API reads this public aggregate and latest Backfill run
metadata. It labels old snapshots during new runs. Existing Daily GAS unchanged.
See Homepage-nas/docs/BACKFILL-PROGRESS-20261022.md for schema/limits.

Current running 39698534252 keeps its original engine checkout. The separate
main-branch callback can publish its final artifact once it ends, without
changing or restarting that worker. Publication remains unverified until a real
callback finishes. Only reviewed main code executes; artifacts are JSON data,
not code. The callback verifies the source run is completed Backfill on main.

Validation: 60 Python tests pass locally, including publisher allowlist,
missing summary, wrong workflow, stale update, identity conflict and replay.
