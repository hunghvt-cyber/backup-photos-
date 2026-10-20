## 2026-10-20 public-runner upgrade — current policy

Both Photos and Drive repositories were verified public. The old private-repository
2,000-minute budget below is historical and no longer controls Photos schedules.
Daily now has a 25-minute engine budget / 40-minute job cap. Historical Backfill
runs daily at 04:45 ICT, with a 5-hour engine / 330-minute job cap.

`src/gphotos_web_backup.py` replaces grid scrolling in Backfill with pinned gpwc
read-only requests: Archive, library, album list, every album page. SQLite tables
`web_tasks`, `web_items`, `web_albums`, `web_album_items` extend the existing
manifest without resetting media or Daily checkpoints. Pagination and membership
are saved to Koofr after each page. Album metadata stays private in manifest.sqlite;
photos are stored once under Photos, not duplicated into album directories.

Downloads require original URL and filename, compare expected size when available,
then reuse existing SHA/Koofr verification. Missing originals are errors; no
thumbnail substitution. There are no Google mutations/deletions. Failed items
rotate behind unattempted items. The encrypted Chrome profile supplies temporary
cookies; plaintext cookies are deleted and never committed or uploaded.

Local validation: 25 tests pass. Live validation pending: feature-branch push
executes a bounded 10-item / 15-minute engine trial, with 60-second inventory.
Do not claim full coverage or throughput before real WEB_PAGE/WEB_SUMMARY logs.
`inventory_complete` describes one finished traversal, not a verified full backup.
Shared album originals may be inaccessible and are left as errors; library is
never modified to obtain them. Rollback: restore previous Backfill module command.

# Shared GitHub Actions free-tier operating budget

Updated: 2026-10-15. Source of truth for both
[`google-photos-koofr`](https://github.com/hunghvt-cyber/google-photos-koofr)
and
[`my-backup-gdrive-koofr`](https://github.com/hunghvt-cyber/my-backup-gdrive-koofr).

## Decision

Keep both repos **private** and run unattended backups within a conservative
planning envelope assuming **GitHub Free = 2,000 standard runner minutes per
billing month**. Keep Google Photos as the ONLY source of Photos backup (no
Google Takeout or mobile device uploads). This is a quota plan, not a guarantee
of no charges: all other private repos, manual reruns and extra jobs share the
account's quota. GitHub Pro or a different plan has other limits.

### Scheduled workflows, Vietnam local time (UTC+7)

| Workflow | UTC cron | ICT schedule | Job hard cap | Internal worker cap |
| --- | --- | --- | --- | --- |
| Drive ↔ Koofr `bisync.yml` | `0 19 * * *` | 02:00 daily | **35 min** | rclone **29 min**, interrupt grace up to 2 min; state/artifact/log reserve |
| Photos `daily.yml` | `17 20 * * *` | 03:17 daily | **9 min** | `MAX_RUNTIME_SECONDS=300` and **240s external watchdog** |
| Photos `backfill.yml` | `45 21 * * 0,2,4,6` | 04:45 **Mon/Wed/Fri/Sun** | **20 min** | `MAX_RUNTIME_SECONDS=720`; **660s watchdog**; browser profile/log reserve |
| Photos `reconcile.yml` | `41 19 1 1,4,7,10 *` | 02:41 **2nd day of Jan/Apr/Jul/Oct** | **60 min** | `MAX_RUNTIME_SECONDS=2400` and **2700s watchdog** |

The rclone deadline is set **after preparation**; the job cap includes setup.
The Photos worker budget is set inside Python and pauses near its deadline,
while the outer shell `timeout` is a fail-safe if a browser request hangs.
The `if: always()` profile, cache, cleanup and report steps run after a
*step failure*; they cannot execute after GitHub forcibly kills the whole job.
This is why worker deadlines are substantially shorter than job deadlines.

**Efficiency rationale:** Profile restore/persistence is paid on each Photos
Backfill run. Running a 20-minute Backfill four days a week may process more
historical media per billed minute than seven very short runs. **Photos Daily
continues every single day.** The history queue remains in SQLite on Koofr
between runs; existing remote photos are not deleted.

### Worst-case calendar-month projection (GitHub Free)

A 31-day month has at most **18** Mon/Wed/Fri/Sun scheduled Backfill days.
Assuming every scheduled job reaches its **full** timeout:

| Workflow | Max runs | Max minutes |
| --- | ---: | ---: |
| Drive Bisync | 31 | 31 × 35 = **1,085** |
| Photos Daily | 31 | 31 × 9 = **279** |
| Photos Backfill | 18 | 18 × 20 = **360** |
| Photos Quarterly Reconcile (only if applicable) | 1 | **60** |
| **Total, including quarterly run** | | **1,784 min** |
| **Remaining from a 2,000-min Free allotment** | | **216 min** |

The 216-minute difference is **not** an account-wide safe balance: additional
workflow runs, manual resync, other repositories, job reruns and billing-cycle
boundaries can consume it. GitHub may queue scheduled jobs and run them later.
Only [GitHub Billing](https://github.com/settings/billing) shows actual current
monthly entitlement/usage for the owner. Set an Actions spending budget or
spending restriction and alerts for 75%, 90% and 100% if available. Configure
a no-overage spending limit when zero extra charges are required. Do not
expose Google Photos/Koofr secrets or switch repos public just to save minutes.

### Drive extended/manual restoration

Normal automatic Drive sync is intentionally bounded at 35min/job / 29min
for rclone. The previous 5h30 job/5h sync path is preserved as the
**manually enabled** `extended_budget=true` workflow_dispatch input, alongside
`resync` and `reset`. Select it only for one-off major migrations/recovery
and only after checking monthly quota, since it may exceed the planned
2,000-minute free allocation. Do **not** use `reset` casually.

If regular Drive bisync exceeds its 29-minute rclone budget, it reports
`BISYNC PAUSED AT 29-MIN BUDGET`; the workflow saves its rclone cache,
ignore list, artifact and summary for continuation. It does NOT mark an
unfinished resync as completely synchronized. Repeated pauses warrant
investigation; do not silently raise scheduled runner timeouts.

### Quarterly inventory

Quarterly Photos Reconcile is **report-only**, no deletion; it has a 60m
job cap and a shorter internal scanner budget. If inventory is too large to
complete within a run, report `PAUSED` and continue from its Koofr state
on a subsequent run; never claim a complete historical inventory from a
partial checkpoint. Quarterly runs and daily Photos jobs share
`concurrency: google-photos-koofr-state` so their Koofr manifest and
encrypted Chrome profile are not written concurrently.

### Diagnostics to check after rollout

1. Drive: action run end status and artifacts `bisync-report-<run_id>`,
   `rclone_exit_code`, `BISYNC SUCCESS` versus `BISYNC PAUSED`;
   caches and ignored file lists must be saved. Latest observed normal
   bisync: ~27 min rclone, ~28.3 min full job (2026-10-14 run 38520318431).
2. Photos Daily: `DAILY_HEALTH` and `daily-health-<run_id>`.
   Latest observed sample: ~3.6 min complete.
3. Photos Backfill: `BACKFILL_SUMMARY`, `uploaded`, `errors`,
   `manifest_uploaded_total`, `pending_seen`, `uploaded_per_hour`,
   `PROFILE_PERSIST_SECONDS`, and `PROFILE_ARCHIVE_BYTES`.
   Latest verified run 38658212741: **44 uploads**, 276 media discovered,
   22.8min job with previous, longer quotas.
4. A `timeout` exit 124 or missing JSON summary is a warning that the
   task may have been forcibly interrupted. Review state/manifest before
   trusting the green/red job result.

The new budgets and watchdogs require live run validation. Do not promise
that every scheduled job will finish before the job cap or that all image
errors have been fixed. The priority is preserving durable Koofr state and
making incremental progress in a cost-controlled way.
