# Google Photos → Koofr

One-way, resumable Google Photos backup designed for GitHub Actions.

## Design

- Google Photos is the source of truth.
- Daily jobs are **incremental**: download only new media and upload originals to Koofr.
- The runner is disposable. Persistent state belongs on Koofr under `.gphotos-sync/`.
- Authentication uses a persistent Chromium profile created interactively (planned via GitHub Codespaces), never an automated Google password login.
- Every successfully uploaded media item is recorded in a manifest from day one so a future full reconcile can detect deletions safely.
- Deletion is **disabled in V1**. A quarterly reconcile will first be implemented in report-only mode; automatic deletion will require a complete inventory plus a grace period.
- Filename is never the canonical identity of a Google Photos item.

## Planned Koofr layout

```
/Google Photos/
  Photos/
  .gphotos-sync/
    manifest.sqlite
    daily-checkpoint.json
    reconcile-state.json
    auth/profile.enc
    logs/
```

## Delivery stages

1. **POC authentication** — create/refresh Chromium profile in Codespaces; restore it on a fresh GitHub runner.
2. **POC transfer** — download one original Google Photos item and upload it to Koofr.
3. **Daily incremental backup** — bounded runtime, retry/resume, manifest + checkpoint persisted to Koofr.
4. **Quarterly reconcile** — resumable full inventory, report-only.
5. **Safe deletion** — only after repeated/aged missing observations and a successfully completed inventory.

## Safety invariants

- Never delete from Google Photos.
- Never infer deletion from an incomplete scan.
- Never delete from Koofr during daily backup.
- Never mark an item synced before Koofr upload succeeds.
- Never depend on GitHub Actions cache as the only copy of state.
- Never commit browser profiles, cookies, credentials, rclone config, or runtime state.

## Current status

Repository reset from the previous prototype. The old implementation used mock downloads/uploads and assumed an unsupported scanner interface, so it was intentionally removed. V1 starts with authentication and one-file transfer POC before production sync is enabled.
