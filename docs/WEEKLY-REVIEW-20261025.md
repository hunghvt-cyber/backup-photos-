# Weekly read-only review — 25 October 2026

Observed 15:47 Asia/Ho_Chi_Minh, from workflow source, job/step logs, published aggregates
and Homepage APIs. No backup/media/state/profile mutation, new run, deletion or scheduler change.

| Evidence | Observed result |
| --- | --- |
| Backfill 40143977325 / source 50e381b | 746 attempted/uploaded, 0 new errors; engine/job success |
| Final snapshot | manifest uploaded 5315, pending_seen 47174, pending_errors 198, inventoried 52686, 49 albums |
| Inventory | inventory_complete=true; this is traversal state, not completed original backup |
| Daily 40138973010 | 19 uploaded, 0 errors, prior boundary reached; profile/artifact/GAS publication success |
| Callback 40162984746 | downloaded the real final artifact and published source run 40143977325 |
| Homepage APIs | /api/backfill-progress and /api/backup-report?source=gphotos both 200 and identify the correct source runs |

The live completion callback is now verified; the 22 October “first live publication
unobserved” limitation is historical. No synthetic test output was used as media evidence:
test fixtures earlier in the job log are separate from the runtime final WEB_SUMMARY.

For Vietnam dates 19–25 October, observed scheduled runs were Daily 7 (4 success/3 failure)
and Backfill 6 (1 success/5 failure). Some failures made partial progress. A green latest
run does not erase earlier failures or the existing error queue.

The 24 October diagnostic fix preserved strict source-size/content checks and added
bounded ConnectionError retries. The latest run has no new media errors, but 198 existing
error records remain; their original recovery is not proven. This audit did not re-read
the three WebP-as-MP4 files from 22 October. Manifest counts are not proof of every original.

Current workflow source still has Daily 03:17 Vietnam (25m engine/40m job), Backfill 04:45
daily (5h engine/330m job), and quarterly Reconcile 02:41 on day 2 of Jan/Apr/Jul/Oct
(40m engine/60m job). All media workers share google-photos-koofr-state. Public workflow
names remain separate even when progress is presented together. Do not change schedules
or start a second writer merely to match a historical unified-worker description.

No Reconcile runs were returned by its workflow-runs API at audit time. Its code/schedule
is not a completed reconciliation or restore test. No manual Reconcile was started.

Links:
- https://github.com/hunghvt-cyber/google-photos-koofr/actions/runs/40143977325
- https://github.com/hunghvt-cyber/google-photos-koofr/actions/runs/40138973010
- https://github.com/hunghvt-cyber/google-photos-koofr/actions/runs/40162984746
- System-level review belongs to 0219nas-aio/WEEKLY-CHECK-20261025.md.

Next evidence: validate the existing error queue without weakening size checks; separately
read back originals previously misrecorded; retain private media/account data outside Git.
