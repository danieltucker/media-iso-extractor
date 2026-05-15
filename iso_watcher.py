#!/usr/bin/env python3
"""
ISO auto-extractor for TrueNAS SCALE media servers.

Watches configured directories for .iso files, extracts the main video title
using makemkvcon, triggers library rescans in Sonarr/Radarr/Plex, then deletes
the ISO. Sends a Telegram alert on failure.
"""

import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests
import yaml
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

_processing: set[str] = set()


def load_config(path: str = "/config/config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# File stability — wait until the ISO is fully written before touching it
# ---------------------------------------------------------------------------

def wait_for_stable(path: str, cfg: dict) -> bool:
    poll = cfg.get("stability_poll_interval", 5)
    wait = cfg.get("stability_wait_seconds", 30)
    deadline = time.time() + wait * 6  # don't wait forever

    prev_size = -1
    stable_since = None

    while time.time() < deadline:
        try:
            size = os.path.getsize(path)
        except OSError:
            return False

        if size == prev_size:
            if stable_since is None:
                stable_since = time.time()
            elif time.time() - stable_since >= wait:
                return True
        else:
            stable_since = None

        prev_size = size
        time.sleep(poll)

    log.warning("Stability timeout for %s — file may still be writing", path)
    return False


# ---------------------------------------------------------------------------
# makemkvcon extraction
# ---------------------------------------------------------------------------

def find_main_title(iso_path: str, min_seconds: int) -> int | None:
    """
    Run makemkvcon info to find the longest title that meets the minimum
    duration threshold. Returns the title index or None if nothing qualifies.
    """
    result = subprocess.run(
        ["makemkvcon", "-r", "info", f"iso:{iso_path}"],
        capture_output=True,
        text=True,
    )

    best_index = None
    best_duration = 0

    # TINFO lines look like: TINFO:0,9,0,"1:23:45"
    for line in result.stdout.splitlines():
        m = re.match(r'TINFO:(\d+),9,0,"(\d+):(\d+):(\d+)"', line)
        if m:
            idx = int(m.group(1))
            seconds = int(m.group(2)) * 3600 + int(m.group(3)) * 60 + int(m.group(4))
            if seconds >= min_seconds and seconds > best_duration:
                best_duration = seconds
                best_index = idx

    return best_index


def extract_iso(iso_path: str, cfg: dict) -> list[Path]:
    """
    Extract the main title from the ISO into the same directory.
    Returns a list of output MKV paths on success, raises on failure.
    """
    iso = Path(iso_path)
    output_dir = iso.parent

    makemkv_cfg = cfg.get("makemkv", {})
    license_key = makemkv_cfg.get("license_key", "")
    min_seconds = makemkv_cfg.get("min_title_seconds", 1800)

    title_index = find_main_title(iso_path, min_seconds)
    if title_index is None:
        # Fall back to title 0 if nothing met the threshold (e.g. short content)
        log.warning("No title met minimum duration for %s, falling back to title 0", iso_path)
        title_index = 0

    cmd = ["makemkvcon"]
    if license_key:
        cmd += [f"--noscan", f"-r"]
    cmd += ["mkv", f"iso:{iso_path}", str(title_index), str(output_dir)]

    log.info("Extracting title %d from %s → %s", title_index, iso_path, output_dir)
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(
            f"makemkvcon exited {result.returncode}:\n{result.stderr or result.stdout}"
        )

    # Collect any MKV files newer than the ISO that appeared in the directory
    iso_mtime = iso.stat().st_mtime
    new_files = [
        p for p in output_dir.glob("*.mkv")
        if p.stat().st_mtime >= iso_mtime
    ]

    if not new_files:
        raise RuntimeError("makemkvcon reported success but no MKV files were created")

    return new_files


# ---------------------------------------------------------------------------
# API integrations
# ---------------------------------------------------------------------------

def _post_command(url: str, api_key: str, body: dict, service: str) -> None:
    try:
        resp = requests.post(
            f"{url}/api/v3/command",
            json=body,
            headers={"X-Api-Key": api_key},
            timeout=10,
        )
        resp.raise_for_status()
        log.info("%s rescan triggered", service)
    except Exception as e:
        log.warning("Failed to trigger %s rescan: %s", service, e)


def trigger_sonarr_rescan(path: str, cfg: dict) -> None:
    c = cfg.get("sonarr", {})
    if not c.get("api_key"):
        return
    _post_command(
        c["url"],
        c["api_key"],
        {"name": "DownloadedEpisodesScan", "path": str(Path(path).parent)},
        "Sonarr",
    )


def trigger_radarr_rescan(path: str, cfg: dict) -> None:
    c = cfg.get("radarr", {})
    if not c.get("api_key"):
        return
    _post_command(
        c["url"],
        c["api_key"],
        {"name": "DownloadedMoviesScan", "path": str(Path(path).parent)},
        "Radarr",
    )


def trigger_plex_scan(cfg: dict) -> None:
    c = cfg.get("plex", {})
    if not c.get("token"):
        return
    try:
        # Refresh all libraries — targeted refresh requires knowing the section ID
        resp = requests.get(
            f"{c['url']}/library/sections/all/refresh",
            headers={"X-Plex-Token": c["token"]},
            timeout=10,
        )
        resp.raise_for_status()
        log.info("Plex library refresh triggered")
    except Exception as e:
        log.warning("Failed to trigger Plex scan: %s", e)


def send_telegram(message: str, cfg: dict) -> None:
    c = cfg.get("telegram", {})
    if not c.get("bot_token") or not c.get("chat_id"):
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{c['bot_token']}/sendMessage",
            json={"chat_id": c["chat_id"], "text": message, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        log.warning("Telegram notification failed: %s", e)


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------

def process_iso(iso_path: str, cfg: dict) -> None:
    if iso_path in _processing:
        return
    _processing.add(iso_path)

    log.info("ISO detected: %s", iso_path)

    try:
        if not wait_for_stable(iso_path, cfg):
            raise RuntimeError("File did not stabilise — skipping")

        extracted = extract_iso(iso_path, cfg)
        log.info("Extracted: %s", [str(p) for p in extracted])

        os.remove(iso_path)
        log.info("Deleted ISO: %s", iso_path)

        trigger_sonarr_rescan(iso_path, cfg)
        trigger_radarr_rescan(iso_path, cfg)
        trigger_plex_scan(cfg)

    except Exception as e:
        log.error("Failed to process %s: %s", iso_path, e)
        send_telegram(
            f"<b>ISO Extractor — Failure</b>\n"
            f"<code>{Path(iso_path).name}</code>\n\n"
            f"{e}",
            cfg,
        )
    finally:
        _processing.discard(iso_path)


# ---------------------------------------------------------------------------
# File system watcher
# ---------------------------------------------------------------------------

class ISOHandler(FileSystemEventHandler):
    def __init__(self, cfg: dict):
        self.cfg = cfg

    def on_created(self, event):
        if not event.is_directory and event.src_path.lower().endswith(".iso"):
            process_iso(event.src_path, self.cfg)

    # Also catch moves/renames into the watched directory
    def on_moved(self, event):
        if not event.is_directory and event.dest_path.lower().endswith(".iso"):
            process_iso(event.dest_path, self.cfg)


def main() -> None:
    config_path = os.environ.get("CONFIG_PATH", "/config/config.yaml")
    cfg = load_config(config_path)

    watch_dirs = cfg.get("watch_dirs", [])
    if not watch_dirs:
        log.error("No watch_dirs configured — exiting")
        sys.exit(1)

    observer = Observer()
    handler = ISOHandler(cfg)

    for directory in watch_dirs:
        if not os.path.isdir(directory):
            log.warning("Watch directory does not exist, skipping: %s", directory)
            continue
        observer.schedule(handler, directory, recursive=True)
        log.info("Watching: %s", directory)

    observer.start()
    log.info("ISO watcher running")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()

    observer.join()


if __name__ == "__main__":
    main()
