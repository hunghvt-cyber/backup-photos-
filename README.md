# Google Photos → Koofr

One-way, resumable backup of an existing Google Photos library to Koofr, designed for unattended GitHub Actions.

> Continuing development with another AI? Read [`AI_CONTEXT.md`](AI_CONTEXT.md) first. It contains the current production state, safety invariants, incident history, proven fixes, schedules, and development protocol.

## Status

The foundation and production path have been proven on fresh GitHub-hosted runners:

- restore an AES-256/PBKDF2 encrypted Chrome profile from Koofr;
- open the authenticated Google Photos library headlessly;
- enumerate opaque Google Photos media IDs;
- trigger Google's official Download action;
- replay the authenticated download request and obtain the real file;
- compute SHA-256, upload through rclone/WebDAV, and verify remote byte size;
- persist SQLite manifest and JSON checkpoint back to Koofr.

Initial historical bootstrap completed successfully on 2026-10-08. The bootstrap run discovered 21 media, uploaded 16 new items, skipped 5 already committed items, and finished with 0 errors and `bootstrap_complete=true`.

POC media was removed after validation. Production media is stored separately under `Google Photos/Photos/`.

## Koofr layout

```text
/Google Photos/
  Photos/
    YYYY/
      MM/
        original-file.ext
  .gphotos-sync/
    auth/profile.tar.gz.enc
    manifest.sqlite
    daily-checkpoint.json
    reconcile-state.json
    logs/
```

## Workflows

**Daily backup** — `.github/workflows/daily.yml`

Runs at 03:17 Vietnam time and can be started manually. During initial bootstrap it walks newest → oldest across repeated bounded runs. Once bootstrap is complete, later runs stop at the prior newest checkpoint.

**Quarterly reconcile** — `.github/workflows/reconcile.yml`

Runs at **19:41 UTC on day 1** of January, April, July and October, which is **02:41 Vietnam time on day 2**. The simple UTC schedule is intentional for maintainability. It inventories Google Photos into a reconcile generation and writes a report. V1 never deletes.

Both workflows use the same concurrency group so they cannot mutate persistent state simultaneously.

## Required GitHub Secrets

- `KOOFR_USER`
- `KOOFR_APP_PASSWORD`
- `GPHOTOS_PROFILE_KEY`

The profile encryption key must match `.gphotos-sync/auth/profile.tar.gz.enc`.

## Safety invariants

- Google Photos is the source of truth.
- No code path deletes from Google Photos.
- Daily backup never deletes from Koofr.
- Reconcile V1 is report-only; deletion is not implemented.
- Media identity is the opaque ID from `/photo/<id>` or `/video/<id>`, never filename.
- An item becomes `uploaded` only after Koofr upload succeeds and remote size matches local size.
- Duplicate filenames never overwrite an existing Koofr object; a short media-ID suffix is used.
- Durable state lives on Koofr, not GitHub Actions cache.
- Browser profiles, cookies, passwords and rclone config are never committed.
- Jobs stop before the 5-hour runner limit so state can be flushed.

## State recovery

The runner is disposable. Each run restores `manifest.sqlite` and checkpoints from Koofr. SQLite runs in WAL mode locally, so production creates a consistent snapshot with SQLite's Backup API before uploading the remote manifest. State is flushed after every successful upload and again during final cleanup. If a run is interrupted, already committed items are skipped on the next run.

If manifest state is missing but a candidate Koofr object already exists, production compares size and SHA-256 and can reconstruct the manifest instead of creating a duplicate.

## Homepage backup report (Vercel Blob)

After each daily run, the workflow generates a **sanitized public JSON report** from its existing local log/health artifact and publishes it to a dedicated public Vercel Blob store. Publication is best-effort and does not change the backup result. Configure the repository Actions secret `BLOB_READ_WRITE_TOKEN` for that store; no GitHub cross-repository token is needed. If the secret is missing, the step skips with a notice. Never publish raw logs, file names, or credentials.

Source of truth for schema, URL configuration, setup, troubleshooting and AI handover: [Homepage-nas/docs/BACKUP-REPORTING.md](https://github.com/hunghvt-cyber/Homepage-nas/blob/main/docs/BACKUP-REPORTING.md).
