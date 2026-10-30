# Profile recovery — 30 October 2026

## Verified runtime
- PR #15 merged at `391fab02f1a85eb6b264fa429f6ccfd433aed59a`; 80 offline tests passed.
- Recovery run [41088990025](https://github.com/hunghvt-cyber/backup-photos-/actions/runs/41088990025) succeeded using existing Actions secret `GPHOTOS_PROFILE_KEY`.
- Staged transfer SHA-256: `f2b57e0847cd4d74716c5c50b7252fef894b3badc51d73b2328ae6c5e4489d33`. This compares two reads from Koofr, not an independent original checksum from Codespaces.
- Encryption round-trip and remote encrypted hash checks passed.
- `RECOVERY_FALLBACK_UNCHANGED=PASS`: existing `profile-before-relogin-20261030.tar.gz.enc` unchanged.
- Additional encrypted recovery copy: `auth/profile-recovered-20261030.tar.gz.enc`.
- `RECOVERY_PROFILE_PERSISTED=PASS`, `RECOVERY_PLAINTEXT_REMOTE_CLEANUP=PASS`, `RECOVERY_PLAINTEXT_LOCAL_CLEANUP=PASS`.
- Plaintext staged `profile-recovery-20261030.tar.gz` removed after verified encrypted persistence. Recovery worker temporary files and rclone configuration removed. No assertion about files in the user's closed Codespace.

## Fresh-runner media proof
Canary [41089999399](https://github.com/hunghvt-cyber/backup-photos-/actions/runs/41089999399), source `fe1a6c584d3f660c9994fd8d01cef5d5f0089b01`, succeeded:
- Attempted 3, uploaded 3, skipped 0, errors 0.
- Manifest uploaded total: 9,991 (previous total 9,988).
- Inventoried total: 52,742; albums: 49; album memberships: 25,316.
- Pending seen: 42,562; pending errors: 198. Existing errors remain unresolved.
- Inventory complete: false; inventory error: false.
- Profile refresh persistence, cleanup and health artifact steps succeeded.
This proves authenticated enumeration and real media transfer resumed. It does not establish complete library coverage or sustained daily throughput.

## Final workflow state
All one-time push triggers removed. Backfill keeps normal cron `45 21 * * *` (04:45 Asia/Ho_Chi_Minh daily), engine budget 18,000 seconds, watchdog 18,300 seconds and job cap 330 minutes. Shared Daily/Backfill/Reconcile concurrency retained. No NAS migration, manifest reset or source media deletion.
Manual recovery remains available with optional independent checksum. Invalid provided checksum fails closed; omitted checksum requires matching downloaded and separately streamed Koofr hashes. Local plaintext is cleaned on exit and via always() cleanup. Backfill does not overwrite encrypted auth if it never produces WEB_SUMMARY.

## Separate progress reporting
Canary source backup succeeded, but publisher initially failed with WRONG_WORKFLOW: allowlist still used `hunghvt-cyber/backup-drive`. Corrected to current `hunghvt-cyber/backup-photos-`; legacy public report URL identity preserved for existing consumers. Only failed publisher job rerun, without media replay. Consult run 41090740127 latest attempt for publication outcome.
