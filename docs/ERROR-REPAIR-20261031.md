# Failed-media repair — 31 October 2026

User authorized repair of all 198 existing failures, preserving source media and backup state. No NAS migration.

## Runtime evidence
- Audit/retry run [41126815085](https://github.com/hunghvt-cyber/backup-photos-/actions/runs/41126815085): 198 errors, all eligible (no missing web_items joins). Categories: 156 ORIGINAL_SIZE_MISMATCH, 10 REMOTE_SIZE_UNCONFIRMED, 1 ConnectionError, 31 OTHER. Ten retries uploaded zero; all ten still failed source-size validation.
- Browser fallback run [41127923291](https://github.com/hunghvt-cyber/backup-photos-/actions/runs/41127923291): 3 attempted, zero uploaded, 3 mismatches. Official browser Download and signed RPC produced identical actual lengths, both smaller than metadata. Examples expected/actual: 6958745/6837893, 5625266/5492690, 7109815/7003121 bytes. This does not prove the reason (metadata, edits, motion component or server transformation remain unproven).
- A previous browser trial stopped during offline validation because runtime flags affected test expectations. Validation now explicitly clears repair flags; no media were touched by that failed trial.
- Current bounded batch [41128598154](https://github.com/hunghvt-cyber/backup-photos-/actions/runs/41128598154), source e22ba4b89721c86ce38384dd29697d47019d7cc6: maximum 45 error-only attempts, 3600-second engine budget. Prioritizes 42 non-size failures, then tests official ZIP on size failures. Outcome still pending at document creation.

## Safety and implementation
- Explicit repair_errors input only; normal schedule/budget unchanged and all one-time push triggers removed immediately after dispatch.
- Error-only runs skip inventory entirely, preserving inventory cursors and Daily checkpoint.
- Aggregate before/after error audit never prints stored raw errors, signed URLs or private filenames.
- Existing SHA-256, actual media validation, source-size comparison, Koofr remote-size verification, consistent SQLite snapshot and collision-safe reuse retained.
- Optional official browser path still rejects wrong source size; it did not recover the three tested samples.
- Optional official ZIP path uses bounded token polling, verifies declared ZIP download size, requires exactly one correctly named member with exact source size, streams with byte limit and validates ZIP CRC. Wrong size, extra members and unsafe paths are rejected.
- No error is marked uploaded merely to reduce the counter. Failed entries remain repairable.
- Source/tests passed CI before starting batch. Existing encrypted auth fallback preserved; worker cleanup runs always.

## Remaining acceptance
Read completed batch logs, compare before/after error counts and verified uploads, inspect public report. Do not claim 198 repaired until runtime proves zero pending errors. If ZIP still differs from metadata, retain errors and record that limitation rather than relaxing original verification.
