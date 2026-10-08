# Architecture

## Data path

Google Photos web UI → authenticated persistent Chrome profile → Playwright → official Download action → captured authenticated Google download request → temporary runner file → SHA-256 → rclone/WebDAV → Koofr → SQLite manifest/checkpoint.

The GitHub runner is disposable. Durable media and state live on Koofr.

## Identity and destination

V1 uses the opaque identifier exposed by current Google Photos media URLs such as `/photo/AF1Qip...` as the SQLite primary key. Filename is metadata only.

Destination layout is `Google Photos/Photos/YYYY/MM/<filename>`. If that path already exists, V1 appends a short media-ID suffix instead of overwriting.

## Daily state machine

1. Restore encrypted browser profile and state from Koofr.
2. Enumerate Google Photos newest-first.
3. Upsert discovery metadata by media ID.
4. Skip IDs already marked `uploaded`.
5. Trigger Google's Download action and capture the authenticated file request.
6. Download to runner, compute SHA-256, upload to Koofr.
7. Verify Koofr byte size equals local byte size.
8. Only then mark the item `uploaded`.
9. Flush SQLite/checkpoint to Koofr after each successful item.
10. Stop before the GitHub Actions five-hour limit.

Initial bootstrap may revisit the newest prefix on later runs. The manifest makes this idempotent. After the historical end is reached, `bootstrap_complete` allows daily jobs to stop at the previous newest checkpoint.

## Quarterly reconcile

A reconcile generation records `(generation, media_id)` observations. The scanner is bounded and can continue the same generation on later runs. Missing counts are report-only.

There is intentionally no deletion function in V1. Any future deletion feature requires multiple proven complete generations, a grace period and explicit safety thresholds.

## Authentication

Interactive login is only required to create or refresh the profile. The closed Chrome profile is archived and encrypted with AES-256-CBC + PBKDF2. The encrypted archive is stored on Koofr while its key is stored separately as a GitHub Actions secret.

Fresh-runner portability has been proven in production-like POC runs.

## Failure model

- **Download/upload error:** manifest records the error and retries the item on a later run.
- **Runner interruption:** previously flushed items remain durable; unfinished items are retried.
- **Duplicate filename:** no overwrite; media-ID suffix is used.
- **Expired Google session:** scanner fails closed when authenticated media is not visible.
- **Concurrent daily/reconcile:** prevented by one shared Actions concurrency group.
- **Missing remote state on first bootstrap:** a new manifest/checkpoint is created; existing remote state is restored when present.
