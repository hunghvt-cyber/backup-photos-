# AI HANDOVER / PROJECT CONTEXT

> Read this file first when continuing development with another AI or in a new conversation.
> Repository: `hunghvt-cyber/google-photos-koofr`
> Last updated: 2026-10-08
> Production status: operational

## 1. Goal

Build and maintain an unattended, one-way Google Photos → Koofr backup system that can be operated from a phone/iPad through GitHub Actions.

Google Photos is always the source of truth. Koofr is the backup destination and durable state store.

Normal operation must not require a PC, Codespaces, or an always-on server.

## 2. Current production status

The difficult end-to-end path has been proven on fresh GitHub-hosted runners:

1. restore an encrypted Chrome profile from Koofr;
2. open the authenticated Google Photos library headlessly;
3. enumerate media using opaque IDs exposed in `/photo/<id>` and `/video/<id>` URLs;
4. invoke Google Photos' official Download action;
5. capture/replay the authenticated `usercontent.google.com` request;
6. download the real media file;
7. compute SHA-256;
8. upload with rclone/WebDAV to Koofr;
9. verify Koofr byte size;
10. commit SQLite manifest/checkpoint back to Koofr;
11. encrypt and persist the refreshed Chrome profile for future fresh runners.

Initial historical bootstrap completed successfully on 2026-10-08.

Bootstrap run `37761542787` summary:

```text
discovered=21
attempted=16
uploaded=16
skipped=5
errors=0
bootstrap_complete=true
```

Before the final bootstrap, durable-state verification showed exact manifest/file parity and zero stale errors. The bootstrap then continued from that verified state and completed without errors.

POC/test directories were purged. Files now under `Google Photos/Photos/` are production backup data and must not be casually deleted.

## 3. Production schedules

GitHub Actions cron expressions are UTC.

### Daily backup

Workflow: `.github/workflows/daily.yml`

```text
cron: 17 20 * * *
UTC: 20:17
Asia/Ho_Chi_Minh: 03:17 next day
```

Runs every day. It can also be started manually with `workflow_dispatch` and an optional `max_items`.

### Quarterly reconcile

Workflow: `.github/workflows/reconcile.yml`

```text
cron: 41 19 1 1,4,7,10 *
UTC: 19:41 on day 1 of Jan/Apr/Jul/Oct
Asia/Ho_Chi_Minh: 02:41 on day 2 of Jan/Apr/Jul/Oct
```

This deliberate UTC-simple schedule is preferred over complicated timezone/date tricks. Reconcile is not time-critical.

Both workflows use concurrency group `google-photos-koofr-state` with `cancel-in-progress: false`, so daily and reconcile cannot mutate state concurrently.

Runner is pinned to `ubuntu-24.04`. Do not casually switch back to `ubuntu-latest`.

## 4. Repository map

```text
.github/workflows/
  daily.yml              daily incremental backup
  reconcile.yml          quarterly report-only inventory/reconcile

src/
  __init__.py
  gphotos_sync.py        production scanner/downloader/state/uploader engine

docs/
  ARCHITECTURE.md
  OPERATIONS.md

README.md
AI_CONTEXT.md            this handover file
requirements.txt
.gitignore
```

Temporary POC/inspection/validation workflows were intentionally removed after use.

## 5. Koofr layout

```text
/Google Photos/
  Photos/
    YYYY/
      MM/
        original-file.ext
        original-file__<short-media-id>.ext   # only for filename collision
  .gphotos-sync/
    auth/
      profile.tar.gz.enc
    manifest.sqlite
    daily-checkpoint.json
    reconcile-state.json
    logs/
      reconcile-report-*.json
```

Durable state belongs on Koofr, not in GitHub Actions cache.

## 6. Required GitHub Actions secrets

- `KOOFR_USER`
- `KOOFR_APP_PASSWORD`
- `GPHOTOS_PROFILE_KEY`

Never print, commit, paste into documentation, or request these values in chat.

Koofr WebDAV uses an app-specific password.

The Chrome profile archive uses:

```text
AES-256-CBC
PBKDF2
iterations=200000
```

The encryption key in `GPHOTOS_PROFILE_KEY` must match the encrypted profile stored on Koofr.

## 7. Core safety invariants

These are requirements, not suggestions:

1. Never delete anything from Google Photos.
2. Daily backup never deletes from Koofr.
3. Reconcile V1 is report-only. There is intentionally no deletion implementation.
4. Never treat filename as canonical identity.
5. Media identity is the opaque Google Photos media ID from the media URL.
6. Never mark an item `uploaded` until upload succeeds and remote byte size matches.
7. Never overwrite an unrelated existing file merely because filenames collide.
8. Never commit browser profiles, cookies, passwords, rclone config, or encryption keys.
9. Preserve the shared workflow concurrency lock.
10. Preserve graceful runtime headroom before GitHub's five-hour job timeout.

If future deletion/pruning is ever designed, require multiple complete reconcile generations, a grace period, explicit thresholds, dry-run/reporting, and a separate opt-in design review first.

## 8. Important implementation details

### Google Photos enumeration

The standard Google Photos API/rclone route cannot enumerate the user's complete pre-existing library under the post-2025 restrictions used by this project. Production therefore uses browser automation.

The current UI exposes opaque media identifiers in URLs such as:

`https://photos.google.com/photo/AF1Qip...`

The opaque ID is used as the SQLite primary key.

### Download

The reliable production method is:

- open the media in authenticated Chrome;
- trigger Shift+D / Google's official Download action;
- capture the exact authenticated request to `usercontent.google.com`;
- remove HTTP/2 pseudo-headers when replaying outside Chrome;
- replay the request to a temporary runner file.

Do not assume that generic cookies alone are sufficient; that previously returned HTTP 403.

### Browser lifecycle

Each media download uses its own Chrome persistent context.

This is intentional. Google/Chrome may close the context after a download. A previous design reused one context for a whole batch and produced `Target page/context/browser has been closed` failures.

The scanner and media downloads must remain isolated from each other unless a replacement design is proven by multi-item canaries.

### SQLite durability

SQLite uses WAL locally, but **never upload the live `manifest.sqlite` file directly while the connection is open**.

A previous implementation did that and Koofr received a stale main database while newer transactions remained in WAL. This caused manifest loss and a duplicate upload.

Production uses Python's SQLite Backup API to create a consistent snapshot, then uploads that snapshot as remote `manifest.sqlite`.

Preserve this behavior.

### Self-healing/idempotency

If manifest state is missing but the expected Koofr filename already exists:

1. compare size;
2. download the remote candidate to a temporary file;
3. compare SHA-256 with the freshly downloaded Google Photos item;
4. if hashes match, reuse the existing Koofr object and reconstruct manifest state;
5. if not, use a filename with a short media-ID suffix.

This behavior was tested after the WAL incident. It prevented re-uploading identical existing files.

### State flushing

After a successful item:

- update SQLite;
- create a consistent SQLite snapshot;
- upload remote manifest;
- update/upload daily checkpoint.

A final flush is also attempted on exit.

### Session longevity

After jobs, the worker Chrome profile is re-archived, encrypted, and uploaded over `.gphotos-sync/auth/profile.tar.gz.enc`.

This allows normal Google session refreshes to survive fresh runners. Manual intervention should only be needed if Google explicitly requires login/2FA again.

## 9. Daily behavior

Historical bootstrap is complete.

Normal daily behavior should therefore:

- enumerate newest-first;
- compare against the stored newest checkpoint;
- process genuinely new media;
- skip media already marked uploaded;
- stop at the previous boundary;
- checkpoint durable state;
- exit red if any media errors occurred, after safely saving state.

The runner is disposable.

## 10. Quarterly reconcile behavior

Reconcile creates a generation and records observed `(generation, media_id)` pairs.

It is resumable by media boundary and periodically checkpoints long scans.

It reports missing counts only.

`deletion_enabled` must remain false in V1.

## 11. Production incidents already found and fixed

Do not rediscover these by reverting the fixes:

### A. Playwright `download.save_as()` failure

The temporary Playwright download file could disappear when the browser context closed.

Fix: capture/replay the authenticated download request instead.

### B. Direct download URL + generic cookies returned HTTP 403

Fix: capture the exact Chrome request headers. Filter HTTP/2 pseudo-headers such as `:authority` before replay.

### C. Live SQLite/WAL upload lost committed state

Symptom: checkpoint advanced but remote manifest contained fewer rows, causing a duplicate.

Fix: SQLite Backup API snapshot before rclone upload.

### D. One browser context for multiple downloads was unstable

Symptom: `Target page, context or browser has been closed`.

Fix: isolated Chrome context per media download.

### E. One duplicate created during WAL canary

Two same-size files existed for one item. SHA-256 was verified identical before deleting the suffixed duplicate. Production state was then cleaned and verified.

### F. GitHub hosted runner apt installation can stall

Workflows now pin Ubuntu 24.04 and bound runtime installation to 15 minutes with retries.

## 12. Verified production checkpoints

Important historical runs:

- Fresh-runner auth POC: `37745665602` — success.
- Fresh-runner real transfer POC: later POC runs — success.
- Multi-item canary: `37756682695` — success; exposed WAL durability issue during follow-up inspection.
- Isolated-context recovery canary: `37760560578` — success.
- Final pre-bootstrap durable verification: manifest/file parity, zero errors.
- Initial production bootstrap: `37761542787` — success, 21 discovered, 16 uploaded, 5 skipped, 0 errors, `bootstrap_complete=true`.

Do not treat old POC failures as current production failures; they were part of the engineering process above.

## 13. Phone/iPad operating model

The owner expects normal maintenance to be possible without a PC.

An AI with GitHub connector access can normally:

- inspect repository code;
- create/update/delete repository files;
- inspect Actions runs/jobs/logs;
- commit fixes;
- indirectly trigger a temporary push-based canary when necessary, then remove that trigger.

Known limitation: the available GitHub connector does not provide direct workflow-dispatch or Actions-secret management in this setup.

Do not ask the owner to paste logs that the connector can read directly.

Manual user action is mainly for:

- updating GitHub Secrets;
- Google interactive login/2FA if the session expires;
- rare GitHub UI actions unavailable through the connector.

## 14. Development protocol for future features

Before changing production behavior:

1. read this file, README, architecture, operations, workflows, and relevant source;
2. preserve all safety invariants;
3. make the smallest coherent change;
4. syntax/test it;
5. use a bounded canary for behavior that touches Google Photos or Koofr;
6. inspect logs yourself;
7. verify manifest/file parity when state logic changes;
8. remove temporary canary/inspection workflows and push triggers;
9. update this handover if architecture or operations changed.

Do not leave debug workflows or temporary push triggers in production.

## 15. Good next feature areas

Develop these in separate conversations/branches of work where practical:

- better operational summaries/notifications after Actions runs;
- health/status dashboard or compact backup report;
- richer metadata/date extraction and validation;
- explicit video-heavy canaries;
- stronger original-quality validation against known source originals;
- reconcile reporting UX;
- automated session-expiry alerting;
- tests/refactoring of the currently compact `gphotos_sync.py`;
- optional retention/pruning design only after long-term reconcile evidence, never as an implicit change.

## 16. Definition of healthy production

A healthy daily system means:

- workflow succeeds;
- no `UPLOAD_ERROR`;
- manifest remains durable;
- no duplicate remote objects for the same media ID;
- refreshed encrypted profile persists;
- checkpoint advances only with verified state;
- no unexpected deletion occurs.

When debugging, protect correctness and recoverability before optimizing speed.
