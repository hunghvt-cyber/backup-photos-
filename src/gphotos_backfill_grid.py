"""Historical grid scanner and resilient bulk backfill for Google Photos.

The scan and download phases deliberately use separate sequential browser
lifetimes: a failed Shift+D download cannot destroy the live scrolling session.
The persistent SQLite manifest in Koofr remains the source of truth.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from src.gphotos_sync import Engine, SEL, cmd, created, href, ident, now, savej

SCROLL_JS = r"""() => {
  // The Photos timeline is virtualized. The document root may have a tiny
  // scrollbar while a nested ancestor owns the actual gallery scroll.
  const tile = document.querySelector('a[href*="/photo/"],a[href*="/video/"]');
  const ancestors = [];
  for (let el = tile; el; el = el.parentElement) ancestors.push(el);
  const root = document.scrollingElement || document.documentElement;
  const extras = Array.from(document.querySelectorAll(
    '[role="main"],main,[role="grid"],[style*="overflow"],div'));
  const candidates = Array.from(new Set([...ancestors, root, ...extras]));
  const choices = [];
  for (const el of candidates) {
    const max = el.scrollHeight - el.clientHeight;
    if (max < 90 || el.clientHeight < 100) continue;
    const style = getComputedStyle(el);
    const score =
        (ancestors.includes(el) ? 1000 : 0) +
        (/(auto|scroll|overlay)/.test(style.overflowY) ? 100 : 0) +
        Math.min(max / 100, 100);
    choices.push({el, max, score, overflow: style.overflowY});
  }
  choices.sort((a, b) => b.score - a.score);
  const diagnostics = choices.slice(0, 5).map(x => ({
    tag: x.el.tagName, className: String(x.el.className || '').slice(0, 90),
    top: Math.round(x.el.scrollTop), max: Math.round(x.max),
    client: Math.round(x.el.clientHeight), overflow: x.overflow
  }));
  let chosen = null;
  for (const x of choices) {
    const before = x.el.scrollTop;
    const step = Math.max(450, Math.round(x.el.clientHeight * 0.75));
    x.el.scrollTop = Math.min(x.max, before + step);
    const after = x.el.scrollTop;
    if (after > before + 1) {
      chosen = {before, after, max: x.max, tag: x.el.tagName, step};
      break;
    }
  }
  return {moved: Boolean(chosen), ...(chosen || {
    before: 0, after: 0, max: 0, step: 0, tag: null
  }), diagnostics};
}"""

def advance_gallery(page, iteration):
    """Combine native wheel/keyboard events with nested scrolling.

    React virtualized galleries may ignore scrollTop changes without native
    wheel/keyboard signals. This is intentionally independent from download
    code, and never clicks thumbnails or changes browser URL.
    """
    anchors = page.locator(SEL)
    if anchors.count():
        last = anchors.last
        try:
            last.scroll_into_view_if_needed(timeout=4000)
        except Exception:
            pass
    metrics = page.evaluate(SCROLL_JS)
    # Wheel must be delivered over the gallery, not over the sidebar.
    page.mouse.move(650, 520)
    page.mouse.wheel(0, 650 + (iteration % 3) * 200)
    if iteration % 3 == 2:
        page.keyboard.press("PageDown")
    page.wait_for_timeout(1100 if metrics["moved"] else 1600)
    return metrics

VISIBLE_JS = r"""elements => elements.map(el => ({
  href: el.getAttribute('href'),
  label: el.getAttribute('aria-label') || el.getAttribute('data-tooltip')
}))"""


def parse_tiles(raw):
    items = []
    seen = set()
    for entry in raw:
        raw_url = entry.get("href")
        if not raw_url:
            continue
        url = href(raw_url)
        try:
            media_id, media_type = ident(url)
        except ValueError:
            continue
        if media_id in seen:
            continue
        seen.add(media_id)
        label = entry.get("label")
        items.append((media_id, media_type, url, label, created(label)))
    return items


class GridBackfill:
    def __init__(self, args):
        self.args = args
        self.engine = Engine(args)
        self.state_path = self.engine.sd / "backfill-grid-checkpoint.json"
        result = cmd("rclone", "copyto",
                     f"{args.sroot}/backfill-grid-checkpoint.json",
                     str(self.state_path), ok=False, cap=True)
        if result.returncode:
            self.state_path.unlink(missing_ok=True)
        self.state = self.engine.load("backfill-grid-checkpoint.json",
                                      {"version": 2, "runs": 0,
                                       "visited_unique_total": 0})
        self.stats = self.engine.stats
        self.scanned_unique = set()
        self.pending = {}
        self.scan_rounds = 0
        self.scan_status = "NOT_STARTED"
        self.anchor_id = None

    def persist(self, status):
        e = self.engine
        self.state.update({
            "version": 2, "updated_at": now(), "status": status,
            "scan_status": self.scan_status,
            "scan_rounds": self.scan_rounds,
            "last_seen_id": self.anchor_id,
            "last_run_stats": dict(self.stats),
            "manifest_uploaded_total": e.db.c.execute(
                "SELECT COUNT(*) FROM media WHERE status='uploaded'").fetchone()[0],
            "pending_seen": e.db.c.execute(
                "SELECT COUNT(*) FROM media WHERE status='seen'").fetchone()[0],
            "pending_errors": e.db.c.execute(
                "SELECT COUNT(*) FROM media WHERE status='error'").fetchone()[0],
        })
        # Flush the manifest before making the new scan position durable.
        e.flush()
        savej(self.state_path, self.state)
        cmd("rclone", "copyto", str(self.state_path),
            f"{self.args.sroot}/backfill-grid-checkpoint.json", "--ignore-times")
        print("GRID_CHECKPOINT=" + json.dumps({
            "status": status, "scan_status": self.scan_status,
            "queued": len(self.pending), "total_uploaded": self.state["manifest_uploaded_total"],
            "pending_errors": self.state["pending_errors"]}), flush=True)

    def scan(self, playwright):
        e = self.engine
        if e.left() < 360:
            self.scan_status = "TIME_BUDGET_LOW"
            return
        browser = None
        try:
            browser = playwright.chromium.launch_persistent_context(
                user_data_dir=self.args.profile, executable_path=self.args.chrome,
                headless=True, args=["--disable-dev-shm-usage", "--no-first-run"])
            page = browser.pages[0] if browser.pages else browser.new_page()
            page.set_viewport_size({"width": 1440, "height": 900})
            page.goto("https://photos.google.com/", wait_until="domcontentloaded",
                      timeout=90000)
            page.wait_for_timeout(5000)
            rounds_without_new_ids = 0
            already_uploaded = 0
            target = max(self.args.maxitems + 15, 25)
            for turn in range(1200):
                if e.left() < 360:
                    self.scan_status = "TIME_BUDGET_LOW"
                    break
                self.scan_rounds += 1
                raw = page.locator(SEL).evaluate_all(VISIBLE_JS)
                items = parse_tiles(raw)
                new_ids = 0
                for media_id, media_type, url, label, capture in items:
                    if media_id in self.scanned_unique:
                        continue
                    self.scanned_unique.add(media_id)
                    new_ids += 1
                    self.anchor_id = media_id
                    self.stats["discovered"] += 1
                    prior = e.db.c.execute(
                        "SELECT status FROM media WHERE id=?", (media_id,)).fetchone()
                    e.db.touch(media_id, media_type, url, label, capture)
                    if not prior or prior[0] == "seen":
                        self.pending[media_id] = (media_id, media_type, url, label, capture)
                    elif prior[0] == "uploaded":
                        already_uploaded += 1
                    # Broken historical photos stay in the error queue.
                if len(self.pending) >= target:
                    self.scan_status = "BATCH_READY"
                    break
                rounds_without_new_ids = (
                    0 if new_ids else rounds_without_new_ids + 1)
                metrics = advance_gallery(page, turn)
                if turn == 0 or new_ids or turn % 5 == 0:
                    print(
                        f"GRID_SCAN round={turn + 1} visible={len(items)} "
                        f"seen={len(self.scanned_unique)} new_ids={new_ids} "
                        f"pending={len(self.pending)} old={already_uploaded} "
                        f"moved={metrics['after'] - metrics['before']:.0f} "
                        f"max_scroll={metrics['max']:.0f} "
                        f"stagnant={rounds_without_new_ids}", flush=True)
                if turn == 0 or (rounds_without_new_ids >= 5
                                 and rounds_without_new_ids % 5 == 0):
                    # Only DOM scrolling metadata, no photo filenames or pixels.
                    print("GRID_SCROLL_DIAG=" + json.dumps(
                        metrics["diagnostics"]), flush=True)
                if rounds_without_new_ids >= 15:
                    self.scan_status = "SCROLL_STALLED"
                    break
            else:
                self.scan_status = "MAX_SCAN_ROUNDS"
            if not self.scanned_unique:
                raise RuntimeError("No Google Photos media tiles were discovered")
        except Exception as exc:
            self.scan_status = "SCAN_ERROR"
            print("GRID_SCAN_ERROR=" + repr(exc), file=sys.stderr, flush=True)
            # Preserve already discovered media and allow processing queued items.
        finally:
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass

    def queue(self):
        # Prefer new scanned historical items. A separate old-error retry tail
        # prevents a permanently blocked photo from consuming every run.
        candidates = list(self.pending.values())
        wanted = {r[0] for r in candidates}
        budget = self.args.maxitems
        if len(candidates) < budget:
            for row in self.engine.db.c.execute(
                "SELECT id,type,url,label,created FROM media "
                "WHERE status='seen' ORDER BY first_seen ASC LIMIT ?", (budget,)):
                if row[0] not in wanted:
                    candidates.append(row)
                    wanted.add(row[0])
                if len(candidates) >= budget:
                    break
        # Repeated HTTP-403 media are kept in the manifest for a dedicated
        # retry workflow, but must not consume the historical backfill quota.
        return candidates[:budget]

    def run(self):
        e = self.engine
        try:
            with sync_playwright() as playwright:
                self.scan(playwright)
                # Browser from scan() is now closed, so any download failure
                # cannot destroy the browsing/scrolling session.
                self.persist("DISCOVERY_SAVED")
                pending = self.queue()
                print(f"GRID_QUEUE count={len(pending)} max_items={self.args.maxitems} "
                      f"scan_status={self.scan_status}", flush=True)
                for index, (media_id, media_type, url, label, capture) in enumerate(pending, 1):
                    if e.left() < 300 or self.stats["attempted"] >= self.args.maxitems:
                        break
                    print(f"GRID_DOWNLOAD item={index}/{len(pending)} id={media_id}",
                          flush=True)
                    # Reuse the downloader already proven by Daily backup,
                    # including its independent Chrome session and HTTP replay.
                    e.one(playwright, media_id, media_type, url, label, capture,
                          update_checkpoint=False)
                    if index % 10 == 0:
                        self.persist("UPLOADING")
            if self.stats["attempted"] >= self.args.maxitems:
                status = "PAUSED_LIMIT"
            elif e.left() < 300:
                status = "PAUSED_TIME"
            elif self.scan_status in ("BATCH_READY",):
                status = "PAUSED_MORE_HISTORY"
            else:
                status = "SCAN_INCOMPLETE"
            self.state["runs"] = self.state.get("runs", 0) + 1
            self.persist(status)
        except Exception:
            self.persist("FAILED")
            raise
        return {
            "status": status, "scan_status": self.scan_status,
            **self.stats, "manifest_uploaded_total": self.state["manifest_uploaded_total"],
            "pending_seen": self.state["pending_seen"],
            "pending_errors": self.state["pending_errors"],
            "scan_rounds": self.scan_rounds,
            "unique_visible": len(self.scanned_unique),
            "runs": self.state["runs"],
        }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--profile", default=os.path.expanduser("~/gphotos-profile"))
    p.add_argument("--chrome", default=os.environ.get("CHROME_BIN", "/usr/bin/google-chrome-stable"))
    p.add_argument("--state", default="/tmp/gphotos-state")
    p.add_argument("--work", default="/tmp/gphotos-downloads")
    p.add_argument("--root", default="koofr_remote:/Google Photos/Photos")
    p.add_argument("--sroot", default="koofr_remote:/Google Photos/.gphotos-sync")
    p.add_argument("--seconds", type=int, default=int(os.environ.get("MAX_RUNTIME_SECONDS", "12000")))
    p.add_argument("--maxitems", type=int, default=int(os.environ.get("MAX_ITEMS", "100")))
    a = p.parse_args()
    if a.maxitems < 1 or a.maxitems > 1000:
        p.error("maxitems must be between 1 and 1000")
    job = GridBackfill(a)
    try:
        summary = job.run()
        print("BACKFILL_SUMMARY=" + json.dumps(summary, ensure_ascii=False), flush=True)
        # Report failure when zero work got done and scanning cannot progress,
        # or when every attempted download failed. Partial successes remain visible.
        all_failed = (summary["attempted"] > 0 and summary["uploaded"] == 0
                      and summary["errors"] > 0)
        scan_failed = summary["scan_status"] in (
            "SCAN_ERROR", "SCROLL_STALLED", "MAX_SCAN_ROUNDS")
        # Some uploads may succeed even if the scanner stalls. Still report
        # a failing run: the user's historical library is NOT fully covered.
        return 2 if all_failed or scan_failed else 0
    finally:
        try:
            job.engine.db.c.close()
        finally:
            shutil.rmtree(job.engine.wd, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
