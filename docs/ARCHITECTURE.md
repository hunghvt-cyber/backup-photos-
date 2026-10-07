# Architecture

## Daily path

Google Photos → authenticated headless browser → temporary local file → rclone → Koofr → manifest/checkpoint.

The daily job only advances forward from its checkpoint. It does not enumerate the historical library to discover deletions.

## Reconcile path

A separate quarterly job performs a resumable full inventory. Each run belongs to a reconcile generation. Missing media may only be evaluated after that generation is explicitly marked COMPLETE.

Initial reconcile is report-only. Future deletion requires a grace period and independent safety thresholds.

## Authentication

Interactive authentication is separated from backup execution:

1. Launch Chromium with a persistent user-data directory in a temporary graphical environment such as Codespaces + noVNC.
2. User completes Google login/2FA.
3. Close Chromium cleanly.
4. Archive and encrypt the profile.
5. Store encrypted profile in Koofr state storage.
6. GitHub Actions restores a worker copy and launches Chromium headlessly.

Worker copies must not concurrently write the same browser profile archive.

## State model

The manifest must eventually retain at least:

- stable Google Photos identity (to be validated during POC)
- filename
- creation timestamp
- media type
- Koofr path
- first_seen
- last_seen
- uploaded_at
- status
- optional size/hash when reliably available

The exact identity field is deliberately not fixed until the selected downloader is validated against current Google Photos.
