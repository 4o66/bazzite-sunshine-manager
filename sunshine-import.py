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

import json
import sys
import os
import re
import time
import shutil
import pathlib
from pathlib import Path
from typing import Dict, Any

VERSION = "2.0"

# Safe to import local modules now
from common.utils import log, read_json, write_json  # noqa: E402
from common.reconcile import (MARKER, SCHEMA_VERSION, backup, log_plan,  # noqa: E402
                              plan_document, reconcile)
from common.system_apps import (find_system_apps_json, load_system_apps,  # noqa: E402
                                restore_missing)
from common.sunshine_api import (SunshineAPIError, reload_sunshine,  # noqa: E402
                                 save_credentials, verify_credentials)
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


def _selectors(env_name: str) -> list:
    """Parse a comma/space separated list of <source>:<id> selectors."""
    return [t for t in re.split(r"[,\s]+", os.getenv(env_name, "").strip()) if t]


def getenv_flag(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def _auth_result(ok: bool, message: str, as_json: bool) -> int:
    if as_json:
        json.dump({"ok": ok, "message": message}, sys.stdout)
        sys.stdout.write("\n")
    log(message)
    return 0 if ok else 1


def dump_state(conf_dir: str, as_json: bool) -> int:
    """Emit what is in apps.json right now, for a front end to render.

    Distinct from the plan: the plan says what *would* change, this says what
    *is*. A manager needs both, and reading apps.json in two places would mean
    two implementations of the marker and tombstone conventions.
    """
    apps_json = os.path.join(conf_dir, "apps.json")
    payload = read_json(apps_json, {})
    if not isinstance(payload, dict):
        payload = {"apps": payload if isinstance(payload, list) else []}
    apps = payload.get("apps")
    apps = apps if isinstance(apps, list) else []
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}

    entries = []
    for index, app in enumerate(apps):
        if not isinstance(app, dict):
            continue
        marker = app.get(MARKER) if isinstance(app.get(MARKER), dict) else None
        entries.append({
            "index": index,
            "name": app.get("name"),
            "image-path": app.get("image-path") or "",
            "cmd": app.get("cmd") or "",
            "source": marker.get("source") if marker else None,
            "id": marker.get("id") if marker else None,
            "managed": marker is not None,
        })

    doc = {
        "schema": SCHEMA_VERSION,
        "generator": {"name": "bazzite-sunshine-manager", "version": VERSION},
        "config_dir": conf_dir,
        "apps_json": apps_json,
        "apps": entries,
        "hidden": [t for t in (meta.get("removed") or []) if isinstance(t, dict)],
    }
    if as_json:
        json.dump(doc, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        log(f"{len(entries)} apps, {len(doc['hidden'])} hidden")
    return 0


def check_auth(conf_dir: str, as_json: bool) -> int:
    """Are stored credentials present and accepted by Sunshine?"""
    try:
        from common.sunshine_api import SunshineClient, load_credentials
        user, password = load_credentials(conf_dir)
        verify_credentials(conf_dir, user, password)
        return _auth_result(True, f"Sunshine accepted the stored credentials for {user!r}.", as_json)
    except SunshineAPIError as e:
        return _auth_result(False, str(e), as_json)


def save_auth(conf_dir: str, as_json: bool) -> int:
    """Read username and password as two lines on stdin, verify, store.

    stdin rather than arguments: argv is visible in ps and lands in shell
    history, and a password is exactly the thing that must not be there.
    """
    data = sys.stdin.read().splitlines()
    user = data[0].strip() if len(data) > 0 else ""
    password = data[1] if len(data) > 1 else ""
    try:
        path = save_credentials(conf_dir, user, password)
        return _auth_result(True, f"Verified and saved to {path}", as_json)
    except SunshineAPIError as e:
        return _auth_result(False, str(e), as_json)


def main(argv: list[str]) -> int:
    dry_run = getenv_flag("BSM_DRY_RUN", False)
    as_json = getenv_flag("BSM_JSON", False)
    home = str(Path.home())
    conf_dir = detect_sunshine_config_dir(home)
    os.makedirs(conf_dir, exist_ok=True)

    # Credential modes exit before any scanning or writing happens.
    if getenv_flag("BSM_STATE", False):
        return dump_state(conf_dir, as_json)
    if getenv_flag("BSM_CHECK_AUTH", False):
        return check_auth(conf_dir, as_json)
    if getenv_flag("BSM_SAVE_AUTH", False):
        return save_auth(conf_dir, as_json)

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

    # Load what is already there. Entries we did not generate are preserved.
    payload = read_json(apps_json, {})
    if not isinstance(payload, dict):
        payload = {"apps": payload if isinstance(payload, list) else []}
    existing_apps = payload.get("apps")
    if not isinstance(existing_apps, list):
        existing_apps = []

    # Files written by older versions of this tool have no ownership markers, but
    # were a wholesale rewrite, so every entry in them is ours. Adopt by name.
    meta = payload.get("meta")
    adopt_by_name = (
        isinstance(meta, dict)
        and meta.get("generated-by") == "bazzite-sunshine-manager"
        and not any(isinstance(a, dict) and MARKER in a for a in existing_apps)
    )
    if adopt_by_name:
        log("Existing apps.json was generated by an older version; adopting entries by name.")

    refresh = _selectors("BSM_REFRESH_EDITED")
    if refresh:
        log(f"Refreshing user-edited fields for: {', '.join(refresh)}")

    # Sunshine's own defaults. Seed a fresh config from them, and put them back
    # on request if an older version of this tool rewrote them away.
    include_system = getenv_flag("INCLUDE_SYSTEM_APPS", True)
    restore_defaults = getenv_flag("BSM_RESTORE_DEFAULTS", False)
    system_apps: list = []
    if include_system:
        system_path = find_system_apps_json(os.getenv("SYSTEM_APPS_JSON", "").strip())
        if system_path:
            system_apps = load_system_apps(system_path)
            log(f"Sunshine defaults: {len(system_apps)} entries from {system_path}")
        else:
            log("Sunshine defaults: shipped apps.json not found; skipping.")

    if system_apps and not existing_apps:
        existing_apps = [dict(a) for a in system_apps]
        log(f"Fresh config: seeded with {len(existing_apps)} Sunshine default entries.")
    elif system_apps and restore_defaults:
        existing_apps, restored = restore_missing(existing_apps, system_apps)
        if restored:
            log(f"Restored Sunshine defaults: {', '.join(restored)}")
        else:
            log("Restore defaults: all default entries already present.")
    restore_removed = _selectors("BSM_RESTORE_REMOVED")
    prune = getenv_flag("BSM_REMOVE_UNINSTALLED", False)
    allow_empty_prune = getenv_flag("BSM_ALLOW_EMPTY_PRUNE", False)

    # What we wrote last run, and what the user has deleted since. Both live in
    # the "meta" block of apps.json, which Sunshine preserves: saveApp() and
    # deleteApp() only ever rewrite file_tree["apps"].
    prior = meta if isinstance(meta, dict) else {}
    previously_managed = prior.get("managed") if isinstance(prior.get("managed"), list) else []
    tombstones = prior.get("removed") if isinstance(prior.get("removed"), list) else []

    # Read toggles from environment
    IMPORT_STEAM = getenv_flag("IMPORT_STEAM", True)
    IMPORT_HEROIC = getenv_flag("IMPORT_HEROIC", True)

    enabled_importers = []
    if IMPORT_STEAM:
        enabled_importers.append("steam")
    if IMPORT_HEROIC:
        enabled_importers.append("heroic")

    settings: Dict[str, Any] = dict(os.environ)

    # Collect apps from enabled importers, recording how each one fared. A source
    # that raised is not the same as a source that found nothing, and consumers
    # need to tell them apart before acting on "missing" entries.
    apps: list = []
    sources: list = []

    def run_source(name: str, enabled: bool, fn):
        report: Dict[str, Any] = {"name": name, "enabled": enabled,
                                  "status": "disabled", "imported": 0}
        sources.append(report)
        if not enabled:
            log(f"{name.capitalize()} importer disabled.")
            return
        try:
            found = fn(report) or []
        except Exception as e:                       # noqa: BLE001 - reported, not swallowed
            log(f"{name.capitalize()} importer failed: {e}")
            report["status"] = "error"
            report["error"] = str(e)
            return
        apps.extend(found)
        report["imported"] = len(found)

    run_source("steam", IMPORT_STEAM,
               lambda r: import_steam(home, conf_dir, images_dir_steam, settings, r))
    run_source("heroic", IMPORT_HEROIC,
               lambda r: import_heroic(home, conf_dir, images_dir_heroic, settings, r))
    run_source("launcher", True,
               lambda r: import_launchers(home, conf_dir,
                                          os.path.join(conf_dir, "images", "launchers"),
                                          settings, r))

    # Only a source that actually read its library may have entries pruned. A
    # source that could not be found looks exactly like one whose games were all
    # uninstalled, and acting on that deletes a library that is merely offline.
    prunable: list = []
    if prune:
        for report in sources:
            name, status = report["name"], report.get("status")
            if status != "ok":
                log(f"Not removing {name} entries: scan status is {status!r}, "
                    f"which does not prove anything was uninstalled.")
            elif not report.get("imported") and not allow_empty_prune:
                log(f"Not removing {name} entries: it scanned cleanly but returned "
                    f"nothing, which usually means a library is offline or mid-update. "
                    f"Pass --allow-empty-prune if everything really was uninstalled.")
            else:
                prunable.append(name)

    # --- ENV BLOCK FIRST ---
    # Default PATH augmentation as requested; allow optional extra append via ENV_PATH_APPEND.
    env_block = {
        "PATH": "$(PATH):$(HOME)/.local/bin" + ((":" + os.getenv("ENV_PATH_APPEND")) if os.getenv("ENV_PATH_APPEND") else "")
    }

    merged_apps, plan = reconcile(existing_apps, apps,
                                  adopt_by_name=adopt_by_name, refresh=refresh,
                                  previously_managed=previously_managed,
                                  tombstones=tombstones,
                                  prunable_sources=prunable,
                                  restore_removed=restore_removed)
    log_plan(plan)

    if dry_run:
        log("Dry run: apps.json not written.")
    elif os.path.exists(apps_json):
        try:
            log(f"Backup saved: {backup(apps_json)}")
        except Exception as e:
            log(f"Warning: failed to backup apps.json: {e}")

    # "env" first, then "apps", preserving any other top-level keys the user has.
    out = {"env": payload.get("env", env_block), "apps": merged_apps}
    for key, value in payload.items():
        if key not in ("env", "apps", "meta"):
            out[key] = value
    out["meta"] = {
        "generated-by": "bazzite-sunshine-manager",
        "enabled-importers": enabled_importers,
        "managed": plan.get("managed", []),
        "removed": plan.get("tombstones", []),
    }
    if not dry_run:
        write_json(apps_json, out)
        log(f"Wrote {len(merged_apps)} apps ({len(plan['kept_foreign'])} not ours, left alone). "
            f"Enabled importers: {', '.join(enabled_importers) or 'none'}")

    if as_json:
        # Logs go to stderr, so stdout stays a clean JSON document.
        doc = plan_document(plan, config_dir=conf_dir, apps_json=apps_json,
                            sources=sources, dry_run=dry_run,
                            generator_version=VERSION)
        json.dump(doc, sys.stdout, indent=2)
        sys.stdout.write("\n")

    # Sunshine has no file watcher, so the file we just wrote is invisible to it
    # until it re-reads. Ask it to, rather than restarting and dropping whatever
    # stream is in progress.
    if getenv_flag("BSM_RELOAD", False):
        reload_sunshine(conf_dir)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
