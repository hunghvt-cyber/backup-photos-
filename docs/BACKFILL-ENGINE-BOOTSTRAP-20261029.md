# Backfill engine bootstrap correction — 29 October 2026

## Evidence and limits

Source run 40799294163 recorded WEB_FATAL type=IndexError after profile/state
restore. The original log has no traceback or stage, so its exact failing line
cannot be proved retrospectively. The pinned gpwc client parses only
script[data-id="_gd"] and immediately indexes element zero; a synthetic valid
HTML page without that attribute reproduces IndexError. A login redirect or
changed HTML can trigger that path. This reproduction is not proof that the
owner's session expired.

## Correction

Read and validate the required WIZ_global_data fields in the already-restored
Chrome session, with at most a 30-second wait. Detect exact account/consent hosts
and fail closed. Reuse that same session metadata and exported cookies in the
bounded client rather than fetching/parsing another HTML page with requests.
No token, cookie, account email, page body, signed URL or exception message is
logged. Fatal diagnostics contain stage and frame basename/line/function only.
The RPC wrapper turns IndexError/KeyError/TypeError response-shape problems into
a safe failure rather than an empty successful inventory.

When the restored manifest/database is available, fatal bootstrap produces the
actual aggregate counts with inventory_error=true and inventory_complete=false.
It does not fabricate an uploaded count or advance inventory cursors. Missing or
unrestored state still cannot produce a successful backup. The encrypted Chrome
profile is preserved when browser bootstrap was not verified.

Original-media size/hash checks, destinations, checkpoint order, media identity,
shared concurrency, cleanup and normal daily Backfill schedule stay unchanged.

## Validation and bounded canary

Full offline suite: 87/87 PASS; compile and workflow YAML/bash syntax PASS.
Regressions reproduce upstream IndexError, validate delayed browser bootstrap,
reject login/consent/missing metadata, prove no second HTTP bootstrap, sanitize
RPC shape failures and preserve real restored counts on a fatal start.

A manual Backfill dispatch with max_items=1 now selects the canary settings:
one attempted item maximum, 30-second inventory budget, 900-second engine budget
and 930-second watchdog plus 30-second termination grace. Other runs retain the
existing 5-hour engine budget and default scan. The canary uses the existing
concurrency group and verified original download/upload path. No resync, media
purge or source deletion is introduced. Live canary and release results must be
recorded separately; unit tests do not establish a working Google session.
