# Google Photos → Koofr

One-way, resumable backup of an existing Google Photos library to Koofr, designed for unattended GitHub Actions.

## Status

The foundation and production path have been proven on fresh GitHub-hosted runners:

- restore an AES-256/PBKDF2 encrypted Chrome profile from Koofr;
- open the authenticated Google Photos library headlessly;
- enumerate opaque Google Photos media IDs;
- trigger Google's official Download action;
- replay the authenticated download request and obtain the real file;
- compute SHA-256, upload through rclone/WebDAV, and verify remote byte size;
- persist SQLite manifest and JSON checkpoint back to Koofr.

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

Runs at 02:41 Vietnam time on the first day of January, April, July and October. It inventories Google Photos into a reconcile generation and writes a report. V1 never deletes.

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

The runner is disposable. Each run restores `manifest.sqlite` and checkpoints from Koofr. State is flushed after every successful upload and again during final cleanup. If a run is interrupted, already committed items are skipped on the next run.
