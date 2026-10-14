"""Resumable historical Google Photos -> Koofr backfill.

Independent of the daily browser-grid scanner. Navigates one photo at a time in
the viewer (Right arrow: older), saves Chrome's actual download, and keeps a
separate durable cursor. It never deletes files or advances the daily cursor.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

from src.gphotos_sync import Engine, SEL, cmd, created, href, ident, now, savej, sha


def media_url(url):
    if not url.startswith("https://photos.google.com/"):
        raise ValueError("Unexpected Google Photos URL")
    return ident(url)[0]


def capture_date(path, filename, label):
    """Use file EXIF when present; otherwise a conservative filename date."""
    parsed = created(label)
    if parsed:
        return parsed
    try:
        from PIL import Image
        with Image.open(path) as picture:
            exif = picture.getexif()
            value = exif.get(36867) or exif.get(306)
            if value:
                return datetime.strptime(str(value)[:19], "%Y:%m:%d %H:%M:%S").isoformat(timespec="seconds")
    except (ImportError, OSError, ValueError, TypeError):
        pass
    match = re.search(r"(?<!\d)(20\d{2})[-_]?([01]\d)[-_]?([0-3]\d)(?!\d)", filename)
    if match:
        try:
            return datetime(*map(int, match.groups())).isoformat(timespec="seconds")
        except ValueError:
            pass
    return None


class Backfill:
    def __init__(self, args):
        self.engine = Engine(args)
        self.args = args
        self.state_path = self.engine.sd / "backfill-checkpoint.json"
        # A missing checkpoint is normal on first deployment.
        result = cmd("rclone", "copyto",
                     f"{args.sroot}/backfill-checkpoint.json", str(self.state_path),
                     ok=False, cap=True)
        if result.returncode:
            self.state_path.unlink(missing_ok=True)
        self.cursor = self.engine.load("backfill-checkpoint.json",
                                       {"version": 1, "last_id": None, "last_url": None})
        self.stats = self.engine.stats
        self.visited = set()
        self.since_save = 0

    def persist(self, status):
        self.cursor.update({"status": status, "updated_at": now(),
                            "last_run_stats": dict(self.stats)})
        self.engine.flush()  # manifest first, then cursor: never skip unsaved entries
        savej(self.state_path, self.cursor)
        cmd("rclone", "copyto", str(self.state_path),
            f"{self.args.sroot}/backfill-checkpoint.json", "--ignore-times")
        self.since_save = 0
        print(f"BACKFILL_CHECKPOINT status={status} last_id={self.cursor.get('last_id')}",
              flush=True)

    def open_media(self, page, url):
        media_url(url)
        page.goto(url, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(900)
        actual = page.url
        media_url(actual)
        return actual

    def older(self, page, current_id):
        """Do not claim completion if the gallery viewer fails to navigate."""
        for retry in range(2):
            page.keyboard.press("ArrowRight")
            try:
                page.wait_for_url(
                    lambda url: (
                        str(url).startswith("https://photos.google.com/")
                        and re.search(r"/(?:photo|video)/([^/?#]+)", str(url)) is not None
                        and media_url(str(url)) != current_id
                    ),
                    timeout=6500)
                return page.url
            except PlaywrightTimeout:
                if retry == 0:
                    page.wait_for_timeout(650)
        return None

    def download(self, page, media_id):
        """Avoid the extra authenticated HTTP replay used by the old engine."""
        with page.expect_download(timeout=75000) as event:
            page.keyboard.press("Shift+D")
        download = event.value
        filename = Path(download.suggested_filename).name[:180]
        if not filename or filename in (".", ".."):
            raise RuntimeError("Invalid downloaded filename")
        dest = self.engine.wd / f"{media_id}__{filename}"
        download.save_as(dest)
        if dest.stat().st_size < 1:
            dest.unlink(missing_ok=True)
            raise RuntimeError("Empty browser download")
        return dest, filename

    def process(self, page, media_id, media_type, url, label=None, capture=None):
        e = self.engine
        e.db.touch(media_id, media_type, url, label, capture)
        self.stats["discovered"] += 1
        if e.db.uploaded(media_id):
            self.stats["skipped"] += 1
            return
        if self.stats["attempted"] >= self.args.maxitems:
            return
        self.stats["attempted"] += 1
        local = None
        try:
            for attempt in range(2):
                try:
                    local, filename = self.download(page, media_id)
                    break
                except Exception as exc:
                    if attempt or e.left() < 210:
                        raise
                    print(f"BACKFILL_DOWNLOAD_RETRY id={media_id} error={str(exc)[:180]}",
                          flush=True)
                    page.reload(wait_until="domcontentloaded", timeout=90000)
                    page.wait_for_timeout(1200)
            size = local.stat().st_size
            digest = sha(local)
            date = capture or capture_date(local, filename, label)
            remote, reused = e.remote(date, filename, media_id, digest, size)
            if not reused:
                # Keep already-backed-up bytes immutable even after an interrupted
                # run: remote() may propose an existing media-ID collision path.
                existing = cmd("rclone", "lsl", remote, ok=False, cap=True)
                if existing.returncode == 0 and existing.stdout.strip():
                    prior = e.wd / f"{media_id}__preexisting-koofr"
                    try:
                        cmd("rclone", "copyto", remote, str(prior))
                        if sha(prior) == digest:
                            reused = True
                        else:
                            raise RuntimeError("Refusing to overwrite different Koofr content")
                    finally:
                        prior.unlink(missing_ok=True)
                if not reused:
                    cmd("rclone", "copyto", str(local), remote,
                        "--ignore-times", "--retries", "3")
            listing = cmd("rclone", "lsl", remote, cap=True).stdout.strip()
            remote_size = int(listing.split()[0]) if listing else -1
            if remote_size != size:
                raise RuntimeError(f"Koofr size mismatch: {size}!={remote_size}")
            e.db.done(media_id, filename, size, digest, remote)
            self.stats["uploaded"] += 1
            print(f"BACKFILL_UPLOAD_OK id={media_id} size={size} reused={reused}", flush=True)
        except Exception as exc:
            e.db.err(media_id, exc)
            self.stats["errors"] += 1
            print(f"BACKFILL_UPLOAD_ERROR id={media_id} error={str(exc)[:250]}",
                  file=sys.stderr, flush=True)
        finally:
            if local:
                local.unlink(missing_ok=True)

    def retry_known_errors(self, page):
        # Bounded retry pool: hard failures cannot monopolize the backfill.
        rows = self.engine.db.c.execute(
            "SELECT id,type,url,label,created FROM media WHERE status='error' "
            "ORDER BY last_seen ASC LIMIT 3").fetchall()
        for media_id, kind, url, label, capture in rows:
            if self.engine.left() < 240 or self.stats["attempted"] >= self.args.maxitems:
                break
            try:
                self.open_media(page, url)
                self.process(page, media_id, kind, url, label, capture)
            except Exception as exc:
                self.stats["errors"] += 1
                print(f"BACKFILL_RETRY_OPEN_ERROR id={media_id} error={str(exc)[:200]}",
                      file=sys.stderr, flush=True)

    def _crawl(self, page):
        """Walk history only. Previously failed media are not allowed to kill the crawl."""
        e = self.engine
        if self.cursor.get("last_url"):
            self.open_media(page, self.cursor["last_url"])
            url = self.older(page, self.cursor["last_id"])
            if not url:
                return "NAVIGATION_STALLED"
        else:
            page.goto("https://photos.google.com/",
                      wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(4000)
            tiles = page.locator(SEL)
            if tiles.count() == 0:
                raise RuntimeError("Google Photos session unavailable or empty gallery")
            first = tiles.nth(0)
            raw = first.get_attribute("href")
            if not raw:
                raise RuntimeError("First photo has no link")
            url = self.open_media(page, href(raw))

        while url and e.left() > 240 and self.stats["attempted"] < self.args.maxitems:
            current = (self.open_media(page, url)
                       if media_url(page.url) != media_url(url) else page.url)
            item, kind = ident(current)
            if item in self.visited:
                return "NAVIGATION_LOOP"
            self.visited.add(item)
            self.process(page, item, kind, current)
            # Advance after processing. Errors stay in manifest and are retryable.
            # The durable cursor is committed after the manifest, not before.
            self.cursor["last_id"] = item
            self.cursor["last_url"] = current
            self.cursor["visited_total"] = self.cursor.get("visited_total", 0) + 1
            self.since_save += 1
            if self.since_save >= 10:
                self.persist("RUNNING")
            if self.stats["attempted"] >= self.args.maxitems:
                return "PAUSED_LIMIT"
            if e.left() <= 240:
                return "PAUSED_TIME"
            url = self.older(page, item)
            if not url:
                return "NAVIGATION_STALLED"
        return "PAUSED_TIME" if e.left() <= 240 else "PAUSED_LIMIT"

    def run(self):
        e = self.engine
        status = "FAILED"
        try:
            with sync_playwright() as playwright:
                for restart in range(4):
                    if e.left() <= 240:
                        status = "PAUSED_TIME"
                        break
                    browser = None
                    try:
                        print(f"BACKFILL_BROWSER_START attempt={restart + 1}", flush=True)
                        browser = playwright.chromium.launch_persistent_context(
                            user_data_dir=self.args.profile,
                            executable_path=self.args.chrome,
                            headless=True, accept_downloads=True,
                            args=["--disable-dev-shm-usage", "--no-first-run"])
                        page = browser.pages[0] if browser.pages else browser.new_page()
                        status = self._crawl(page)
                        break
                    except Exception as exc:
                        closed = ("target page, context or browser has been closed"
                                  in str(exc).lower()
                                  or "browser has been closed" in str(exc).lower())
                        if not closed:
                            raise
                        # Chrome can close on specific photos. Preserve the current
                        # manifest/cursor, then reopen the saved profile to continue.
                        print(f"BACKFILL_BROWSER_CLOSED attempt={restart + 1} "
                              f"error={str(exc)[:220]}", file=sys.stderr, flush=True)
                        self.persist("BROWSER_RESTART")
                        if restart == 3:
                            status = "FAILED_BROWSER_RESTARTS"
                    finally:
                        if browser is not None:
                            try:
                                browser.close()
                            except Exception:
                                pass
            self.persist(status)
        except Exception:
            # Still write the safely completed prefix for the next run.
            self.persist("FAILED")
            raise
        pending = e.db.c.execute(
            "SELECT COUNT(*) FROM media WHERE status='error'").fetchone()[0]
        total = e.db.c.execute(
            "SELECT COUNT(*) FROM media WHERE status='uploaded'").fetchone()[0]
        return {"status": status, **self.stats, "manifest_uploaded_total": total,
                "pending_errors": pending, "backfill_cursor": self.cursor.get("last_id"),
                "backfill_visited_total": self.cursor.get("visited_total", 0)}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default=os.path.expanduser("~/gphotos-profile"))
    parser.add_argument("--chrome", default=os.environ.get("CHROME_BIN", "/usr/bin/google-chrome-stable"))
    parser.add_argument("--state", default="/tmp/gphotos-state")
    parser.add_argument("--work", default="/tmp/gphotos-downloads")
    parser.add_argument("--root", default="koofr_remote:/Google Photos/Photos")
    parser.add_argument("--sroot", default="koofr_remote:/Google Photos/.gphotos-sync")
    parser.add_argument("--seconds", type=int, default=int(os.environ.get("MAX_RUNTIME_SECONDS", "12000")))
    parser.add_argument("--maxitems", type=int, default=int(os.environ.get("MAX_ITEMS", "100")))
    args = parser.parse_args()
    backfill = Backfill(args)
    try:
        result = backfill.run()
        print("BACKFILL_SUMMARY=" + json.dumps(result, ensure_ascii=False), flush=True)
        good_pause = result["status"] in ("PAUSED_LIMIT", "PAUSED_TIME")
        all_failed = result["attempted"] > 0 and result["uploaded"] == 0 and result["errors"] > 0
        return 0 if good_pause and not all_failed else 2
    finally:
        try:
            backfill.engine.db.c.close()
        finally:
            import shutil
            shutil.rmtree(backfill.engine.wd, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
