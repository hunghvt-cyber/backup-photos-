# Historical Google Photos backfill (experimental)

## Purpose

The regular Daily workflow is for newly detected media only. Its
`bootstrap_complete` flag **does not prove** that thousands of older photos
have been inventoried or backed up. Historical backfill traverses photo-viewer
navigation separately and writes to the same durable SQLite manifest on Koofr.

## How to operate

- Workflow: [Google Photos Historical Backfill](../.github/workflows/backfill.yml)
- Scheduled: 21:45 UTC = **04:45 Asia/Ho_Chi_Minh**, every day.
- Runs independently from Daily (03:17 ICT), but shares the
  `google-photos-koofr-state` concurrency group so they cannot update the
  manifest or Chrome profile at the same time.
- Default: **100 attempted downloads per run**; manually choose 100 initially
  and 300 only after confirmed successful runs. Already-uploaded photos are
  skipped without using the download quota.
- Maximum per run: 240-minute GitHub Actions job and a 12,000-second engine
  budget; the engine leaves time to re-encrypt and persist the Chrome profile.
- Manual on mobile GitHub: Actions > Google Photos Historical Backfill >
  Run workflow > choose max_items > Run workflow.

## How it works

1. Restore the authenticated Chrome profile and the manifest from Koofr.
2. Prioritize historical traversal. Known error media stay in the manifest for
   separate retry instead of crashing the historical discovery session.
3. If `backfill-checkpoint.json` exists, reopen the last visited photo and
   advance once to the older item. Otherwise start at the gallery's first item.
4. Navigate photo-by-photo in **one** persistent Chrome context. Send
   Google Photos' native `Shift+D` command and use Chrome's actual download
   event and saved bytes. Unlike Daily, no second HTTP download replay.
5. Check the SHA-256 of any existing destination filename, otherwise write
   non-destructively with a media-ID suffix on collision. Upload using rclone
   and check Koofr file size after upload.
6. Save a durable SQLite manifest first, then backfill cursor, every ten
   viewed items, before restarting a crashed browser, and at the end.
   Failed media remain `status='error'` for retry.
7. Report summary and cumulative manifest count in GitHub Actions Summary.

Backfill does **not** advance the Daily newest-item cursor, delete Photos or
Koofr files, or blindly mark the entire historical library complete.

## Durable state

- `Koofr:/Google Photos/.gphotos-sync/manifest.sqlite`: media statuses and
  original capture metadata.
- `Koofr:/Google Photos/.gphotos-sync/backfill-checkpoint.json`: last viewed
  media ID, URL, status and cumulative viewer count.
- `Koofr:/Google Photos/.gphotos-sync/daily-checkpoint.json`: daily cursor,
  untouched by the backfill engine (except safe persistence of its same value).
- `Koofr:/Google Photos/.gphotos-sync/auth/profile.tar.gz.enc`: encrypted
  persistent Chrome profile.

## Limitations / release safety

First manual trial `38523118388` on 2026-10-14 failed before historical
traversal: the preflight retry of a previously broken media item closed Chrome.
The engine has since been changed to **prioritize history**, reopen Chrome up to
three times after unexpected closure, and preserve state between attempts.
These changes still require a second live run for validation.

This is a new downloader path and must be validated on real authenticated
Google Photos pages. Unit tests cannot prove UI navigation works.
If Google Photos changes its navigation or download shortcut, the workflow
reports `NAVIGATION_STALLED` or an error rather than falsely claiming all
history has been backed up.

A successful limit-based run will report `PAUSED_LIMIT`; this means the
backfill is **in progress**, not that synchronization is complete. An
unsupported navigation state does not imply the oldest item was reached.

The backfill can use significant GitHub Actions runner minutes. Monitor
repository Actions usage and Koofr storage as throughput rises. Full-library
coverage cannot be asserted until a verified independent inventory is available.

## Prior art

Ideas are based on (not a wholesale import of) the following public projects:

- https://github.com/vikas5914/google-photos-backup — Playwright browser viewer
  traversal and durable `.lastdone` resume.
- https://github.com/jpratt9/gphotos-export — retried original-quality downloads,
  EXIF dates, resumable history, and separate backward traversal.
- https://github.com/perkeep/gphotos-cdp — Chrome DevTools Protocol downloader
  with durable historical media position.

The historical backfill implementation is specific to the existing private
GitHub Actions + Koofr architecture and reuses the original SQLite manifest.
