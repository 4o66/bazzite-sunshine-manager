# Plan document schema (`--json`)

`sunshine-import --dry-run --json` writes a JSON document to **stdout**. All
human-readable logging goes to stderr, so stdout is safe to pipe.

This is the only supported interface for other tools. Do not import this
project's Python modules: it is not a package, and it claims the top-level
names `common` and `importers`.

## Versioning

`schema` is an integer, currently **1**. Additive changes (new keys) will not
bump it; removing or repurposing a key will. **Reject a schema version you do
not recognise** rather than guessing.

## Shape

```json
{
  "schema": 1,
  "generator": { "name": "bazzite-sunshine-manager", "version": "2.0" },
  "generated_at": "2026-09-11T23:45:00-0700",
  "dry_run": true,
  "config_dir": "/home/u/.config/sunshine",
  "apps_json": "/home/u/.config/sunshine/apps.json",
  "sources": [
    { "name": "steam", "enabled": true, "status": "ok", "imported": 5 }
  ],
  "totals": { "added": 5, "updated": 0, "unchanged": 0,
              "diverged": 0, "missing": 0, "kept_foreign": 3 },
  "plan": {
    "added":     [ { "name": "Portal 2", "source": "steam", "id": "620" } ],
    "updated":   [ { "name": "...", "source": "...", "id": "...",
                     "fields": ["image-path"] } ],
    "unchanged": [ { "name": "...", "source": "...", "id": "..." } ],
    "diverged":  [ { "name": "...", "source": "...", "id": "...",
                     "fields": [ { "field": "cmd",
                                   "current": "what you set",
                                   "would_be": "what the importer wants" } ] } ],
    "missing":   [ { "name": "...", "source": "...", "id": "..." } ],
    "kept_foreign": [ { "name": "Desktop" } ]
  }
}
```

## What each bucket means

| Bucket | Meaning |
|---|---|
| `added` | Discovered now, not in `apps.json` yet. |
| `updated` | Ours, and fields we own changed. `fields` lists which. |
| `unchanged` | Ours, nothing to do. |
| `diverged` | Ours, but you edited these fields. **Left alone.** Reclaim with `--refresh-edited <source>:<id>`. |
| `missing` | We generated it before and no longer discover it. **Left in place.** |
| `pruned` | Removed, because its source scanned cleanly and no longer lists it. Only with `--remove-uninstalled`. |
| `removed_by_user` | We wrote it last run and it is gone, so you deleted it. **Not recreated**, and recorded as a tombstone. |
| `suppressed` | In the library, but you deleted it previously, so it was not re-added. |
| `restored` | A tombstone cleared by `--restore-removed`; the entry may be added again. |
| `kept_foreign` | Not ours — Sunshine's defaults, or entries you created. Never touched. |

Every entry except `kept_foreign` carries `source` and `id`, which together form
the `<source>:<id>` selector accepted by `--refresh-edited`.

## `sources[].status`

| Status | Meaning |
|---|---|
| `ok` | The library was found and read. |
| `not_found` | The library or config directory does not exist here. |
| `disabled` | Turned off by flag or environment. |
| `error` | Raised; `error` holds the message. |

Only `ok` proves anything about what is installed. The other three mean the scan
never happened, which looks identical to "everything was uninstalled" — so
entries belonging to such a source are never removed.

**`ok` with `imported: 0` is still treated as suspect.** A library that is
offline, unmounted or mid-update can scan cleanly and yield nothing. Pruning is
refused in that case unless `--allow-empty-prune` is passed.

## State kept in `meta`

`apps.json`'s `meta` block carries two lists this tool maintains:

- `managed` — the `<source>:<id>` of every entry written last run. Comparing it
  against what is present is how a deletion is detected at all.
- `removed` — tombstones for entries you deleted, so they are not recreated.
  `--restore-removed` clears them.

This lives in `apps.json` rather than a sidecar because Sunshine preserves it:
`saveApp()` and `deleteApp()` only ever rewrite `file_tree["apps"]`. Deleting
the `meta` block by hand is harmless — deleted entries come back once, and the
state rebuilds from there.

## Caveat

`--dry-run` does not write `apps.json`, but importers still populate the image
cache under `<config_dir>/images/` while resolving cover art. A dry run is
read-only with respect to your configuration, not to the filesystem.
