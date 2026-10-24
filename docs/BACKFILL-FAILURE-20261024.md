# Backfill partial failure — 24/10/2026

## Runtime evidence

Source run [40042998281](https://github.com/hunghvt-cyber/google-photos-koofr/actions/runs/40042998281)
used commit `925de2ff54be6e8b57da19bdcc2aa2fcda258492`.
The worker attempted 851 media, uploaded 841 and recorded 10 errors:
9 `ORIGINAL_SIZE_MISMATCH` after both original routes, and 1 `ConnectionError`.
A separate `ReadTimeout` recovered on retry. The worker emitted `PARTIAL` and
exited 1; no watchdog termination or fatal crash was observed.
Final summary: 4550 manifest uploads, 47918 pending seen, 198 pending errors,
52655 inventoried IDs and 49 albums. These counters have different scopes;
they are not a verified full-library completion percentage.

Live inventory emitted `INVENTORY_DEFERRED` and 0 pages / 0 remote checkpoints.
This proves the recent-complete TTL branch executed, not the live performance
of checkpoint batching. The earlier inventory messages were from the 69 passing
offline tests. `inventory_complete=true` describes restored traversal state,
not completion of media backup or a fresh inventory on this date.

Publisher run [40064746599](https://github.com/hunghvt-cyber/google-photos-koofr/actions/runs/40064746599)
downloaded `web-backup-health-40042998281` and published its aggregate with
`outcome=failure`. Publisher success means report publication succeeded.
Homepage rendering was not inspected in this investigation. Profile persistence
and final artifact creation succeeded; no independent remote media/manifest
audit was performed.

## Small corrective change

- Log `ORIGINAL_SIZE_DIAGNOSTIC` with `route`, `expected_bytes`, `actual_bytes`
  before rejecting a size mismatch. Route 0 is metadata URL; route 1 is the
  signed-original RPC. No URL, filename, credentials or response body is logged.
- Recognize `ConnectionError` in the existing download retry policy. Keep the
  3-attempt cap and existing time reserve; persistent failures remain errors.
- Rename the publisher to `Publish Backfill run result`. Continue publishing
  failed runs with their real outcome so failures remain visible.

Source-size checking, payload validation, remote-size verification, concurrency,
state snapshots, schedules and quotas remain unchanged. A mismatch is still
rejected, not retried by the outer retry loop or accepted as an original.

## Validation and remaining evidence

Offline regressions cover both-route mismatch diagnostics and cleanup without
URL/filename leakage, connection-error recovery through remote verification,
retry exhaustion and the time-reserve stop. Validation: compileall succeeded,
all 71 offline tests passed, and `git diff --check` passed.
No extra production run is started for this change. Inspect the next scheduled
run for byte diagnostics and retry outcomes. Until then, the cause of the nine
size mismatches and recovery of the connection failure remain unproven.
