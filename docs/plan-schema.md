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
| `kept_foreign` | Not ours — Sunshine's defaults, or entries you created. Never touched. |

Every entry except `kept_foreign` carries `source` and `id`, which together form
the `<source>:<id>` selector accepted by `--refresh-edited`.

## `sources[].status`

| Status | Meaning |
|---|---|
| `ok` | Ran to completion. |
| `disabled` | Turned off by flag or environment. |
| `error` | Raised; `error` holds the message. |

**`ok` with `imported: 0` does not yet mean "nothing is installed."** An
importer that cannot find its library logs and returns an empty list rather than
raising, so a missing Steam install and an empty one look alike here. This is
why removal of `missing` entries is opt-in and must never be driven by this
field alone.

## Caveat

`--dry-run` does not write `apps.json`, but importers still populate the image
cache under `<config_dir>/images/` while resolving cover art. A dry run is
read-only with respect to your configuration, not to the filesystem.
