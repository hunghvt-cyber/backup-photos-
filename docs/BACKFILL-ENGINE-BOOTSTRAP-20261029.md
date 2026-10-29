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

## Follow-up diagnostic implementation — 29 October 2026

Implementation commit: `980df25ef7f14f0399453bc5ec3012e4108bfa85` on
`fix/backfill-browser-bootstrap-20261029` (PR #14).

The decoded log for run 40820467446 was filtered in memory before analysis; no
raw Actions log was sent to Gemini. It contains two timeout snapshots. The first
was still on `photos.google.com`, with a sign-in form and challenge selector
present; `WIZ_global_data` existed but `FdrFJe`, `cfb2h` and `Im6cmf` were
`NoneType` (only `SNlM0e` was a string). The later snapshot was on
`www.google.com`, with no form, challenge selector or bootstrap object. Both
reported `WEB_BOOTSTRAP_STATUS=UNAVAILABLE`. The profile restore step succeeded
and profile persistence was skipped, preserving the original encrypted Koofr
archive. No media was attempted. This sequence does not establish whether the
cause was authentication, Google challenge/routing, profile compatibility, or
page metadata timing/schema.

Gemini's first analysis independently reached the same limit: the redirect and
one incomplete metadata snapshot do not prove session expiry or bot detection.
It recommended recording a sanitized main-frame redirect chain and HTTP
statuses, page-state booleans, metadata presence/types, actual profile
structure/access, and Chromium version.
The independent Gemini review of a new runtime diagnostic is still pending;
there is no new diagnostic run to review yet.

The follow-up code adds those filtered diagnostics. Only exact allowlisted
Google hostnames are emitted; unknown hosts become `[other-host]`, unknown path
segments become `[redacted]`, and query/fragment are discarded. A manual
`bootstrap_diagnostic=true` workflow input restores the encrypted profile,
copies it to a disposable profile directory, and performs one bootstrap-only
navigation with no manifest restore, inventory, media attempt, or profile
persist. The original encrypted Koofr profile remains untouched. The run also
reports profile archive/layout/access facts and the Chromium version; it does
not collect a screenshot.

Offline validation after this change: compileall and 92/92 unit tests pass;
workflow YAML and bash blocks parse; `git diff --check` passes. No local
`gphotos-profile`, Chromium executable, or Koofr credentials were available in
the checkout environment, so the new one-time diagnostic run has not yet been
executed. No `READY`, media enumeration, image/video upload, checksum, Koofr
object, or resume result is claimed. Do not run an ordinary Backfill canary.

Required operator action: after this branch is pushed, open Actions → Google
Photos Historical Backfill → Run workflow, leave `max_items` at `1`, set
`bootstrap_diagnostic` to `true`, and start exactly one run. Share only the run
ID; its log can be fetched and filtered for review. If it reports
`AUTH_REQUIRED`, `CONSENT_REQUIRED`, or an equivalent sign-in gate, refresh the
session by opening the established private profile interactively on the
trusted machine that owns it, confirm Photos opens, close Chromium cleanly, and
allow the normal encrypted profile-save flow to update Koofr. Never send the
password in chat. If profile ownership or that trusted machine is unavailable,
stop and ask the owner to perform those steps; do not replace the Koofr archive.
