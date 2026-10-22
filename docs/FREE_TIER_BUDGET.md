# Lịch và ngân sách Actions — Drive/Photos

Nguồn quản trị chung duy nhất cho hai repo. Đối chiếu workflow main ngày
22/10/2026; cả hai repo public tại lần đọc metadata. Bảng là cấu hình source,
không phải xác nhận scheduler đã chạy đúng giờ hoặc dung lượng backup đầy đủ.

| Job | Cron UTC | Giờ Việt Nam | Giới hạn job / engine |
| --- | --- | --- | --- |
| Drive Bisync | `0 19 * * *` | 02:00 hằng ngày | 35 phút / rclone 29 phút |
| Photos Daily | `17 20 * * *` | 03:17 hằng ngày | 40 phút / 1.500 giây; watchdog 1.800 giây |
| Photos Backfill | `45 21 * * *` | 04:45 hằng ngày | 330 phút / 18.000 giây; watchdog 18.300 giây |
| Photos Reconcile | `41 19 1 1,4,7,10 *` | 02:41 ngày 2 tháng 1/4/7/10 | 60 phút / 2.400 giây; watchdog 2.700 giây |

Nguồn thực thi: [Drive bisync](https://github.com/hunghvt-cyber/my-backup-gdrive-koofr/blob/main/.github/workflows/bisync.yml),
[Daily](../.github/workflows/daily.yml), [Backfill](../.github/workflows/backfill.yml),
[Reconcile](../.github/workflows/reconcile.yml). Schedule có thể trễ; ba job media Photos
dùng chung concurrency. Giữ thời gian dự phòng lưu manifest/profile/state.
Drive extended_budget là lựa chọn thủ công 330 phút/job và 300 phút rclone,
không tự bật và không đồng nghĩa được phép reset/resync.

Kế hoạch 1.784 phút/tháng dưới đây thuộc thời kỳ private ngày 15/10 và **không
còn mô tả lịch đang cấu hình**. Không hứa chạy public là miễn phí vô hạn hoặc phù
hợp mọi cách dùng; quota/billing và điều kiện tài khoản phải kiểm riêng trước đổi nơi chạy.
Không đổi visibility, budget hoặc workflow để sửa tài liệu.

## Kế hoạch private 15/10/2026 — lưu lịch sử, đã được thay thế

> Current public-runner policy and web backup upgrade: see [AI_CONTEXT.md](../AI_CONTEXT.md). Older budget and grid-scanner notes below are historical.

# Shared GitHub Actions free-tier operating budget

Updated: 2026-10-15. Source of truth for both
[`google-photos-koofr`](https://github.com/hunghvt-cyber/google-photos-koofr)
and
[`my-backup-gdrive-koofr`](https://github.com/hunghvt-cyber/my-backup-gdrive-koofr).

## Decision

Keep both repos **private** and run unattended backups within a conservative
planning envelope assuming **GitHub Free = 2,000 standard runner minutes per
billing month**. Keep Google Photos as the ONLY source of Photos backup (no
Google Takeout or mobile device uploads). This is a quota plan, not a guarantee
of no charges: all other private repos, manual reruns and extra jobs share the
account's quota. GitHub Pro or a different plan has other limits.

### Scheduled workflows, Vietnam local time (UTC+7)

| Workflow | UTC cron | ICT schedule | Job hard cap | Internal worker cap |
| --- | --- | --- | --- | --- |
| Drive ↔ Koofr `bisync.yml` | `0 19 * * *` | 02:00 daily | **35 min** | rclone **29 min**, interrupt grace up to 2 min; state/artifact/log reserve |
| Photos `daily.yml` | `17 20 * * *` | 03:17 daily | **9 min** | `MAX_RUNTIME_SECONDS=300` and **240s external watchdog** |
| Photos `backfill.yml` | `45 21 * * 0,2,4,6` | 04:45 **Mon/Wed/Fri/Sun** | **20 min** | `MAX_RUNTIME_SECONDS=720`; **660s watchdog**; browser profile/log reserve |
| Photos `reconcile.yml` | `41 19 1 1,4,7,10 *` | 02:41 **2nd day of Jan/Apr/Jul/Oct** | **60 min** | `MAX_RUNTIME_SECONDS=2400` and **2700s watchdog** |

The rclone deadline is set **after preparation**; the job cap includes setup.
The Photos worker budget is set inside Python and pauses near its deadline,
while the outer shell `timeout` is a fail-safe if a browser request hangs.
The `if: always()` profile, cache, cleanup and report steps run after a
*step failure*; they cannot execute after GitHub forcibly kills the whole job.
This is why worker deadlines are substantially shorter than job deadlines.

**Efficiency rationale:** Profile restore/persistence is paid on each Photos
Backfill run. Running a 20-minute Backfill four days a week may process more
historical media per billed minute than seven very short runs. **Photos Daily
continues every single day.** The history queue remains in SQLite on Koofr
between runs; existing remote photos are not deleted.

### Worst-case calendar-month projection (GitHub Free)

A 31-day month has at most **18** Mon/Wed/Fri/Sun scheduled Backfill days.
Assuming every scheduled job reaches its **full** timeout:

| Workflow | Max runs | Max minutes |
| --- | ---: | ---: |
| Drive Bisync | 31 | 31 × 35 = **1,085** |
| Photos Daily | 31 | 31 × 9 = **279** |
| Photos Backfill | 18 | 18 × 20 = **360** |
| Photos Quarterly Reconcile (only if applicable) | 1 | **60** |
| **Total, including quarterly run** | | **1,784 min** |
| **Remaining from a 2,000-min Free allotment** | | **216 min** |

The 216-minute difference is **not** an account-wide safe balance: additional
workflow runs, manual resync, other repositories, job reruns and billing-cycle
boundaries can consume it. GitHub may queue scheduled jobs and run them later.
Only [GitHub Billing](https://github.com/settings/billing) shows actual current
monthly entitlement/usage for the owner. Set an Actions spending budget or
spending restriction and alerts for 75%, 90% and 100% if available. Configure
a no-overage spending limit when zero extra charges are required. Do not
expose Google Photos/Koofr secrets or switch repos public just to save minutes.

### Drive extended/manual restoration

Normal automatic Drive sync is intentionally bounded at 35min/job / 29min
for rclone. The previous 5h30 job/5h sync path is preserved as the
**manually enabled** `extended_budget=true` workflow_dispatch input, alongside
`resync` and `reset`. Select it only for one-off major migrations/recovery
and only after checking monthly quota, since it may exceed the planned
2,000-minute free allocation. Do **not** use `reset` casually.

If regular Drive bisync exceeds its 29-minute rclone budget, it reports
`BISYNC PAUSED AT 29-MIN BUDGET`; the workflow saves its rclone cache,
ignore list, artifact and summary for continuation. It does NOT mark an
unfinished resync as completely synchronized. Repeated pauses warrant
investigation; do not silently raise scheduled runner timeouts.

### Quarterly inventory

Quarterly Photos Reconcile is **report-only**, no deletion; it has a 60m
job cap and a shorter internal scanner budget. If inventory is too large to
complete within a run, report `PAUSED` and continue from its Koofr state
on a subsequent run; never claim a complete historical inventory from a
partial checkpoint. Quarterly runs and daily Photos jobs share
`concurrency: google-photos-koofr-state` so their Koofr manifest and
encrypted Chrome profile are not written concurrently.

### Diagnostics to check after rollout

1. Drive: action run end status and artifacts `bisync-report-<run_id>`,
   `rclone_exit_code`, `BISYNC SUCCESS` versus `BISYNC PAUSED`;
   caches and ignored file lists must be saved. Latest observed normal
   bisync: ~27 min rclone, ~28.3 min full job (2026-10-14 run 38520318431).
2. Photos Daily: `DAILY_HEALTH` and `daily-health-<run_id>`.
   Latest observed sample: ~3.6 min complete.
3. Photos Backfill: `BACKFILL_SUMMARY`, `uploaded`, `errors`,
   `manifest_uploaded_total`, `pending_seen`, `uploaded_per_hour`,
   `PROFILE_PERSIST_SECONDS`, and `PROFILE_ARCHIVE_BYTES`.
   Latest verified run 38658212741: **44 uploads**, 276 media discovered,
   22.8min job with previous, longer quotas.
4. A `timeout` exit 124 or missing JSON summary is a warning that the
   task may have been forcibly interrupted. Review state/manifest before
   trusting the green/red job result.

The new budgets and watchdogs require live run validation. Do not promise
that every scheduled job will finish before the job cap or that all image
errors have been fixed. The priority is preserving durable Koofr state and
making incremental progress in a cost-controlled way.
