#!/usr/bin/env bash
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
#   --reload                       Ask Sunshine to re-read apps.json via its own API,
#                                  without restarting. Keeps any stream alive.
#                                  Needs SUNSHINE_USERNAME/SUNSHINE_PASSWORD or a
#                                  mode-600 .bsm-credentials in the config dir.
#   --python PY                    Python interpreter to use (default: python3)
#   --conf-dir DIR                 Force Sunshine config dir (sets SUNSHINE_CONF_DIR for your script to read)
#   --sgdb-key "YOUR_STEAMGRID_API" Enable SteamGrid to download game covers (IMPORT_HEROIC=1/0)
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

# Resolve paths
SCRIPT_DIR="/var/home/steam/.config/sunshine/helper"
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
    --python)       PYTHON="${2:-}"; shift 2 ;;
    --conf-dir)     export SUNSHINE_CONF_DIR="${2:-}"; shift 2 ;;
    --sgdb-key)     SGDB_API_KEY="${2:-}"; shift 2 ;;
    --sgdb-enable)  SGDB_ENABLE="${2:-1}"; shift 2 ;;
    --sgdb-timeout) SGDB_TIMEOUT="${2:-12}"; shift 2 ;;
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
export BSM_RELOAD="${BSM_RELOAD:-0}"

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
