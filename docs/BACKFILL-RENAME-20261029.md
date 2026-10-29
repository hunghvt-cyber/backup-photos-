# Backfill report rename repair — 29 October 2026

## Cause and bounded scope

Canonical media repository is `hunghvt-cyber/backup-drive` (ID 1336978361).
Homepage still requested run metadata using its old name with redirect:error;
the metadata lookup failed. Its publisher also rejected the canonical callback
identity: [callback 40799546918](https://github.com/hunghvt-cyber/backup-drive/actions/runs/40799546918)
logged WRONG_WORKFLOW after the health artifact downloaded successfully.

The reader now requests the fixed canonical snapshot and workflow URLs. It
accepts exactly the canonical and historical aliases for matching run IDs,
keeps old snapshot content/timestamps unchanged, and emits canonical current-run
links. Arbitrary repos, mismatched IDs and malformed run metadata remain
rejected; redirect:error and bounded responses/timeouts remain enforced.

The publisher correction is maintained in the backup repository. It validates
canonical callback/source identity and uses canonical GitHub API endpoints;
public snapshot links retain the known historical alias for stable idempotent
replay and compatibility. Run order checks, health validation and aggregate-only
publication stay intact.

This task changes reporting only: no media worker rerun, authentication/profile
change, media copy/delete, manifest/checkpoint update, schedule change, GAS
change or Notes change. The latest source Backfill run 40799294163 failed;
fixing reports must preserve that failure outcome.

## Verification before rollout

- Homepage reader regression suite covers canonical endpoints and known historical links.
- Local adapter with real public GitHub sources: HTTP 200, both snapshot and
  current metadata available. Current is 40799294163, completed/failure;
  snapshot remains 40429013609 measured 2026-10-27T05:49:07.734744+00:00.
- Publisher tests, build, CI, production alias/readback and a report-only callback
  retry are recorded as verified only after each check completes. No newer
  aggregate is fabricated from a failed or missing summary.
