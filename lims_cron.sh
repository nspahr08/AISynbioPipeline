#!/bin/bash
#
# Cron-safe entry point for LIMS sync/archive jobs.
#
# cron runs with a bare environment (no conda/micromamba activation, minimal
# PATH, cwd=$HOME). This wrapper makes invocation deterministic:
#   - uses the project's Python interpreter by ABSOLUTE path (LIMS_PYTHON,
#     baked into the crontab by install_cron.sh),
#   - sets PYTHONPATH to the project root,
#   - refuses to run (cleanly) if the shared data directory isn't available,
#     which prevents config.py's mkdir() from creating phantom local dirs when
#     the network filesystem isn't mounted (or this is the wrong host).
#
# The data directory is read from config.json's db_path, so each host uses its
# own mountpoint for the shared filesystem with no per-host edits to this script.
#
# Usage (same subcommands as lims.sh / the CLI):
#   ./lims_cron.sh sync
#   ./lims_cron.sh archive create --type hourly
#   ./lims_cron.sh archive cleanup
#
set -euo pipefail

# Project root = directory containing this script.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Interpreter (not on PATH in cron). install_cron.sh bakes the correct per-host
# path into the crontab as LIMS_PYTHON; the fallback is only for direct runs.
PYTHON="${LIMS_PYTHON:-/scratch/fliu/hub_home/nspahr/.local/share/mamba/envs/aisynbio_env/bin/python}"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') lims_cron: $*"; }

if [[ ! -x "$PYTHON" ]]; then
    log "ERROR: interpreter not found or not executable: $PYTHON"
    exit 1
fi

# Shared data directory = parent of db_path in config.json. Reading config.json
# (a local file in the checkout) never touches the shared FS, so this is safe
# even when the mount is down. LIMS_DATA_DIR overrides if ever needed.
DATA_DIR="${LIMS_DATA_DIR:-$("$PYTHON" -c "import json,os;print(os.path.dirname(json.load(open('$SCRIPT_DIR/aisynbiopipeline/limsapi/config.json'))['database']['db_path']))" 2>/dev/null || true)}"

if [[ -z "$DATA_DIR" || ! -d "$DATA_DIR" ]]; then
    log "SKIP: shared data directory not available: ${DATA_DIR:-<unknown>}"
    exit 0
fi

cd "$SCRIPT_DIR"
export PYTHONPATH="$SCRIPT_DIR:${PYTHONPATH:-}"

exec "$PYTHON" "$SCRIPT_DIR/aisynbiopipeline/cli/lims.py" "$@"
