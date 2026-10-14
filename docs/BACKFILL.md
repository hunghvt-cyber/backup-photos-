# Google Photos Historical Backfill — Grid Scanner V2

## Current status

The October 14 trial [run 38527073559](https://github.com/hunghvt-cyber/google-photos-koofr/actions/runs/38527073559) failed. It uploaded 0 images, found 3 items, and looped in viewer navigation. Its manifest nevertheless confirmed **93 uploaded media** in total, and 6 errors still pending. The previous viewer-based downloader is kept as `src/gphotos_backfill.py` for investigation **but is not used by production Backfill workflow anymore**.

The active workflow now invokes **`python3 -m src.gphotos_backfill_grid`**, whose runtime has not yet been confirmed through a live Actions run. Do not claim full library coverage or >100 images per run before observing actual logs.

## Scheduled operation

- Daily new-photo backup: 03:17 Vietnam time, unchanged.
- Historical Backfill: **04:45 Vietnam time** every day, manually dispatchable.
- Manual trial: Actions > Google Photos Historical Backfill > Run workflow > branch `main` > `max_items=10`.
- Default historical batch size: **100 attempted downloads**. Increase to 300 only after repeated verified success.
- Runner timeout: 240 minutes; engine budget 200 minutes.
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
The second phase attempts at most `max_items` media, with at most two old
errors added at the end of the queue when there is spare capacity. A permanently
broken download should not repeatedly block all historical progress.

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
