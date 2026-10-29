# Backup/report recovery — 29 October 2026

## Evidence and scope

The canonical repositories were renamed: `backup-photos` is Drive/Koofr bisync,
`backup-drive` is Google Photos/Koofr. Do not infer their roles from their names.
The publishers at the failed run commits allowed only the former names, rejected
the actual GitHub repository identity before HTTP, then masked
`UNAPPROVED_REPOSITORY` as `REQUEST_FAILED`. A local reproduction made zero
network calls. This is separate from the media backup failures.

The publisher now explicitly allows the two canonical names and their historical
aliases, checks the actual repository/workflow and report run identity, then
normalizes only the public run URL to the historical GitHub alias already
accepted by deployed GAS and Homepage readers. Source labels and run IDs are
unchanged. These aliases refer to the same repositories; this does not authorize
other repositories, backfill-to-daily publishing, or arbitrary URL rewriting.
No GAS deployment, report key change or Homepage deployment is required.
Known validation errors remain explicit; unknown exception text remains redacted.

Offline checks cover both renamed sources, signed ACK verification, preserved
wire schema, rejected cross-source/workflow identities and bounded retries.
Both normalized failure reports were also accepted by the current Homepage GAS
schema source. This is local compatibility evidence, not a live signed GAS ACK.
No media backup or report was fabricated or replayed during local validation.

## Photos library readiness

[Run 40791344646](https://github.com/hunghvt-cyber/backup-drive/actions/runs/40791344646)
failed around 07:03 ICT on 29 October before enumeration: no media tile was
visible after a fixed four-second wait. That message alone cannot distinguish
expired login from slow loading or changed UI.

Daily now waits up to 30 seconds for the existing media selector. Exact account
and consent hosts emit safe AUTH_REQUIRED / CONSENT_REQUIRED diagnostics;
missing/changed/empty gallery emits GALLERY_NOT_READY and remains a failure.
No account URL, cookie, DOM, screenshot or Notes data is logged. A failed
readiness check closes the browser before enumeration; it never advances the
checkpoint or marks an empty scan successful. The profile persistence step
preserves the original encrypted remote profile when this check fails.

This does not automate Google login or bypass 2FA. If AUTH_REQUIRED remains in
a live run, an owner-controlled interactive profile refresh is still necessary.
Backfill implementation, manifest, checkpoints, schedules and concurrency stay
unchanged. Local suite: 78 tests pass; YAML and bash syntax pass. Authenticated
Google runtime and live report delivery remain to be verified by a bounded
canary (manual Daily max_items=1) after reviewed source reaches main.
