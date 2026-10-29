> 29/10 engine: [browser-session bootstrap correction and bounded canary](docs/BACKFILL-ENGINE-BOOTSTRAP-20261029.md). Offline tests pass; authenticated runtime is validated separately.

> 29/10: [backup/report recovery](docs/BACKUP-REPORT-RECOVERY-20261029.md) — canonical repo names, compatible GAS reports and guarded runtime fixes; live validation remains separate.

> Backfill progress 22/10: [nhánh báo cáo riêng cho Homepage](docs/BACKFILL-PROGRESS-20261022.md). Daily vẫn qua GAS; Backfill chỉ xuất aggregate sau khi chốt lượt, không gửi giả Daily.

> 22/10: [video gốc và nhận diện nội dung](docs/VIDEO-ORIGINAL-IDENTITY-20261022.md). Ba MP4 nhỏ thực chất là WebP preview; không đổi tên thành ảnh. Bản sửa lấy đúng Download và xác minh trước khi lưu thành công.

> Cập nhật 21/10: [download verification và Daily scan](docs/DOWNLOAD-VERIFICATION-20261021.md). Không dùng bootstrap_complete để kết luận đủ thư viện.

> Current state: [20 October upgrade handoff](docs/UPGRADE-20261020.md) and [AI_CONTEXT.md](AI_CONTEXT.md).

# Google Photos → Koofr

One-way, resumable backup of an existing Google Photos library to Koofr, designed for unattended GitHub Actions.

> Continuing development with another AI? Read [`AI_CONTEXT.md`](AI_CONTEXT.md) first. It contains the current production state, safety invariants, incident history, proven fixes, schedules, and development protocol.

## Status

Latest reviewed snapshot: [weekly read-only review, 25 October](docs/WEEKLY-REVIEW-20261025.md). It separates successful new runs from pending errors and unverified original recovery.

The foundation and production path have been proven on fresh GitHub-hosted runners:

- restore an AES-256/PBKDF2 encrypted Chrome profile from Koofr;
- open the authenticated Google Photos library headlessly;
- enumerate opaque Google Photos media IDs;
- trigger Google's official Download action;
- save the exact browser Download for Daily, or use the reviewed metadata/signed-original route for Backfill with source-size validation;
- compute SHA-256, upload through rclone/WebDAV, and verify remote byte size;
- persist SQLite manifest and JSON checkpoint back to Koofr.

The early 2026-10-08 bootstrap saw only 21 media; its `bootstrap_complete=true` was not evidence of full library coverage. The current worker inventories Photos, Archive and albums. The completed retry trial on 2026-10-20 uploaded 10/10 formerly failed items; its snapshot recorded 12,713 inventoried media, 254 uploaded in the manifest, and 49 albums. Full library coverage remains unverified.

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

**Historical Backfill** — `.github/workflows/backfill.yml`

Runs **every day at 04:45 Vietnam time**, with a five-hour engine budget, 305-minute external watchdog and 330-minute job cap. It uses `src/gphotos_web_backup.py` to paginate Photos, Archive and albums, resume durable cursors and upload pending originals to Koofr. Album membership is stored in the private SQLite manifest without duplicating media into album folders. See the [current handoff](docs/UPGRADE-20261020.md).

**Quarterly reconcile** — `.github/workflows/reconcile.yml`

Runs at **19:41 UTC on day 1** of January, April, July and October, which is **02:41 Vietnam time on day 2**. The simple UTC schedule is intentional for maintainability. It inventories Google Photos into a reconcile generation and writes a report. V1 never deletes.

All three Photos workflows share a concurrency group so they cannot mutate Koofr's persistent manifest and encrypted Chrome profile simultaneously.

**Public runner policy:** Photos uses standard hosted Ubuntu runners in a public repository. The older shared private-repository minute-budget projection is historical. Six hours is a per-job hosted-runner limit; the shorter configured budgets preserve time for state and profile saving. This upgrade does not change Drive workflows.

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
- Configured engine budgets and watchdogs stop before job hard limits so state can be flushed.

## State recovery

The runner is disposable. Each run restores `manifest.sqlite` and checkpoints from Koofr. SQLite runs in WAL mode locally, so production creates a consistent snapshot with SQLite's Backup API before uploading the remote manifest. Daily persists immediately. Web Backfill checkpoints each inventory page, each ten attempted media and at the end; a hard interruption may require rechecking a recent batch. If a run is interrupted, already committed items are skipped on the next run.

If manifest state is missing but a candidate Koofr object already exists, production compares size and SHA-256 and can reconstruct the manifest instead of creating a duplicate.

## Báo cáo Homepage qua GAS/Drive

Chỉ xuất aggregate đã lọc; không coi publish thành công là backup media thành công.

- Source workflow mặc định `REPORT_BACKEND=gas-drive`; dùng variable
  `REPORT_GAS_URL` và secret `REPORT_GAS_KEY`. Nhánh Blob chỉ còn lựa chọn legacy
  rõ ràng, không phải mặc định hoặc fallback của Homepage.
- Hai feed đã phục hồi HTTP 200 ngày 20/10; đây là bằng chứng có thời điểm,
  chưa phải phép đo mới ngày 22/10. Xem [hồ sơ vận hành](docs/REPORTS-GAS.md).
- Không sửa engine, filter, state, lịch, reset/resync hoặc media để sửa báo cáo.

Nguồn tích hợp/API: [Homepage OPERATIONS](https://github.com/hunghvt-cyber/Homepage-nas/blob/main/docs/OPERATIONS.md).
Bản đồ tổng thể: [NAS AIO](https://github.com/hunghvt-cyber/0219nas-aio).
