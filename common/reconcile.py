"""Three-way reconcile of generated apps into an existing apps.json.

The importer used to rewrite apps.json from scratch on every run, which deleted
anything the user had added through Sunshine's web UI, including the defaults
Sunshine ships with. This module merges instead, by tracking which entries and
which individual fields the importer owns.

Ownership is recorded inline, in a "bsm" key on each generated app. That is safe
because Sunshine round-trips unknown keys: confighttp.cpp parses apps.json into a
generic JSON DOM, replaces only the element being edited, and re-dumps the whole
tree, and the web UI deep-clones an app before editing it. Entries we did not
create are never touched.
"""

import hashlib
import json
import os
import shutil
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .utils import log

MARKER = "bsm"
MARKER_VERSION = 1

# Sunshine's saveApp() erases these keys when their value is empty, so an absent
# key and an empty one are the same state and must hash identically. Without
# this, one save in the web UI makes every entry look user-edited.
_EMPTY_EQUIV = ("prep-cmd", "detached")

Identity = Tuple[str, str]


def _normalized(key: str, value: Any) -> Any:
    if key in _EMPTY_EQUIV and not value:
        return None
    return value


def field_hash(key: str, value: Any) -> str:
    """Hash a normalized field *value*, never its serialized form.

    Sunshine re-dumps apps.json with keys sorted and 4-space indent, and getApps()
    coerces legacy string booleans to real booleans, so hashing text would report
    spurious edits.
    """
    blob = json.dumps(_normalized(key, value), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def tag(app: Dict[str, Any], source: str, ident: Any) -> Dict[str, Any]:
    """Return *app* with an ownership marker recording every field we set."""
    tagged = {k: v for k, v in app.items() if k != MARKER}
    tagged[MARKER] = {
        "v": MARKER_VERSION,
        "source": source,
        "id": str(ident),
        "fields": {k: field_hash(k, v) for k, v in tagged.items()},
    }
    return tagged


def identity(app: Dict[str, Any]) -> Optional[Identity]:
    m = app.get(MARKER)
    if isinstance(m, dict) and m.get("source") and m.get("id") is not None:
        return (str(m["source"]), str(m["id"]))
    return None


def _recorded_hashes(app: Dict[str, Any]) -> Dict[str, str]:
    m = app.get(MARKER)
    if isinstance(m, dict) and isinstance(m.get("fields"), dict):
        return m["fields"]
    return {}


def _forced(ident: Identity, refresh: Optional[Sequence[str]]) -> bool:
    if not refresh:
        return False
    if "all" in refresh:
        return True
    return f"{ident[0]}:{ident[1]}" in refresh


def _merge(cur: Dict[str, Any], want: Dict[str, Any], ident: Identity,
           forced: bool) -> Tuple[Dict[str, Any], List[str], List[Dict[str, Any]]]:
    recorded = _recorded_hashes(cur)
    merged = {k: v for k, v in cur.items() if k != MARKER}
    marker_fields: Dict[str, str] = {}
    changed: List[str] = []
    diverged: List[Dict[str, Any]] = []

    for key, new_value in want.items():
        if key == MARKER:
            continue
        cur_value = cur.get(key)
        cur_h = field_hash(key, cur_value)
        new_h = field_hash(key, new_value)
        was = recorded.get(key)
        # The user owns this field if it no longer matches what we last wrote.
        user_owned = was is not None and cur_h != was

        if user_owned and not forced:
            if new_h == cur_h:
                marker_fields[key] = new_h       # converged; ours again
            else:
                diverged.append({"field": key, "current": cur_value, "would_be": new_value})
                marker_fields[key] = was         # keep flagging it every run
            continue

        if cur_h != new_h:
            merged[key] = new_value
            changed.append(key)
        marker_fields[key] = new_h

    merged[MARKER] = {
        "v": MARKER_VERSION,
        "source": ident[0],
        "id": ident[1],
        "fields": marker_fields,
    }
    return merged, changed, diverged


def reconcile(existing: List[Dict[str, Any]], desired: List[Dict[str, Any]],
              adopt_by_name: bool = False,
              refresh: Optional[Sequence[str]] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Merge *desired* generated apps into the *existing* app list.

    Returns (apps, plan). Entries without one of our markers are passed through
    untouched. Generated entries no longer present in *desired* are reported as
    "missing" but kept: removing them is a separate, opt-in behaviour.
    """
    plan: Dict[str, Any] = {
        "added": [], "updated": [], "unchanged": [],
        "diverged": [], "missing": [], "kept_foreign": [],
    }

    by_id: Dict[Identity, Dict[str, Any]] = {}
    for app in desired:
        ident = identity(app)
        if ident is None:
            raise ValueError(f"desired app {app.get('name')!r} has no ownership marker")
        by_id[ident] = app

    name_to_id = {a.get("name"): i for i, a in by_id.items()}
    out: List[Dict[str, Any]] = []
    claimed = set()

    for cur in existing:
        if not isinstance(cur, dict):
            out.append(cur)
            continue
        ident = identity(cur)
        if ident is None and adopt_by_name:
            ident = name_to_id.get(cur.get("name"))

        if ident is None:
            plan["kept_foreign"].append(cur.get("name"))
            out.append(cur)
            continue
        if ident not in by_id:
            plan["missing"].append({"name": cur.get("name"), "source": ident[0], "id": ident[1]})
            out.append(cur)
            continue
        if ident in claimed:            # duplicate marker; keep the first only
            plan["missing"].append({"name": cur.get("name"), "source": ident[0],
                                    "id": ident[1], "duplicate": True})
            continue

        claimed.add(ident)
        merged, changed, diverged = _merge(cur, by_id[ident], ident, _forced(ident, refresh))
        out.append(merged)
        if diverged:
            plan["diverged"].append({"name": merged.get("name"), "source": ident[0],
                                     "id": ident[1], "fields": diverged})
        if changed:
            plan["updated"].append({"name": merged.get("name"), "fields": changed})
        elif not diverged:
            plan["unchanged"].append(merged.get("name"))

    for ident, app in by_id.items():
        if ident not in claimed:
            out.append(dict(app))
            plan["added"].append(app.get("name"))

    return out, plan


def log_plan(plan: Dict[str, Any]) -> None:
    log(f"Reconcile: {len(plan['added'])} added, {len(plan['updated'])} updated, "
        f"{len(plan['unchanged'])} unchanged, {len(plan['diverged'])} edited by you, "
        f"{len(plan['missing'])} no longer found, {len(plan['kept_foreign'])} not ours")
    for entry in plan["diverged"]:
        fields = ", ".join(f["field"] for f in entry["fields"])
        log(f"  kept your edits to {entry['name']!r} ({fields}); "
            f"use --refresh-edited {entry['source']}:{entry['id']} to overwrite")
    for entry in plan["missing"]:
        log(f"  {entry['name']!r} was imported before but is not installed now; left in place")


def backup(path: str, keep: int = 10) -> str:
    """Timestamped backup, keeping the most recent *keep*. Returns its path."""
    if not os.path.exists(path):
        return ""
    dst = f"{path}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(path, dst)
    prefix = os.path.basename(path) + ".bak-"
    directory = os.path.dirname(path) or "."
    old = sorted(f for f in os.listdir(directory) if f.startswith(prefix))
    for stale in old[:-keep]:
        try:
            os.remove(os.path.join(directory, stale))
        except OSError:
            pass
    return dst
