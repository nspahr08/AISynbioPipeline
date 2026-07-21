#!/bin/bash
#
# Cron-safe entry point for the AISynbio data pipeline jobs:
#   - globus      : transfer data from a Globus endpoint into synbio scratch
#   - process-od  : process robotic OD data and upload results to Google Drive
#
# cron runs with a bare environment (no conda/micromamba activation, minimal
# PATH, cwd=$HOME). This wrapper makes invocation deterministic, mirroring
# lims_cron.sh:
#   - uses the project's Python interpreter by ABSOLUTE path (AISYNBIO_PYTHON,
#     baked into the crontab by install_pipeline_cron.sh),
#   - runs from the project root with PYTHONPATH set,
#   - refuses to run (cleanly) if the synbio scratch directory isn't available,
#     so a down mount / wrong host is a no-op rather than an error.
#
# The Globus job also needs GLOBUS_CLIENT_ID in the environment; the installer
# bakes it into the crontab block. The stored refresh token is read from
# ~/.globus_aisynbio_tokens.json by globus_transfer.py itself.
#
# Transfer-completion dependency: the two jobs are scheduled independently, but
# process-od does not blindly trust the clock. The globus job touches a success
# marker (transfer.ok) only when a transfer COMPLETES successfully; process-od
# runs only when that marker is newer than its own last-success marker
# (process.ok). So if the current cycle's transfer is still running, failed, or
# produced nothing new, process-od skips cleanly and picks it up next cycle.
# A non-blocking per-job lock also prevents overlapping runs from piling up.
# Markers/locks live in PIPELINE_STATE_DIR (default ~/.aisynbio_pipeline_state).
#
# Usage (args are passed straight through to the underlying script):
#   ./pipeline_cron.sh globus     <src_endpoint> <dst_endpoint> <src_path> <dst_path> [flags]
#   ./pipeline_cron.sh process-od <data_dir> <plate_layout> <output_dir> <gdrive_folder_id> [flags]
#
set -euo pipefail

# Project root = directory containing this script.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Interpreter (not on PATH in cron). install_pipeline_cron.sh bakes the correct
# per-host path into the crontab as AISYNBIO_PYTHON; the fallback is only for
# direct runs. Keep in sync with lims_cron.sh / lims.sh.
PYTHON="${AISYNBIO_PYTHON:-/scratch/fliu/hub_home/nspahr/.local/share/mamba/envs/aisynbio_env/bin/python}"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') pipeline_cron: $*"; }

if [[ ! -x "$PYTHON" ]]; then
    log "ERROR: interpreter not found or not executable: $PYTHON"
    exit 1
fi

# Synbio scratch directory (transfer destination + OD data live here). If it's
# not present (mount down / wrong host), skip cleanly. SYNBIO_DIR overrides.
SYNBIO_DIR="${SYNBIO_DIR:-/scratch1/fliu/hub_scratch/synbio}"
if [[ ! -d "$SYNBIO_DIR" ]]; then
    log "SKIP: synbio scratch directory not available: $SYNBIO_DIR"
    exit 0
fi

cd "$SCRIPT_DIR"
export PYTHONPATH="$SCRIPT_DIR:${PYTHONPATH:-}"

# State directory holds success markers + per-job locks. Host-local and
# nspahr-owned by default (always available, not on the shared world-writable
# scratch). Override with PIPELINE_STATE_DIR.
STATE_DIR="${PIPELINE_STATE_DIR:-$HOME/.aisynbio_pipeline_state}"
mkdir -p "$STATE_DIR"
TRANSFER_OK="$STATE_DIR/transfer.ok"   # mtime = last SUCCESSFUL transfer
PROCESS_OK="$STATE_DIR/process.ok"     # mtime = last SUCCESSFUL processing

job="${1:-}"
shift || true

# Prevent overlapping runs of the same job. Non-blocking: if a run is already
# in progress (e.g. a slow transfer still going when the next cycle fires),
# skip this cycle rather than pile up. The lock fd stays held until exit.
acquire_lock() {
    exec 9>"$STATE_DIR/$job.lock"
    if ! flock -n 9; then
        log "SKIP: a '$job' run is already in progress"
        exit 0
    fi
}

case "$job" in
    globus)
        acquire_lock
        log "starting globus transfer"
        if "$PYTHON" "$SCRIPT_DIR/aisynbiopipeline/pipeline/globus_transfer.py" transfer "$@"; then
            touch "$TRANSFER_OK"
            log "globus transfer succeeded (marker: $TRANSFER_OK)"
        else
            rc=$?
            log "globus transfer FAILED (exit $rc); success marker NOT updated"
            exit "$rc"
        fi
        ;;
    process-od)
        # Transfer-completion dependency: only process when a transfer has
        # succeeded more recently than the last successful processing.
        if [[ ! -f "$TRANSFER_OK" ]]; then
            log "SKIP: no successful transfer yet ($TRANSFER_OK missing)"
            exit 0
        fi
        if [[ -f "$PROCESS_OK" && ! "$TRANSFER_OK" -nt "$PROCESS_OK" ]]; then
            log "SKIP: no new successful transfer since last processing"
            exit 0
        fi
        acquire_lock
        # Re-check under the lock, in case a concurrent run just finished.
        if [[ -f "$PROCESS_OK" && ! "$TRANSFER_OK" -nt "$PROCESS_OK" ]]; then
            log "SKIP: processing already up to date"
            exit 0
        fi
        log "starting robotic OD processing"
        if "$PYTHON" "$SCRIPT_DIR/aisynbiopipeline/pipeline/process_robotic_od.py" "$@"; then
            touch "$PROCESS_OK"
            log "processing succeeded (marker: $PROCESS_OK)"
        else
            rc=$?
            log "processing FAILED (exit $rc); success marker NOT updated"
            exit "$rc"
        fi
        ;;
    *)
        log "ERROR: unknown job '$job' (expected 'globus' or 'process-od')"
        exit 1
        ;;
esac
