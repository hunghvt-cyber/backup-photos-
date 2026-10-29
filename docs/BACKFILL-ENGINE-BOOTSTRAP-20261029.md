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

Full offline suite: 89/89 PASS; compile and workflow YAML/bash syntax PASS.
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


## Authenticated canaries — release remains blocked

Three manually bounded branch canaries ran with max_items=1:

- [40808967152](https://github.com/hunghvt-cyber/backup-drive/actions/runs/40808967152), source d6c0eb19700d65a23d7f2f24b9a6702866a50df2: bootstrap unavailable.
- [40809580474](https://github.com/hunghvt-cyber/backup-drive/actions/runs/40809580474), source c37f3960fc490d71af8043270367445ccce6eb59: unavailable; safe field-shape diagnostics added.
- [40820467446](https://github.com/hunghvt-cyber/backup-drive/actions/runs/40820467446), source ef2e1d6090b2a7b426a7244614fcca249bdcdb30: actual Historical backfill step at 2026-10-29T04:57:23Z reported host_class=www.google.com, photos_host=false, global_present=false, signin_form=false, challenge_frame=false. No raw URL/path/query, account data or tokens were recorded.

All three failed before any media attempt. The restored manifest reports 9,988
uploaded, 42,561 pending seen, 198 pending errors; these are existing manifest
counts, not uploads made by these canaries. The original encrypted profile was
preserved. The canary branch does not publish to the main-only progress feed.
Synthetic fixture output from Validate backfill implementation is not runtime
backup evidence; inspect the Historical backfill step separately.

Latest source CI passed (40809963747); authenticated operation did not. PR #14
therefore remains unmerged. The redirect proves this worker did not reach the
Photos library; it does not prove session expiry or bot detection. Next action
is to check/refresh the existing worker's Google session through the established
private profile flow, then repeat one bounded canary. Do not weaken media
validation, follow an alternate provider route, reset cursors, purge backups or
merge under a claim of production recovery.
