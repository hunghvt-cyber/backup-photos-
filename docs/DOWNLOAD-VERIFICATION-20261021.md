# Download verification and Daily scan — 21 October 2026

## Observed evidence (historical, not current inventory)

Daily run 39513549851: 19 discovered, 7 already-uploaded skipped, 12 attempted,
11 uploaded, one download failed HTTP 403 after three attempts. Reporting succeeded.
Backfill run 39386977931: 1,085 attempted, 1,013 uploaded, 72 errors; 69 source-size
mismatches and three unconfirmed remote listings. Final snapshot: 28,073 inventoried,
1,267 manifest uploaded, 49 albums, inventory_complete=false. These scopes differ;
no complete-library percentage can be calculated from them.

## Changes

- Metadata original URL failures, HTML and source-size mismatch now try the signed
  original RPC once. Both routes retain source-size validation and allowed hosts.
  Partial files are removed; exhausted failures remain errors. No thumbnail fallback.
- Daily HTTP replay 403 can use the completed Chrome download for the same item.
  Empty files are still rejected; existing SHA/Koofr-size checks remain required.
  This does not prove the previously failing Google item will now download.
- Empty/failed remote size listings get at most three reads with bounded waits;
  these retries never upload again. A real different size fails immediately.
  Unconfirmed records are not marked uploaded. Existing manifest is not reset.
- Daily collects intermediate gallery viewports via the existing scroll helper.
  Repeated no-growth is SCAN_STALLED, not completion. Limit/time stops remain
  incomplete. Only reaching the existing incremental boundary without errors is
  successful Daily completion; this is not full historical coverage.
- The existing newest ID is preserved when downloads fail or the scan stalls.
  The misleading bootstrap_complete flag becomes false on the next Daily run;
  the newest ID continues to be used independently. No generation/cursor is reset.
  With no existing boundary, Daily remains incomplete; historical coverage belongs
  to the paginated Backfill inventory, not to viewport stagnation.
- Daily health artifacts include scan_status. Public GAS schema stays unchanged.
- A credential-free PR/main workflow runs syntax and offline fault regressions.

## Verification and rollout

40 offline unittest checks pass, including valid signed fallback after mismatch,
rejected fallback size, HTML/transport failures, invalid host, reserve handling,
remote-listing recovery, no false uploaded state, stalled scan, retained failed
boundary, intermediate viewports and Chrome 403 fallback. Compile and diff checks pass.
Tests use synthetic responses and do not validate live Google/Koofr behavior.

After merge, scheduled Daily/Backfill use the new source. No manual bulk run,
source deletion, destination deletion, manifest repair/reset, secret rotation,
schedule change, NAS change or Homepage deployment is part of this change.
Next real runs must establish failure counts, fallback success, boundary status
and preserved pending errors. Never infer full coverage from a green job.
