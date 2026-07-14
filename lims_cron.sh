#!/bin/bash
#
# Cron-safe entry point for LIMS sync/archive jobs.
#
# cron runs with a bare environment (no conda/micromamba activation, minimal
# PATH, cwd=$HOME). This wrapper makes invocation deterministic:
#   - uses the project's Python interpreter by ABSOLUTE path,
#   - sets PYTHONPATH to the project root,
#   - refuses to run (cleanly) if the /storage NFS mount isn't ready, which
#     prevents config.py's mkdir() from creating phantom dirs under the
#     mountpoint before NFS comes up.
#
# Usage (same subcommands as lims.sh / the CLI):
#   ./lims_cron.sh sync
#   ./lims_cron.sh archive create --type hourly
#   ./lims_cron.sh archive cleanup
#
set -euo pipefail

# Project root = directory containing this script.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Absolute path to the project's interpreter (not on PATH in cron). install_cron.sh
# bakes the correct per-host path into the crontab as LIMS_PYTHON, so the same
# tracked script works on every host; the fallback is only for direct manual runs.
PYTHON="${LIMS_PYTHON:-/scratch/fliu/hub_home/nspahr/.local/share/mamba/envs/aisynbio_env/bin/python}"

# Data mount that must be present before touching the DB/archives/logs.
STORAGE_MOUNT="/storage"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') lims_cron: $*"; }

if [[ ! -x "$PYTHON" ]]; then
    log "ERROR: interpreter not found or not executable: $PYTHON"
    exit 1
fi

# Skip cleanly (exit 0) if /storage isn't mounted yet — do NOT let Python run
# and create local phantom directories under the mountpoint.
if ! mountpoint -q "$STORAGE_MOUNT"; then
    log "SKIP: $STORAGE_MOUNT is not mounted"
    exit 0
fi

cd "$SCRIPT_DIR"
export PYTHONPATH="$SCRIPT_DIR:${PYTHONPATH:-}"

exec "$PYTHON" "$SCRIPT_DIR/aisynbiopipeline/cli/lims.py" "$@"
