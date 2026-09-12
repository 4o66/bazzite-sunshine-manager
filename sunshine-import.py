#!/usr/bin/env python3
"""
Bazzite Sunshine Manager

Author: wadiebs
Date: January 2026
Version: 2.0

Description:
Automated importer and manager for Sunshine streaming app configurations.
This tool recreates Sunshine's apps.json with proper structure and organization.

Features:
- Automatic detection of Sunshine configuration directory (Flatpak + native)
- Imports applications from multiple sources (Steam, Heroic Launcher, custom launchers)
- Maintains proper JSON structure with "env" section first, followed by "apps"
- Comprehensive environment variable and application mapping
- Blacklist support for filtering unwanted applications
- Modular architecture for easy extension of import sources
- Support for poster/thumbnail artwork organization
"""

import sys
import os
import time
import shutil
import pathlib
from pathlib import Path
from typing import Dict, Any

# Safe to import local modules now
from common.utils import log, write_json  # noqa: E402
from importers.steam import import_steam  # noqa: E402
from importers.heroic import import_heroic  # noqa: E402
from importers.launchers import import_launchers

# Files Sunshine itself writes while running. Their mtime is what distinguishes a
# config directory in use from one an uninstalled Flatpak left behind.
_LIVENESS_FILES = ("sunshine.log", "sunshine_state.json", "sunshine.conf")


def _config_dir_candidates(home: str) -> list[str]:
    flatpak_ids = ["dev.lizardbyte.app.Sunshine", "dev.lizardbyte.Sunshine"]
    cands = [os.path.join(home, ".var", "app", fid, "config", "sunshine") for fid in flatpak_ids]
    cands.append(os.path.join(home, ".config", "sunshine"))
    return cands


def _last_used(conf_dir: str) -> float:
    """Most recent mtime among Sunshine's own runtime files, or 0.0 if none."""
    newest = 0.0
    for name in _LIVENESS_FILES:
        try:
            newest = max(newest, os.path.getmtime(os.path.join(conf_dir, name)))
        except OSError:
            continue
    return newest


def detect_sunshine_config_dir(home: str) -> str:
    """Detect Sunshine config directory (Flatpak + native).

    SUNSHINE_CONF_DIR overrides everything. Otherwise, when more than one
    candidate exists, pick the one Sunshine used most recently rather than the
    first that happens to exist: an uninstalled Flatpak leaves its whole config
    tree behind, and writing to it silently does nothing.
    """
    override = os.getenv("SUNSHINE_CONF_DIR", "").strip()
    if override:
        return os.path.abspath(os.path.expanduser(os.path.expandvars(override)))

    existing = [d for d in _config_dir_candidates(home) if os.path.isdir(d)]
    if not existing:
        return os.path.join(home, ".config", "sunshine")
    if len(existing) == 1:
        return existing[0]

    ranked = sorted(existing, key=_last_used, reverse=True)
    chosen = ranked[0]
    log("Multiple Sunshine config directories found; choosing the most recently used:")
    for d in ranked:
        stamp = _last_used(d)
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(stamp)) if stamp else "never used"
        log(f"  {'->' if d == chosen else '  '} {d}  ({when})")
    log("Set SUNSHINE_CONF_DIR (or --conf-dir) to override.")
    return chosen


def getenv_flag(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def main(argv: list[str]) -> int:
    home = str(Path.home())
    conf_dir = detect_sunshine_config_dir(home)
    os.makedirs(conf_dir, exist_ok=True)

    # Paths
    apps_json = os.path.join(conf_dir, "apps.json")
    images_root = os.path.join(conf_dir, "images")
    images_dir_steam = os.path.join(images_root, "steam")
    images_dir_heroic = os.path.join(images_root, "heroic")
    images_dir_sideload = os.path.join(images_root, "sideload")
    for d in (images_dir_steam, images_dir_heroic, images_dir_sideload):
        os.makedirs(d, exist_ok=True)

    log(f"Sunshine config: {conf_dir}")
    log(f"Images root:     {images_root}")

    # Fresh file each run: keep a backup for troubleshooting
    if os.path.exists(apps_json):
        try:
            shutil.copy2(apps_json, f"{apps_json}.bak")
            log(f"Backup saved: {apps_json}.bak")
        except Exception as e:
            log(f"Warning: failed to backup apps.json: {e}")

    # Read toggles from environment
    IMPORT_STEAM = getenv_flag("IMPORT_STEAM", True)
    IMPORT_HEROIC = getenv_flag("IMPORT_HEROIC", True)

    enabled_importers = []
    if IMPORT_STEAM:
        enabled_importers.append("steam")
    if IMPORT_HEROIC:
        enabled_importers.append("heroic")

    settings: Dict[str, Any] = dict(os.environ)

    # Collect apps from enabled importers
    apps = []
    if IMPORT_STEAM:
        apps += import_steam(home, conf_dir, images_dir_steam, settings)
    else:
        log("Steam importer disabled.")
    if IMPORT_HEROIC:
        apps += import_heroic(home, conf_dir, images_dir_heroic, settings)
    else:
        log("Heroic importer disabled.")

    apps += import_launchers(home, conf_dir, os.path.join(conf_dir, "images", "launchers"), settings)

    # --- ENV BLOCK FIRST ---
    # Default PATH augmentation as requested; allow optional extra append via ENV_PATH_APPEND.
    env_block = {
        "PATH": "$(PATH):$(HOME)/.local/bin" + ((":" + os.getenv("ENV_PATH_APPEND")) if os.getenv("ENV_PATH_APPEND") else "")
    }

    # Fresh write: "env" then "apps" (then meta for visibility)
    payload = {
        "env": env_block,
        "apps": apps,
        "meta": {
            "generated-by": "bazzite-sunshine-manager",
            "enabled-importers": enabled_importers,
        },
    }
    write_json(apps_json, payload)
    log(f"Wrote {len(apps)} apps. Enabled importers: {', '.join(enabled_importers) or 'none'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
