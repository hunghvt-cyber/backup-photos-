# Operations

Đọc [README](../README.md) và [lịch/ngân sách hiện hành](FREE_TIER_BUDGET.md); hướng dẫn download mới ở [VIDEO-ORIGINAL-IDENTITY](VIDEO-ORIGINAL-IDENTITY-20261022.md).

## Normal operation

No computer is required for normal use.

- Daily backup runs automatically at 03:17 Asia/Ho_Chi_Minh.
- Quarterly reconcile uses the simple UTC cron `41 19 1 1,4,7,10 *`: 19:41 UTC on day 1, equivalent to 02:41 Asia/Ho_Chi_Minh on day 2 of January, April, July and October.
- The repository and GitHub Actions logs can be inspected from a phone or iPad.
- Persistent state and the encrypted Google session profile live on Koofr.
- Daily/Backfill dùng worker web hiện hành; inventory toàn thư viện chưa được chứng minh. Không dùng bootstrap_complete cũ làm chứng nhận hoàn tất.
- For AI-assisted maintenance, read `AI_CONTEXT.md` before changing production.

## When manual intervention is required

Manual action is only expected when one of these credentials becomes invalid:

1. Google requires interactive login or 2FA again.
2. The Koofr application password is revoked.
3. The profile encryption key is intentionally rotated.

Never paste passwords, cookies, application passwords or the profile encryption key into chat or commit them to the repository.

## Google session refresh

Successful jobs persist the refreshed Chrome profile back to Koofr in encrypted form. This normally lets session refreshes survive fresh GitHub runners without another login.

If Google explicitly requires login again, recreate the interactive profile in Codespaces/noVNC, close Chrome, encrypt the profile with the current GitHub secret key, and replace:

`Google Photos/.gphotos-sync/auth/profile.tar.gz.enc`

## Failure semantics

- A media upload is not marked complete until Koofr reports the same byte size as the local download.
- The remote SQLite manifest is written from a consistent SQLite Backup API snapshot, never by copying the live WAL database.
- If manifest state is missing but an existing Koofr candidate matches size and SHA-256, the existing object is reused and manifest state is reconstructed.
- Failed media remain retryable.
- A daily run with media errors exits red after state is safely flushed.
- Daily, Backfill and Reconcile media jobs share one concurrency group.
- Reconcile is report-only and cannot delete files.
