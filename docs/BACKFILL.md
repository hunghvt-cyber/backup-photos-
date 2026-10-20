> Current public-runner policy and web backup upgrade: see [AI_CONTEXT.md](../AI_CONTEXT.md). Older budget and grid-scanner notes below are historical.

# Google Photos Historical Backfill — Grid Scanner V2

## Current status

The October 14 trial [run 38527073559](https://github.com/hunghvt-cyber/google-photos-koofr/actions/runs/38527073559) failed. It uploaded 0 images, found 3 items, and looped in viewer navigation. Its manifest nevertheless confirmed **93 uploaded media** in total, and 6 errors still pending. The previous viewer-based downloader is kept as `src/gphotos_backfill.py` for investigation **but is not used by production Backfill workflow anymore**.

The active workflow now invokes **`python3 -m src.gphotos_backfill_grid`**, whose runtime has not yet been confirmed through a live Actions run. Do not claim full library coverage or >100 images per run before observing actual logs.

## Run 38531203749 and third-round fix (2026-10-14)

[Manual run 38531203749](https://github.com/hunghvt-cyber/google-photos-koofr/actions/runs/38531203749)
was green at the GitHub job level, but only uploaded **3** images (2
repeated HTTP 403/Chrome failures); it found **17** gallery media, of
which 13 were already uploaded. Manifest count rose from 93 to **96**.
The scan stopped after only six rounds, reporting
`SCROLL_END_OR_STALLED`. This was not a full-library backup.

Changes committed after the run:

- Scan progress is based on **any previously unseen gallery media ID**,
  including already uploaded photos, rather than only new upload
  candidates. Thus long runs of previously backed-up photos will not
  falsely stop historical traversal.
- Gallery scrolling now detects the nearest scrollable ancestor of media
  tiles (including hidden-overflow containers) and combines
  `scroll_into_view_if_needed`, scrolling, mouse-wheel events and
  periodic `PageDown`. A 1440×900 viewport improves thumbnail density.
- `GRID_SCROLL_DIAG` logs scroll-container metadata every five
  stagnant rounds, without disclosing filenames or image pixels.
- If the browser stops exposing new IDs for 15 rounds,
  `scan_status=SCROLL_STALLED` and the workflow exits as a failure,
  even when some uploads succeed. This prevents misleading green jobs.
- Previously failed HTTP 403 images are temporarily excluded from
  historical upload batches; they remain safely tracked in the SQLite
  manifest for a separately designed retry workflow.
- Regression tests verify that the scanner traverses many already
  uploaded items before concluding it is stalled.

**Status: not yet verified by a new authenticated Chrome run.** Run
`max_items=10` and inspect `GRID_SCAN`, `GRID_SCROLL_DIAG`,
`GRID_QUEUE`, and `BACKFILL_SUMMARY`. Only raise to 100 when
scanner-visible historical IDs grow past the first few dozen.

## 2026-10-15 — historical scanning works; optimize write amplification

Latest verified run: https://github.com/hunghvt-cyber/google-photos-koofr/actions/runs/38658212741

- `GRID_SCAN` found **276 distinct media IDs in 21.7 seconds**, with a
  real Google Photos scrollable `C-WIZ` container. The gallery-scanning
  bottleneck is now resolved for at least the first 276 items.
- `max_items=100`, but engine hit its 1,200-second time budget after
  **50 attempted downloads**; **44 verified uploads**, **6 failures**.
- Runtime reported **178.29 successful media/hour of download phase**,
  `manifest_uploaded_total=161`, `pending_seen=102`, `pending_errors=13`.
- Errors were mainly transient or persistent HTTP 403 and Chrome closure.
  The failed media are retained in the manifest, not deleted.
- GitHub run was successful because progress was nonzero and the engine
  paused intentionally. This is **not** evidence that all history is backed up.

Performance improvements committed *after* that run, not yet live benchmarked:

1. `Engine.one(..., flush_state=False)` lets only the historical Backfill
   defer remote SQLite/checkpoint uploads. `GridBackfill.run` uses this
   mode and invokes `persist("UPLOADING")` once per **10 attempted media**,
   then once at the end. This avoids two Koofr uploads for every media
   file. The SQLite manifest still commits each local success/failure.
   **The existing Daily flow keeps its immediate flush behavior.**
2. If a runner ends mid-batch, remote photo files already copied to Koofr
   are retained; the next run rechecks size/SHA before attempting a
   duplicate upload. At worst the recent unflushed media may be
   re-downloaded, but they are not deleted.
3. Strip conditional `If-None-Match`, `If-Modified-Since`, `If-Range`
   and `Range` request headers during authenticated download replay.
   This addresses HTTP **304 Not Modified** and partial-cache surprises.
   It does **not** guarantee that Google stops returning 403.
4. Exclude disposable Chrome caches (`Cache`, `Code Cache`, `GPUCache`,
   `DawnCache`, shader caches and `Crashpad`) from the encrypted
   profile archive uploaded after Daily and Backfill. Authentication
   cookies and persistent browser storage are preserved. The workflows
   now log `PROFILE_ARCHIVE_BYTES` and `PROFILE_PERSIST_SECONDS`
   so reduction can be measured.

The next run should validate (a) that the new code's offline tests pass,
(b) download throughput exceeds 178/hour, (c) profile archive is smaller
and session survives reboot, and (d) the historical media count increases.
**100 successful uploads/run is still a target, not a verified result.**

**Quota warning:** Other repositories consume the same GitHub-hosted
Actions quota. A Google Drive↔Koofr run 38520318431 lasted about 28
minutes; historical Backfill now runs Mon/Wed/Fri/Sun with a 20-minute job cap. Actual
monthly included-use headroom depends on all scheduled jobs, so
confirm GitHub billing usage before increasing any runtime limits.

## Free-tier daily operating policy (2026-10-14)

The goal is reliable incremental progress with **no need to keep Codespaces
running**. The historical backfill uses the already scheduled GitHub Actions
runner. Codespaces is reserved for development/debugging because it does not
provide unattended daily execution by itself.

- Automatic trigger: **04:45 Asia/Ho_Chi_Minh Mon/Wed/Fri/Sun**. Photos Daily still runs daily.
- Hard job cap: **20 minutes**; external runner watchdog **11 minutes**; profile/log tail reserved.
- Backup engine budget: **720 seconds = 12 minutes**, with an internal stop reserve before the worker deadline.
- Gallery scan budget: **180 seconds = 3 minutes**. Stop early on 15 rounds
  without discovering a new media ID.
- Batch default: at most **100 attempted media**, constrained by the time
  budget. This is a **limit, not a speed or success guarantee**.
- The engine leaves time to persist the encrypted Chrome profile and to
  clean temporary files before the GitHub job time limit.
- GitHub Actions Summary includes `scan_seconds`, `download_seconds`,
  `uploaded_per_hour`, and `manifest_uploaded_total`. A stalled scan or
  zero-progress budget run is marked failed, rather than green.
- Keep existing Koofr SQLite manifest, daily checkpoint and backups intact;
  Backfill remains non-destructive, one-way only.

**Free usage caveat:** GitHub Free includes 2,000 Actions minutes per billing
cycle across applicable private-repository jobs owned by the account, not
2,000 minutes separately for this repository. A 20-minute cap × at most 18 scheduled days uses **360 Backfill minutes**
in a 31-day month. The entire scheduled plan, including a quarterly
Reconcile, has an estimated worst-case ceiling of **1,784 minutes** per
31-day month, before other private repositories and manual reruns. We cannot verify the account's
remaining free quota from the backup workflow, so the run cap alone is NOT
a guaranteed no-charge safeguard. Review
https://github.com/settings/billing and activate included-usage warnings at
90% and 100%; confirm billing/spending settings separately.

**Reliability caveat:** Changing time limits does not fix Google Photos UI
scrolling. Grid scrolling was verified by run 38658212741 (276 distinct media in 21.7s);
its success is measured by discovered unique media IDs and real upload
throughput, not by the job showing a green checkmark.

Shared accounting for Drive, Daily, Backfill and quarterly Reconcile is in
[FREE_TIER_BUDGET.md](FREE_TIER_BUDGET.md). These new operating limits still
require validation on the next scheduled runs; they are not proof of zero
charges or full library coverage.

## Scheduled operation

- Daily new-photo backup: 03:17 Vietnam time, unchanged.
- Historical Backfill: **04:45 Vietnam time on Monday, Wednesday, Friday, Sunday**, manually dispatchable on other days.
- Manual trial: Actions > Google Photos Historical Backfill > Run workflow > branch `main` > `max_items=10`.
- Default historical batch size: **100 attempted downloads**. Increase to 300 only after repeated verified success.
- Runner timeout: **20 minutes**; engine budget **12 minutes** with 11-minute watchdog; scan cap **3 minutes**.
- Concurrency group: `google-photos-koofr-state`; no overlap with Daily or quarterly Reconcile.

## Two-phase design

1. Restore the persistent Chrome profile and SQLite manifest from Koofr.
2. Open `photos.google.com` in **one persistent Chrome session**, collect visible
   photo/video links and scroll the page. Scroll-container movement is logged
   as `GRID_SCAN` with `round`, `visible`, `pending`, `old`,
   `moved`, and `max_scroll`. Traverse past already-uploaded items to
   discover historical images.
3. Record all discovered media and statuses in SQLite, then **close the scanner
   browser** before any downloads. This isolates UI scanning from crashes caused
   by the native Google Photos download gesture.
4. Upload queued media through the **original Daily engine**
   `Engine.one()`, which has already succeeded in real runs. It uses an
   independent browser per item, retries transient download failures, verifies
   the remote Koofr size, and uses SQLite/media ID deduplication.
5. Download operations in Historical Backfill invoke
   `Engine.one(update_checkpoint=False)`, so the Daily newest-item cursor is
   not advanced by historical uploads.
6. Persist SQLite and `backfill-grid-checkpoint.json` to Koofr before the
   download phase and after progress. Failed media stay in manifest for retry.

The first phase aims for at least `max_items + 15` queued historical candidates
before starting uploads, subject to the runner time budget and scrolling limits.
The second phase attempts at most `max_items` media, while old HTTP-403/error items are excluded from this backfill queue and remain
tracked for a dedicated retry workflow. A permanently broken download must not
repeatedly block historical progress.

## Durable Koofr state

```
/Google Photos/.gphotos-sync/
  manifest.sqlite                 authoritative uploaded / seen / error status
  daily-checkpoint.json           Daily cursor, preserved by historical uploads
  backfill-grid-checkpoint.json   Historical scan status and progress
  backfill-checkpoint.json        Legacy viewer-engine cursor; kept for rollback
  auth/profile.tar.gz.enc         encrypted Google Chrome profile
```

No historical job deletes photos or changes the daily schedule. The scan-based
progress cursor is **not proof of end-of-library coverage**; repeated passes
against the Photos web UI and quarterly inventory checks are still important.

## Reading results

`BACKFILL_SUMMARY` and GitHub Actions Summary contain:

- `uploaded`: successful uploads this run.
- `attempted`: attempted downloads this run.
- `discovered`: unique items found on the gallery in this run (including those previously uploaded).
- `scan_rounds`, `unique_visible`: diagnostics of library traversal.
- `pending_seen`: discovered but not uploaded records.
- `pending_errors`: failed records still in the manifest.
- `manifest_uploaded_total`: cumulative number of uploaded media recorded in the SQLite manifest.
- `SCAN_INCOMPLETE`: scanning stopped or reached an unverified boundary, **not** a declaration that all photos are backed up.
- `PAUSED_LIMIT`: reached the requested download batch size.

The new scanner path must first be validated with `max_items=10`. Inspect
the `GRID_SCAN` movement and `GRID_QUEUE` count; if it finds only 10–20
media while thousands should exist, do not increase the download quota.
Fix the gallery scroll selector or use another inventory method first.

## Reference projects

- https://github.com/vikas5914/google-photos-backup
- https://github.com/jpratt9/gphotos-export
- https://github.com/perkeep/gphotos-cdp
