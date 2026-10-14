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
  const root = document.scrollingElement || document.documentElement;
  let target = root;
  let best = Math.max(0, root.scrollHeight - root.clientHeight);
  for (const el of document.querySelectorAll('div, main, section')) {
    const extra = el.scrollHeight - el.clientHeight;
    if (extra <= best || extra < 100) continue;
    const style = getComputedStyle(el);
    if (!/(auto|scroll|overlay)/.test(style.overflowY)) continue;
    target = el;
    best = extra;
  }
  const before = target.scrollTop;
  const step = Math.max(750, Math.round(target.clientHeight * 0.78));
  target.scrollTop = Math.min(best, before + step);
  return {before: before, after: target.scrollTop, max: best,
          tag: target.tagName, step: step};
}"""

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
            page.goto("https://photos.google.com/", wait_until="domcontentloaded",
                      timeout=90000)
            page.wait_for_timeout(4000)
            seen_rounds = 0
            stuck_rounds = 0
            old_count = 0
            target = max(self.args.maxitems + 15, 25)
            for turn in range(1500):
                if e.left() < 360:
                    self.scan_status = "TIME_BUDGET_LOW"
                    break
                self.scan_rounds += 1
                raw = page.locator(SEL).evaluate_all(VISIBLE_JS)
                items = parse_tiles(raw)
                new_this_round = 0
                for media_id, media_type, url, label, capture in items:
                    if media_id in self.scanned_unique:
                        continue
                    self.scanned_unique.add(media_id)
                    self.anchor_id = media_id
                    self.stats["discovered"] += 1
                    prior = e.db.c.execute(
                        "SELECT status FROM media WHERE id=?", (media_id,)).fetchone()
                    e.db.touch(media_id, media_type, url, label, capture)
                    if not prior or prior[0] == "seen":
                        self.pending[media_id] = (media_id, media_type, url, label, capture)
                        new_this_round += 1
                    elif prior[0] == "uploaded":
                        old_count += 1
                    # Previously failed images are retried after fresh historical media.
                if len(self.pending) >= target:
                    self.scan_status = "BATCH_READY"
                    break
                scroll = page.evaluate(SCROLL_JS)
                if scroll["after"] <= scroll["before"] + 1:
                    # A mouse wheel also notifies virtualized React scroll handlers.
                    page.mouse.wheel(0, 1250)
                    stuck_rounds += 1
                else:
                    stuck_rounds = 0
                seen_rounds = seen_rounds + 1 if new_this_round == 0 else 0
                if turn % 10 == 0 or new_this_round > 0:
                    print(f"GRID_SCAN round={turn + 1} visible={len(items)} "
                          f"seen={len(self.scanned_unique)} pending={len(self.pending)} "
                          f"old={old_count} moved={scroll['after'] - scroll['before']:.0f} "
                          f"max_scroll={scroll['max']:.0f}", flush=True)
                if stuck_rounds >= 5 and seen_rounds >= 5:
                    # Not proof that the Google Photos library has been fully scanned.
                    self.scan_status = "SCROLL_END_OR_STALLED"
                    break
                page.wait_for_timeout(500 if new_this_round else 750)
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
        # Include at most two old errors only when there is spare capacity.
        if len(candidates) < budget:
            for row in self.engine.db.c.execute(
                "SELECT id,type,url,label,created FROM media "
                "WHERE status='error' ORDER BY last_seen ASC LIMIT 2"):
                if row[0] not in wanted:
                    candidates.append(row)
                    wanted.add(row[0])
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
        no_progress = summary["attempted"] == 0 and (
            summary["scan_status"] == "SCAN_ERROR" or
            summary["scan_status"] == "SCROLL_END_OR_STALLED")
        return 2 if all_failed or no_progress else 0
    finally:
        try:
            job.engine.db.c.close()
        finally:
            shutil.rmtree(job.engine.wd, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
