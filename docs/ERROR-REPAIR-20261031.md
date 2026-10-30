# Repair of 198 failed media — 31 October 2026

## Current verified status
**176 of the initial 198 failures repaired; 22 camera RAW files remain unresolved.**
Manifest uploaded total: **10,167**; pending seen: 42,562; pending errors: 22.
Full-library coverage remains incomplete. No Google Photos additions, edits or deletions have been performed.

## Proven causes and repairs
- **134 Live Photos**: Google source size represents still + motion components. Example HEIC 2,160,850 + MP4 4,758,336 = 6,919,186 source bytes. Comparing one derivative to the aggregate caused false failures.
- Complete Live Photos are preserved in the unchanged official `.livephoto.zip`, with both original names. Exactly two safe image/video members, exact aggregate source size, CRC, still magic and valid motion stream/duration are required. Upload SHA-256 and Koofr size checks remain enabled.
- **41 remote verification failures**: `rclone lsl` returned rc=0 with empty output for real objects. Exact `lsjson --stat` confirmed their file sizes. Empty listings now require exact stat before upload; same-sized existing objects are hash-compared before reuse. Unknown stat never authorizes overwrite.
- **1 ConnectionError** recovered on retry.

## Runtime evidence
- Initial audit 41126815085: 198 eligible error rows; 156 size mismatches, 10 REMOTE_SIZE_UNCONFIRMED, 1 ConnectionError and 31 OTHER. Subsequent retries classified those 31 as remote verification failures.
- Exact-stat smoke 41131301904 recovered one object.
- Acceptance [41132219007](https://github.com/hunghvt-cyber/backup-photos-/actions/runs/41132219007): 2 attempted, 2 uploaded, 0 errors; one hash-verified reuse and one complete Live Photo archive.
- Full remaining batch [41132862344](https://github.com/hunghvt-cyber/backup-photos-/actions/runs/41132862344), source df917e32663a39948776293273b0e7051e3d8952: **194 attempted, 172 uploaded, 22 errors**. Source status PARTIAL/failure is accurate. Inventory unchanged (52,742 inventoried, 49 albums, 25,316 album memberships). Profile refresh and worker cleanup completed.
- Together with four earlier repairs, this proves 176 repaired. Publisher 41140263635 succeeded separately; publication success is not complete backup success.

## Residual RAW investigation
Read-only audit [41144300819](https://github.com/hunghvt-cyber/backup-photos-/actions/runs/41144300819) found all 22 unresolved items are RAW, source=shared, saved flag=true and original-quality flag=true. Audit plaintext cleanup passed.
- First three samples have source sizes around 21–23 MB; preferred metadata URL, alternative URL, signed RPC and official ZIP all returned roughly 0.9 MB derivatives. The size gate rejected them.
- ItemInfoExt and independent batch metadata agree; raw numeric quality code=2. No size tolerance or preview acceptance was introduced.
- RAW extensions now explicitly reject JPEG/WebP previews, in addition to source-size checks.
- Read-only owned-copy scan 41144798031 matched 13 dedup keys to the same IDs and found no different owned copies before an empty API page stopped the scan. This is not proof that all possible aliases were examined.
- Browser probes confirmed the photo viewer contains a Vietnamese more-options control, but the old literal label matcher failed. Matching now normalizes decomposed Unicode/nonbreaking spaces and only selects explicit original/RAW download actions; delete/revert controls are covered by a rejection test.
- Current native-original canary [41146287031](https://github.com/hunghvt-cyber/backup-photos-/actions/runs/41146287031) is pending. No runtime recovery of those 22 is yet proven.

## Final-state requirements
- Normal Backfill cron remains `45 21 * * *` (04:45 Asia/Ho_Chi_Minh daily), engine 18,000 seconds, watchdog 18,300 seconds, cap 330 minutes.
- Proven ZIP fallback is enabled for normal Backfill. Native-original browser recovery remains disabled in normal runs pending runtime acceptance.
- Error-only repair skips inventory and preserves Daily checkpoint. All one-time triggers and temporary audit workflow files have been removed after dispatch.
- Existing encrypted fallback and recovered profile copies remain on Koofr. Worker plaintext/cookies/config are always cleaned; no assertion is made about files in the user's closed Codespace.
- Latest completed source CI at 7229a58ce4cb69e2a00cb7f8da09cbf1ff3af638 passed. Continue from the current canary; do not claim 198/198 or reset remaining errors without proof.
