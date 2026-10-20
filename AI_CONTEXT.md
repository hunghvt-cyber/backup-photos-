## Trạng thái hiện hành — 20/10/2026

**Đọc [bàn giao nâng cấp 20/10/2026](docs/UPGRADE-20261020.md) trước.** Đây là nguồn hiện hành cho lịch public-runner, Photos/Archive/album, kết quả thử và việc cần kiểm tra tiếp. Các phần phía dưới lưu lịch sử, có thể có lịch và ngân sách đã hết hiệu lực.

- Daily 03:17 ICT: engine 25 phút / job 40 phút.
- Backfill **04:45 ICT mỗi ngày**: engine 5 giờ / job 330 phút; chỉ schedule/manual.
- Worker hiện hành: `src/gphotos_web_backup.py`; giữ manifest và Daily checkpoint, quét luân phiên Photos/Archive/album.
- 29 tests pass. Lượt retry [39386517817](https://github.com/hunghvt-cyber/google-photos-koofr/actions/runs/39386517817) SUCCESS: 10/10 uploaded, 0 lỗi trong lượt.
- Snapshot sau lượt retry: **12.713 mục đã kiểm kê, 254 uploaded trong manifest, 12.456 pending_seen, 4 pending_errors, 49 album, 2.240 quan hệ album–ảnh**; inventory_complete=false.
- Lượt dài [39386977931](https://github.com/hunghvt-cyber/google-photos-koofr/actions/runs/39386977931) đang chạy tại thời điểm cập nhật; cần đọc kết quả cuối lượt trước khi đánh giá tốc độ hoặc tiến độ mới.
- Chưa chứng minh backup đầy đủ hoặc duyệt xong nội dung tất cả album. Không dùng bootstrap_complete cũ hoặc một job xanh để kết luận đã đủ.
- Homepage publishing Daily giữ nguyên; Backfill báo cáo qua Actions Summary/artifact.

# AI HANDOVER / PROJECT CONTEXT

> Read this file first when continuing development with another AI or in a new conversation.
> Repository: `hunghvt-cyber/google-photos-koofr`
> Last updated: 2026-10-20
> Production status: upgrade deployed; full-budget run under verification

## 2026-10-15 active free-tier scheduling and safe-shutdown policy

**HISTORICAL POLICY (superseded 2026-10-20):** [docs/FREE_TIER_BUDGET.md](docs/FREE_TIER_BUDGET.md).
This section supersedes all older "Daily Backfill at 04:45" and
"35-minute historical Backfill" statements in archived incident history.

User directive: keep the two private repos inside GitHub Free's monthly
minute allocation, prioritize completed checkpoints/logs over using the
entire 6-hour job limit. Google Photos is the only media source; no
Google Takeout, no mobile photo upload and no persistent Codespaces.

Active automatic schedule (Asia/Ho_Chi_Minh):

| Project/workflow | ICT schedule | Job hard cap | Internal process budget |
|---|---|---:|---|
| `my-backup-gdrive-koofr/.github/workflows/bisync.yml` | 02:00 EVERY day | 35 min | 29 min Rclone + max 2 min interrupt grace |
| `google-photos-koofr/.github/workflows/daily.yml` | 03:17 EVERY day | 9 min | Python 300s and watchdog 240s (+30s kill grace) |
| `google-photos-koofr/.github/workflows/backfill.yml` | 04:45 Mon/Wed/Fri/Sun | 20 min | Python 720s and watchdog 660s (+30s kill grace) |
| `google-photos-koofr/.github/workflows/reconcile.yml` | 02:41 Jan/Apr/Jul/Oct 2nd | 60 min | Python 2400s and watchdog 2700s (+30s kill grace) |

The early termination limits leave the runner time to persist Koofr
manifest/checkpoints, rclone bisync state/caches, encrypted Chrome
profile, GitHub artifact and reports. Shell timeout exits may mark a run
failed; `if: always()` performs cleanup/persistence where possible.
There is NO guarantee if GitHub kills the runner itself. Backfill remains
manual-dispatchable any day; its automatic schedule is four days weekly
for better per-minute effectiveness, while **new Photos Daily stays daily**.

Worst-case planned monthly consumption for a 31-day month including
a quarterly reconcile: 31×35 + 31×9 + 18×20 + 60 = **1,784 min**.
This assumes GitHub Free private standard Linux runner allowance 2,000
min/billing month. **216 min is only a planning buffer**, not actual
remaining billing quota: other repositories, manual runs, reruns, and
GitHub billing-cycle boundaries can consume it. User should check
https://github.com/settings/billing and set a no-overage spending cap /
appropriate budget alerts for a hard monetary guardrail.

Manual rescue: Drive `workflow_dispatch` now offers
`extended_budget=true`, restoring a 330-minute maximum job and
300-minute rclone budget, **only** when deliberately selected manually.
It can exceed remaining free minutes; `resync/reset` should not be used
without checking state and quota first. Daily Drive default remains
35 minutes and uses recovered cache on timeout; a timed-out resync is
NOT a completed two-way sync.

Time caps are deployed but need confirmation from the next scheduled
Actions runs. Do not revert these for throughput without a
free-minutes calculation and explicit user approval. Observed benchmarks:
Drive Bisync 28.3min full job in run 38520318431; Photos Daily 3.6min
in run 38510416865; historical Backfill 22.8min and 44 successful
uploads in run 38658212741 (before new limits).

## 1. Goal

Build and maintain an unattended, one-way Google Photos → Koofr backup system that can be operated from a phone/iPad through GitHub Actions.

Google Photos is always the source of truth. Koofr is the backup destination and durable state store.

Normal operation must not require a PC, Codespaces, or an always-on server.

## 2026-10-15 verified Backfill breakthrough and speed improvement

Run 38658212741 on 2026-10-15 (ICT):
https://github.com/hunghvt-cyber/google-photos-koofr/actions/runs/38658212741
**Success/PAUSED_TIME, partial media errors:** discovered=276 in 21.7s,
attempted=50, uploaded=44, errors=6, runtime download_seconds=888.44,
uploaded_per_hour=178.29, cumulative manifest uploaded=161,
pending_seen=102, pending_errors=13. Gallery scrolling is now working
to at least 276 distinct IDs, so the primary bottleneck is per-media
download and Koofr state flush, not enumeration.
The max_items=100 setting is an attempt ceiling, not guaranteed throughput.

Speed changes committed after the run:
- `Engine.one` now accepts optional `flush_state=True` (default).
  Daily is unchanged and still persists state immediately.
- Grid Backfill calls `Engine.one(..., update_checkpoint=False,
  flush_state=False)` and persists state via `GridBackfill.persist`
  once each 10 attempted media and at the end. Avoids redundant
  manifest+daily-checkpoint WebDAV uploads per individual image.
- A mid-batch crash may lose recent manifest checkpoint entries, but
  uploaded remote files remain; next run verifies size and SHA before
  reusing, so no remote media are destroyed.
- Browser download request replay now excludes cached conditional HTTP
  headers, mitigating `HTTP 304 Not Modified`.
- Both Daily and Backfill workflows exclude disposable Chrome caches from
  the encrypted refreshed profile archive; authentication databases
  and web storage are preserved. Logs include `PROFILE_ARCHIVE_BYTES`
  and `PROFILE_PERSIST_SECONDS`.
- Backfill Actions Summary now explicitly reports partial failures.

**Not yet tested with a live workflow after these performance changes.**
Offline tests for batch persistence were added to
`tests/test_gphotos_backfill_grid.py`, and will run in the next workflow.
Do not claim 100 uploads/day until next run proves it.
Time budgets remain Backfill 35-minute job / 20-minute engine /
3-minute scanner. Daily remains at 03:17 ICT and Backfill 04:45 ICT.
Drive-Koofr bisync also runs daily and may consume shared GitHub
Actions free minutes; latest checked run 38520318431 lasted ~28 min.
See `docs/BACKFILL.md` for details.

## 2026-10-14 budget-constrained unattended daily backfill

User decision: progress gradually day-by-day **within free allocations**,
prioritizing useful backups over long idle/broken runs. Avoid a permanent
Codespace or a paid VPS. Google Photos cloud remains the only media source;
no Takeout or device camera upload.

Active `.github/workflows/backfill.yml` continues daily at 04:45 ICT,
but now caps the whole job at **35 minutes**, the engine at **20 minutes**
(`MAX_RUNTIME_SECONDS=1200`) and the virtual gallery scan at **3 minutes**
(`MAX_SCAN_SECONDS=180`). `max_items=100` is an upper bound only, not
a promise that 100 items are discovered or uploaded.

`src/gphotos_backfill_grid.py` reports `scan_seconds`,
`download_seconds`, `uploaded_per_hour`, and cumulative
`manifest_uploaded_total`. The scanner fails on repeated stagnation;
a zero-progress scan-budget run cannot falsely report success.
Known perma-failed HTTP403 media are excluded from the backfill queue,
but remain recorded as `error` for a future separate repair routine.
Safety: no deletion, same Koofr manifest, no changes to the Daily cursor.

**Do not promise zero cost solely from job caps.** GitHub Free's included
Actions allowance is **2,000 min/month shared by the account's private
repositories** (other Drive/Koofr workflows consume minutes). The user
must inspect https://github.com/settings/billing and enable included
usage alerts or enforce appropriate billing settings. GitHub Codespaces
has a separate 120 core-hour monthly free quota but is not an unattended
daily scheduler. This latest time-budget change has **not yet been
verified by a live workflow run**. Wait for a new backfill run to inspect
`GRID_SCAN` / `BACKFILL_SUMMARY` before increasing quotas.
More details: `docs/BACKFILL.md`.

## State restoration safety improvement (2026-10-14)

`Engine.restore` now stops immediately if Koofr `manifest.sqlite` or
`daily-checkpoint.json` cannot be restored. Previously a transient restore
failure could silently create an empty database and overwrite durable state.
The optional and currently absent `reconcile-state.json` remains non-fatal.

## 2026-10-14 third trial and scrolling fix (unverified)

- Run: https://github.com/hunghvt-cyber/google-photos-koofr/actions/runs/38531203749
- GitHub job SUCCESS but library backfill not successful:
  `discovered=17, attempted=5, uploaded=3, errors=2`,
  `scan_status=SCROLL_END_OR_STALLED` after 6 rounds, total manifest uploaded=96.
  Two previously broken media failed with HTTP 403 / Chrome closure.
- Updated `src/gphotos_backfill_grid.py` to scan beyond already backed-up
  media, combining last-tile scroll-into-view, ancestor/container scroll,
  native wheel and PageDown. Logs `GRID_SCROLL_DIAG` with DOM scroll metrics.
  A 15-round stagnant scanner is now a FAILURE rather than green status.
- Old hard-error media are not retried during routine historical backfill,
  remaining safely in manifest for a separate repair queue.
- Added regression tests for navigation past previously uploaded media.
- Updated documentation at `docs/BACKFILL.md`.
- Next manual test should use max_items=10, inspect `GRID_SCAN` counts.
  Do NOT raise to 100 until new scanner discovers at least dozens of unique
  historical media in a real run.
- No completed entire-library inventory or speed benchmark yet; 96 is total
  manifest uploaded as at that run, not a claimed total photo library size.

## 2026-10-14 second Backfill trial and V2 Grid Scanner

- Manual run: https://github.com/hunghvt-cyber/google-photos-koofr/actions/runs/38527073559
- Outcome: FAILED. Scanned 3 items, attempted 2, uploaded 0, skipped 1,
  errors 2, `NAVIGATION_LOOP`. Manifest cumulative uploaded=93;
  pending_errors=6; legacy viewer visited_total=35.
- Viewer-path download hit Chrome closure and then Playwright timeout.
  A Chrome restart succeeded but the left/right viewer navigation did not
  traverse historical photos reliably.
- Changed production `.github/workflows/backfill.yml` to invoke
  `src/gphotos_backfill_grid.py` (new two-phase design):
  1. single persistent Chrome browser scans virtualized gallery via scroll,
     records all discovered media IDs in SQLite, logs visible/count/movement;
  2. closes the scanner browser, then uses existing proven `Engine.one()`
     downloader for up to 100 attempted images by default, with isolated
     Chrome per item and Koofr verification.
- `Engine.one(...,update_checkpoint=False)` preserves the Daily state cursor
  during historical backfill. Both phases share manifest and concurrency key.
- Writes `backfill-grid-checkpoint.json` on Koofr, manifest committed first.
  Previous `backfill-checkpoint.json` from viewer engine preserved as
  legacy/rollback. No deletion of Photos/Koofr data.
- New offline tests in `tests/test_gphotos_backfill_grid.py`.
- **V2 not yet live-tested**; next manual workflow test with max_items=10
  should check `GRID_SCAN`, `GRID_QUEUE`, `BACKFILL_SUMMARY`. Do NOT
  assume 100+ throughput until verified. If scan shows no scroll movement
  and only 10-20 visible items, fix scrolling before raising the quota.
- Docs: `docs/BACKFILL.md`.

## 2026-10-14 first historical backfill trial and fix

- Manual run: https://github.com/hunghvt-cyber/google-photos-koofr/actions/runs/38523118388
- Result: failure; 5 offline tests passed, authentication restored, no
  historical items reached. The engine retried a previously problematic media
  item FIRST; `Download.save_as` closed Chrome. It then attempted to reuse
  the dead browser for opening the gallery and crashed with `TargetClosedError`.
- Fix: Backfill now traverses **historical media first** (no broken-media
  preflight retry), restarts a closed Chrome context up to 3 times, and
  checkpoints the already processed manifest and viewer position BEFORE
  restarting. Exhausted retries fail with a structured status.
- New restart test was added. **Not yet verified in a subsequent live run.**
- Previously failed IDs remain in the existing manifest retry queue and should
  be handled by a separate failure-retry phase in future development; avoid
  blocking the main historical backfill on those IDs.

## 2026-10-14 historical backfill development (not yet live-tested)

The October 14 Daily run `38510416865` discovered 13, skipped 12 and
uploaded 1; this is NOT evidence of completed library-wide coverage.
Several thousand historical photos are still expected.

New independent backfill was implemented on main:
- `src/gphotos_backfill.py` — persistent Chrome gallery-viewer traversal,
  native Shift+D browser download events, EXIF/filename date fallback,
  per-media retry, SHA-256 collision avoidance, Koofr size verification.
- `.github/workflows/backfill.yml` — 04:45 ICT daily, 100 attempted
  downloads per default run, 4-hour GitHub cap and 200-minute engine budget.
- `tests/test_gphotos_backfill.py` — offline helper/navigation tests, run
  by backfill workflow before loading authentication.
- `docs/BACKFILL.md` — operations and caveats.

Backfill uses existing `manifest.sqlite` and a separate
`backfill-checkpoint.json` in Koofr. The checkpoint is written AFTER
the manifest; the script never deletes backups or changes the Daily cursor.
All three scheduled workflows share concurrency key
`google-photos-koofr-state`.

**Validation warning:** This implementation has not yet been exercised
against the authenticated account after deployment. In particular, verify
that Google Photos viewer ArrowRight advances toward older media. If
navigation stops, the status is `NAVIGATION_STALLED` (failure), NOT
completed. Start with 100 before trying manual max_items=300.
The status `bootstrap_complete` in Daily is not a full-inventory proof.
The Vercel homepage currently displays Daily results, not historical backfill
cumulative statistics.

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

## Homepage backup reporting (2026-10-14)

Daily workflow additionally converts its existing daily-health.json into a sanitized schema v1 report and publishes gphotos-backup-latest.json to a dedicated public Vercel Blob store. Requires optional GitHub Actions secret BLOB_READ_WRITE_TOKEN. Publishing is best-effort; never changes backup success, manifest/checkpoint or Koofr state. Central contract and troubleshooting: https://github.com/hunghvt-cyber/Homepage-nas/blob/main/docs/BACKUP-REPORTING.md . No repository_dispatch or cross-repo GitHub token.
