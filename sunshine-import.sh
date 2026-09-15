#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# sunshine-import — wrapper to run sunshine-import.py with flags
#
# Usage:
#   sunshine-import [options] [-- <extra-args-to-python-script>]
#
# Options:
#   --steam / --no-steam           Enable/disable Steam importer (EXPORT: IMPORT_STEAM=1/0)
#   --heroic / --no-heroic         Enable/disable Heroic importer (IMPORT_HEROIC=1/0)
#   --launchers / --no-launchers   Enable/disable Launchers importer (IMPORT_LAUNCHERS=1/0)
#   --restart                      Restart Sunshine after import (systemctl --user restart sunshine.service)
#   --browse DIR                   List DIR through Sunshine's own file browser.
#   --browse-type T                any | directory | executable (default: any)
#   --mutate                       Apply manual changes read as JSON on stdin
#                                  ({"ops":[...]}). Combine with --reload.
#   --state                        Report what is in apps.json now (not what would
#                                  change) and exit. Use with --json.
#   --backups                      List the kept copies of apps.json, newest
#                                  first. One is taken before every write. Put
#                                  one back with --mutate and a "rollback"
#                                  operation naming it.
#   --art-search                   List every piece of cover art available for one
#                                  app, each cached ready to choose. Identify the
#                                  app with --art-source/--art-ident (its ownership
#                                  marker) and --art-name. Use with --json.
#   --art-choose ID                Copy candidate ID from that list into the images
#                                  tree and report the image-path to use.
#   --art-name NAME                The app's name: searched for on SteamGridDB, and
#                                  used to name the chosen file.
#   --art-source S --art-ident I   The app's ownership marker, e.g. steam / 526870.
#   --save-sgdb-key                Read a SteamGridDB key on stdin, check it against
#                                  the API, store it mode 600. Use this rather than
#                                  --sgdb-key, which puts the key in ps and history.
#   --check-auth                   Test the stored Sunshine credentials and exit.
#   --save-auth                    Read a username and password as two lines on
#                                  stdin, verify them against Sunshine, and store
#                                  them mode 600. Never pass them as arguments.
#   --reload                       Ask Sunshine to re-read apps.json via its own API,
#                                  without restarting. Keeps any stream alive.
#                                  Needs SUNSHINE_USERNAME/SUNSHINE_PASSWORD or a
#                                  mode-600 .bsm-credentials in the config dir.
#   --python PY                    Python interpreter to use (default: python3)
#   --conf-dir DIR                 Force Sunshine config dir (sets SUNSHINE_CONF_DIR for your script to read)
#   --sgdb-key "YOUR_STEAMGRID_API" Enable SteamGrid to download game covers (IMPORT_HEROIC=1/0)
#   --refresh-edited [SEL]         Overwrite fields you edited by hand. Bare = all;
#                                  or a selector like steam:620 for one entry.
#   --remove-uninstalled           Remove entries whose source no longer lists them.
#                                  Only applies to sources that scanned cleanly.
#   --allow-empty-prune            Also prune when a source scanned but found nothing
#                                  (normally refused: that means a library is offline).
#   --restore-removed [SEL]        Undo deletions so entries are recreated. Bare = all.
#   --dry-run                      Report what would change; do not write apps.json.
#   --json                         Emit the plan as JSON on stdout (logs stay on stderr).
#   --restore-defaults             Put back any of Sunshine's default entries that
#                                  are missing (never overwrites ones you kept).
#   --no-system-apps               Do not seed or restore Sunshine's defaults.
#   --system-apps-json FILE        Use FILE as the source of those defaults.
#   -h, --help                     Show help
#
# Examples:
#   sunshine-import --steam --no-heroic --restart
#   sunshine-import --python /usr/bin/python3
#   sunshine-import --conf-dir "$HOME/.config/sunshine"
#
set -euo pipefail

# Defaults
PYTHON="python3"
RESTART=0
: "${IMPORT_STEAM:=1}"
: "${IMPORT_HEROIC:=1}"
: "${IMPORT_LAUNCHERS:=1}"

# Resolve paths from this script's own location, so the tool works for whatever
# user is running it rather than only a user named "steam". The launcher is
# symlinked into ~/.local/bin by common/init.sh, so resolve symlinks first.
# Override with BSM_HELPER_DIR when testing from a checkout.
_resolve_self_dir() {
  local src="${BASH_SOURCE[0]}" dir
  while [[ -L "$src" ]]; do
    dir="$(cd -P "$(dirname "$src")" && pwd)"
    src="$(readlink "$src")"
    [[ "$src" != /* ]] && src="$dir/$src"
  done
  cd -P "$(dirname "$src")" && pwd
}
SCRIPT_DIR="${BSM_HELPER_DIR:-$(_resolve_self_dir)}"
PY_SCRIPT="${SCRIPT_DIR}/sunshine-import.py"

# Check requirements
REQS="${SCRIPT_DIR}/requirements.txt"
if [[ -f "$REQS" ]]; then
  if ! "$PYTHON" -c "import PIL" >/dev/null 2>&1; then
    echo "[bootstrap] Installing requirements from $REQS ..." >&2
    "$PYTHON" -m pip install --user -r "$REQS"
  fi
fi

# Defaults (can be overridden by flags below)
: "${SGDB_ENABLE:=1}"
: "${SGDB_TIMEOUT:=12}"
: "${SGDB_API_KEY:=}"

usage() { sed -n '1,50p' "$0" | sed -n '1,30p' >&2; exit 1; }

# Parse all arguments in a single loop
ARGS_TO_PY=()
while (( "$#" )); do
  case "$1" in
    --steam)        IMPORT_STEAM=1; shift ;;
    --no-steam)     IMPORT_STEAM=0; shift ;;
    --heroic)       IMPORT_HEROIC=1; shift ;;
    --no-heroic)    IMPORT_HEROIC=0; shift ;;
    --launchers)    IMPORT_LAUNCHERS=1; shift ;;
    --no-launchers) IMPORT_LAUNCHERS=0; shift ;;
    --restart)      RESTART=1; shift ;;
    --reload)       BSM_RELOAD=1; shift ;;
    --state)        BSM_STATE=1; shift ;;
    --mutate)       BSM_MUTATE=1; shift ;;
    --browse)       BSM_BROWSE=1; BSM_BROWSE_PATH="${2:-}"; shift 2 ;;
    --browse-type)  BSM_BROWSE_TYPE="${2:-any}"; shift 2 ;;
    --backups)      BSM_BACKUPS=1; shift ;;
    --backup-diff)  BSM_BACKUP_DIFF="${2:-}"; shift 2 ;;
    --art-search)   BSM_ART_SEARCH=1; shift ;;
    --art-choose)   BSM_ART_CHOOSE="${2:-}"; shift 2 ;;
    --art-name)     BSM_ART_NAME="${2:-}"; shift 2 ;;
    --art-source)   BSM_ART_SOURCE="${2:-}"; shift 2 ;;
    --art-ident)    BSM_ART_IDENT="${2:-}"; shift 2 ;;
    --save-sgdb-key) BSM_SAVE_SGDB_KEY=1; shift ;;
    --check-auth)   BSM_CHECK_AUTH=1; shift ;;
    --save-auth)    BSM_SAVE_AUTH=1; shift ;;
    --python)       PYTHON="${2:-}"; shift 2 ;;
    --conf-dir)     export SUNSHINE_CONF_DIR="${2:-}"; shift 2 ;;
    --sgdb-key)     SGDB_API_KEY="${2:-}"; shift 2 ;;
    --sgdb-enable)  SGDB_ENABLE="${2:-1}"; shift 2 ;;
    --sgdb-timeout) SGDB_TIMEOUT="${2:-12}"; shift 2 ;;
    --dry-run)      BSM_DRY_RUN=1; shift ;;
    --json)         BSM_JSON=1; shift ;;
    --restore-defaults) BSM_RESTORE_DEFAULTS=1; shift ;;
    --no-system-apps)   INCLUDE_SYSTEM_APPS=0; shift ;;
    --system-apps-json) SYSTEM_APPS_JSON="${2:-}"; shift 2 ;;
    --remove-uninstalled) BSM_REMOVE_UNINSTALLED=1; shift ;;
    --allow-empty-prune)  BSM_ALLOW_EMPTY_PRUNE=1; shift ;;
    --restore-removed)
                    if [[ -n "${2:-}" && "${2:-}" != -* ]]; then
                      BSM_RESTORE_REMOVED="$2"; shift 2
                    else
                      BSM_RESTORE_REMOVED="all"; shift
                    fi ;;
    --refresh-edited)
                    # optional selector; bare flag means everything
                    if [[ -n "${2:-}" && "${2:-}" != -* ]]; then
                      BSM_REFRESH_EDITED="$2"; shift 2
                    else
                      BSM_REFRESH_EDITED="all"; shift
                    fi ;;
    -h|--help)      usage ;;
    --)             shift; ARGS_TO_PY+=("$@"); break ;;
    *)              ARGS_TO_PY+=("$1"); shift ;;
  esac
done

# Sanity checks
if [[ ! -f "$PY_SCRIPT" ]]; then
  echo "ERROR: sunshine-import.py not found at: $PY_SCRIPT" >&2
  exit 1
fi

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "ERROR: Python interpreter not found: $PYTHON" >&2
  exit 1
fi

# Environment toggles exported for the Python script
export IMPORT_STEAM IMPORT_HEROIC IMPORT_LAUNCHERS SGDB_API_KEY SGDB_ENABLE SGDB_TIMEOUT
export BSM_REFRESH_EDITED="${BSM_REFRESH_EDITED:-}"
export BSM_DRY_RUN="${BSM_DRY_RUN:-0}" BSM_JSON="${BSM_JSON:-0}"
export BSM_RESTORE_DEFAULTS="${BSM_RESTORE_DEFAULTS:-0}"
export INCLUDE_SYSTEM_APPS="${INCLUDE_SYSTEM_APPS:-1}" SYSTEM_APPS_JSON="${SYSTEM_APPS_JSON:-}"
export BSM_REMOVE_UNINSTALLED="${BSM_REMOVE_UNINSTALLED:-0}"
export BSM_ALLOW_EMPTY_PRUNE="${BSM_ALLOW_EMPTY_PRUNE:-0}"
export BSM_RESTORE_REMOVED="${BSM_RESTORE_REMOVED:-}"
export BSM_RELOAD="${BSM_RELOAD:-0}"
export BSM_CHECK_AUTH="${BSM_CHECK_AUTH:-0}" BSM_SAVE_AUTH="${BSM_SAVE_AUTH:-0}"
export BSM_STATE="${BSM_STATE:-0}" BSM_MUTATE="${BSM_MUTATE:-0}"
export BSM_BROWSE="${BSM_BROWSE:-0}" BSM_BROWSE_PATH="${BSM_BROWSE_PATH:-}"
export BSM_BROWSE_TYPE="${BSM_BROWSE_TYPE:-any}"
export BSM_BACKUPS="${BSM_BACKUPS:-0}"
export BSM_BACKUP_DIFF="${BSM_BACKUP_DIFF:-}"
export BSM_ART_SEARCH="${BSM_ART_SEARCH:-0}" BSM_ART_CHOOSE="${BSM_ART_CHOOSE:-}"
export BSM_ART_NAME="${BSM_ART_NAME:-}" BSM_ART_SOURCE="${BSM_ART_SOURCE:-}"
export BSM_ART_IDENT="${BSM_ART_IDENT:-}"
export BSM_SAVE_SGDB_KEY="${BSM_SAVE_SGDB_KEY:-0}"

echo "[sunshine-import] IMPORT_STEAM=$IMPORT_STEAM IMPORT_HEROIC=$IMPORT_HEROIC IMPORT_LAUNCHERS=$IMPORT_LAUNCHERS RESTART=$RESTART" >&2
if [[ -n "${SUNSHINE_CONF_DIR:-}" ]]; then
  echo "[sunshine-import] SUNSHINE_CONF_DIR=$SUNSHINE_CONF_DIR" >&2
fi
echo "[sunshine-import] Running: $PYTHON \"$PY_SCRIPT\" ${ARGS_TO_PY[*]:-}" >&2

set +e
"$PYTHON" "$PY_SCRIPT" "${ARGS_TO_PY[@]:-}"
RET=$?
set -e

if [[ $RET -ne 0 ]]; then
  echo "[sunshine-import] Python exited with code $RET" >&2
  exit "$RET"
fi

if [[ $RESTART -eq 1 ]]; then
  echo "[sunshine-import] Checking which Sunshine service is running..." >&2
  
  # Check which sunshine service is active
  if systemctl --user is-active --quiet sunshine-kms.service; then
    echo "[sunshine-import] Restarting sunshine-kms.service..." >&2
    systemctl --user restart sunshine-kms.service || {
      echo "[sunshine-import] WARNING: failed to restart sunshine-kms.service" >&2
    }
  elif systemctl --user is-active --quiet sunshine.service; then
    echo "[sunshine-import] Restarting sunshine.service..." >&2
    systemctl --user restart sunshine.service || {
      echo "[sunshine-import] WARNING: failed to restart sunshine.service" >&2
    }
  else
    echo "[sunshine-import] WARNING: No active Sunshine service found. Skipping restart." >&2
    echo "[sunshine-import] Please start either sunshine.service or sunshine-kms.service manually." >&2
  fi
fi

echo "[sunshine-import] Done." >&2
