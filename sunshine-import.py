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
import shutil
import pathlib
from pathlib import Path
from typing import Dict, Any

# Safe to import local modules now
from common.utils import log, write_json  # noqa: E402
from common.sunshine_api import reload_sunshine  # noqa: E402
from importers.steam import import_steam  # noqa: E402
from importers.heroic import import_heroic  # noqa: E402
from importers.launchers import import_launchers

def detect_sunshine_config_dir(home: str) -> str:
    """Detect Sunshine config directory (Flatpak + native)."""
    flatpak_ids = ["dev.lizardbyte.app.Sunshine", "dev.lizardbyte.Sunshine"]
    for fid in flatpak_ids:
        fp_dir = os.path.join(home, ".var", "app", fid, "config", "sunshine")
        if os.path.isdir(fp_dir):
            return fp_dir
    return os.path.join(home, ".config", "sunshine")


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

    # Sunshine has no file watcher, so the file we just wrote is invisible to it
    # until it re-reads. Ask it to, rather than restarting and dropping whatever
    # stream is in progress.
    if getenv_flag("BSM_RELOAD", False):
        reload_sunshine(conf_dir)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
