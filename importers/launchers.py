# importers/launchers.py
from __future__ import annotations
import os
import urllib.request
from typing import List, Dict, Any
from pathlib import Path
from common.utils import log, have_cmd, yn
from common.reconcile import tag

# GitHub "blob" URLs -> convert to raw content automatically
POSTERS = {
    "desktop": "https://github.com/wadiebs/bazzite-sunshine-manager/blob/main/common/posters/desktop.png",
    "steam":   "https://github.com/wadiebs/bazzite-sunshine-manager/blob/main/common/posters/steam.png",
    "heroic":  "https://github.com/wadiebs/bazzite-sunshine-manager/blob/main/common/posters/heroic.png",
    "reboot":  "https://github.com/wadiebs/bazzite-sunshine-manager/blob/main/common/posters/reboot.png",
}

NAMES = {
    "desktop": "#1 Desktop",
    "steam": "Zz Steam",
    "heroic": "Zz Heroic",
    "reboot": "Zz Reboot",
}

def _to_raw_github(url: str) -> str:
    # github.com/{user}/{repo}/blob/{branch}/{path} -> raw.githubusercontent.com/{user}/{repo}/{branch}/{path}
    if "github.com" in url and "/blob/" in url:
        parts = url.split("github.com/", 1)[1]
        user_repo, rest = parts.split("/", 1)
        repo, rest = rest.split("/", 1)
        # rest starts with 'blob/...'
        _, branch, *path_parts = rest.split("/")
        raw = f"https://raw.githubusercontent.com/{user_repo}/{repo}/{branch}/" + "/".join(path_parts)
        return raw
    return url

def _download_image(src_url: str, dst_path: str, timeout: int = 8) -> bool:  # Reduced from 20 to 8 seconds
    url = _to_raw_github(src_url)
    try:
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        if not data or len(data) < 200:  # sanity check
            return False
        with open(dst_path, "wb") as f:
            f.write(data)
        return True
    except Exception as e:
        log(f"Poster download failed: {url} -> {dst_path} ({e})")
        return False

def _steam_cmd(home: str) -> tuple[str, str]:
    """Return (cmd, working_dir) for Steam if found, else ('','')."""
    flatpak_root = f"{home}/.var/app/com.valvesoftware.Steam/.local/share/Steam"
    if os.path.isdir(flatpak_root):
        return ("flatpak run com.valvesoftware.Steam", flatpak_root)
    if have_cmd("steam"):
        for r in (f"{home}/.local/share/Steam", f"{home}/.steam/steam"):
            if os.path.isdir(r):
                return ("steam", r)
        return ("steam", home)
    return ("", "")

def _heroic_cmd(home: str) -> tuple[str, str]:
    """Return (cmd, working_dir) for Heroic if found, else ('','')."""
    candidates = [
        f"{home}/.var/app/com.heroicgameslauncher.hgl/config/heroic",
        f"{home}/.config/heroic",
    ]
    is_flatpak = any(os.path.isdir(p) and "/.var/app/" in p for p in candidates)
    if is_flatpak:
        return ("flatpak run com.heroicgameslauncher.hgl", home)
    if have_cmd("heroic"):
        return ("heroic", home)
    return ("", "")

def _common_fields() -> Dict[str, Any]:
    return {
        "exclude-global-prep-cmd": False,
        "exit-timeout": 5,
        "output": "",
        "wait-all": True,
    }

def _ensure_posters(images_dir: str) -> Dict[str, str]:
    """
    Ensure all required posters exist under images_dir.
    Returns dict with resolved local image paths.
    """
    paths: Dict[str, str] = {}
    for key, url in POSTERS.items():
        filename = {
            "desktop": "Desktop.png",
            "steam":   "Steam.png",
            "heroic":  "Heroic.png",
            "reboot":  "Reboot.png",
        }[key]
        dst = os.path.join(images_dir, filename)
        if not os.path.isfile(dst):
            ok = _download_image(url, dst)
            if ok:
                log(f"Downloaded poster: {dst}")
            else:
                log(f"Warning: poster not downloaded: {dst}")
        paths[key] = dst
    return paths

def import_launchers(home: str, conf_dir: str, images_dir: str, settings: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Create generic launchers (Desktop, Steam-if-installed, Heroic-if-installed, Reboot).

    Toggle with IMPORT_LAUNCHERS (default: on).
    """
    enabled = str(settings.get("IMPORT_LAUNCHERS", "1")).strip().lower() in ("1", "true", "yes", "on")
    if not enabled:
        log("Launchers importer disabled.")
        return []

    posters = _ensure_posters(images_dir)
    apps: List[Dict[str, Any]] = []

    # 1) Desktop
    apps.append(tag({
        "name": NAMES["desktop"],
        "cmd": "",
        "working-dir": home,
        "image-path": posters["desktop"],
        "detached": False,
        "elevated": False,
        "exit-on-close": True,
        **_common_fields(),
    }, "launcher", "desktop"))
    log(f"Added {yn(NAMES['desktop'])} launcher")

    # 2) Steam (only if installed)
    steam_cmd, steam_wd = _steam_cmd(home)
    if steam_cmd:
        apps.append(tag({
            "name": NAMES["steam"],
            "cmd": steam_cmd,
            "working-dir": steam_wd or home,
            "image-path": posters["steam"],
            "detached": False,
            "elevated": False,
            "exit-on-close": True,
            **_common_fields(),
        }, "launcher", "steam"))
        log(f"Added {yn(NAMES['steam'])} launcher")
    else:
        log("Steam not detected; skipping Steam launcher")

    # 3) Heroic (only if installed)
    heroic_cmd, heroic_wd = _heroic_cmd(home)
    if heroic_cmd:
        apps.append(tag({
            "name": NAMES["heroic"],
            "cmd": heroic_cmd,
            "working-dir": heroic_wd or home,
            "image-path": posters["heroic"],
            "detached": False,
            "elevated": False,
            "exit-on-close": True,
            **_common_fields(),
        }, "launcher", "heroic"))
        log(f"Added {yn(NAMES['heroic'])} launcher")
    else:
        log("Heroic not detected; skipping Heroic launcher")

    # 4) Reboot
    apps.append(tag({
        "name": NAMES["reboot"],
        "auto-detach": True,
        "cmd": [],
        "detached": ["systemctl reboot"],
        "image-path": posters["reboot"],
        **_common_fields(),
    }, "launcher", "reboot"))
    log(f"Added {yn(NAMES['reboot'])} launcher")

    return apps
