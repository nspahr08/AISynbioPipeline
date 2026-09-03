#!/bin/bash
#
# Install (or remove) the AISynbio pipeline schedule (Globus transfer +
# robotic OD processing) in the current user's crontab. Idempotent:
# re-running replaces the managed block, so it never duplicates entries.
#
# Usage:
#   ./install_pipeline_cron.sh              # install / update the schedule
#   ./install_pipeline_cron.sh --uninstall  # remove the schedule
#   ./install_pipeline_cron.sh --show       # print what would be installed
#
# BEFORE INSTALLING: fill in the job-argument variables in the "JOB ARGUMENTS"
# block below (the ones set to CHANGE_ME) and export GLOBUS_CLIENT_ID. To change
# WHEN things run, edit the CRON_* variables. Then re-run this script.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WRAPPER="$SCRIPT_DIR/pipeline_cron.sh"

# --- Schedule (standard cron: minute hour day-of-month month day-of-week) ----
# CRON_GLOBUS="0,10,20,30,40,50 * * * *"       # Globus transfer at 0,10,20,30,40,50 min of every hour (for testing)
# CRON_PROCESS_OD="5,15,25,35,45,55 * * * *"  # robotic OD processing at 5,15,25,35,45,55 min of every hour (for testing)
CRON_GLOBUS="0 */2 * * *"       # Globus transfer at :00 of every even hour
CRON_PROCESS_OD="30 */2 * * *"  # robotic OD processing at :30 of every even hour
# -----------------------------------------------------------------------------

# === JOB ARGUMENTS (EDIT THESE) ==============================================
# Globus transfer: source_endpoint dest_endpoint source_path dest_path
GLOBUS_SOURCE_ENDPOINT="391a895a-05b8-4e6a-a48a-fde1aa727769"  # source collection UUID
GLOBUS_DEST_ENDPOINT="local"                                    # 'local' = this host's GCP endpoint
GLOBUS_SOURCE_PATH="/REAL_RUNS/LiveExperimentDataOutput/"                                  # e.g. /path/on/source/
GLOBUS_DEST_PATH="/scratch1/fliu/hub_scratch/synbio/ai_synbio_data/experimental_data/downloads/TFMN5"                                    # under /scratch1/fliu/hub_scratch/synbio/
GLOBUS_EXTRA_FLAGS="--poll-interval 300"                        # e.g. --poll-interval 300, --no-wait

# Globus Native App Client ID (needed by globus_transfer.py). Captured from the
# environment at install time; export it before running this script.
GLOBUS_CLIENT_ID="${GLOBUS_CLIENT_ID:-52c5931a-75b5-480c-8c0c-1c28a69817e4}"

# Robotic OD processing: data_dir plate_layout output_dir gdrive_folder_id
OD_DATA_DIR="/scratch1/fliu/hub_scratch/synbio/ai_synbio_data/experimental_data/downloads/TFMN5"          # directory with robotic OD .txt files
# OD_PLATE_LAYOUT="-"
OD_PLATE_LAYOUT="/scratch1/fliu/hub_scratch/nspahr/tmp/TFMN5-plate_layout_9-2.csv"      # path to plate_layout.csv
OD_OUTPUT_DIR="/scratch1/fliu/hub_scratch/synbio/ai_synbio_data/experimental_data/downloads/testing_od_transfer_and_processing"        # where processed CSV + plots are written
OD_GDRIVE_FOLDER_ID="18lNLMIsAYf5X5ViiVmMQj2L78iU9eCi5"  # Google Drive folder ID to upload results to
OD_EXTRA_FLAGS=""                # e.g. --first-reading-is-blank, --skip-inoculation
# =============================================================================

# Log for cron stdout/stderr (each script also writes aisynbiopipeline/pipeline/pipeline.log).
SYNBIO_DIR="${SYNBIO_DIR:-/scratch1/fliu/hub_scratch/synbio}"
CRON_LOG="$SYNBIO_DIR/pipeline_cron.log"

# Stored Globus refresh token (written by `globus_transfer.py login`).
GLOBUS_TOKEN_FILE="$HOME/.globus_aisynbio_tokens.json"

# Interpreter baked into the crontab so the wrapper uses this host's env. Pick
# the first candidate that can import the pipeline deps, so a bare invocation
# (no env activated) can't silently bake a Python that lacks them. Override with
# AISYNBIO_PYTHON=/path/to/python.
_DEP_CHECK='import globus_sdk, pandas, matplotlib'
_ENV_PYTHON="/scratch/fliu/hub_home/nspahr/.local/share/mamba/envs/aisynbio_env/bin/python"
PYTHON_BIN=""
for _cand in "${AISYNBIO_PYTHON:-}" "$(command -v python 2>/dev/null || true)" "$_ENV_PYTHON"; do
    [[ -n "$_cand" && -x "$_cand" ]] || continue
    if "$_cand" -c "$_DEP_CHECK" >/dev/null 2>&1; then
        PYTHON_BIN="$_cand"
        break
    fi
done

BEGIN_MARKER="# >>> AISYNBIO PIPELINE (managed by install_pipeline_cron.sh) >>>"
END_MARKER="# <<< AISYNBIO PIPELINE (managed by install_pipeline_cron.sh) <<<"

build_block() {
    cat <<EOF
$BEGIN_MARKER
SHELL=/bin/bash
PATH=/usr/bin:/bin:/usr/sbin:/sbin
MAILTO=""
AISYNBIO_PYTHON=$PYTHON_BIN
GLOBUS_CLIENT_ID=$GLOBUS_CLIENT_ID
$CRON_GLOBUS $WRAPPER globus $GLOBUS_SOURCE_ENDPOINT $GLOBUS_DEST_ENDPOINT $GLOBUS_SOURCE_PATH $GLOBUS_DEST_PATH $GLOBUS_EXTRA_FLAGS >> $CRON_LOG 2>&1
$CRON_PROCESS_OD $WRAPPER process-od $OD_DATA_DIR $OD_PLATE_LAYOUT $OD_OUTPUT_DIR $OD_GDRIVE_FOLDER_ID $OD_EXTRA_FLAGS >> $CRON_LOG 2>&1
$END_MARKER
EOF
}

# Current crontab with any existing managed block stripped out.
current_without_block() {
    crontab -l 2>/dev/null | sed "\|$BEGIN_MARKER|,\|$END_MARKER|d" || true
}

# Verify no required job argument is still a placeholder / empty.
validate_args() {
    local missing=()
    local name
    for name in GLOBUS_SOURCE_ENDPOINT GLOBUS_SOURCE_PATH GLOBUS_DEST_PATH \
                GLOBUS_CLIENT_ID OD_DATA_DIR OD_PLATE_LAYOUT OD_OUTPUT_DIR \
                OD_GDRIVE_FOLDER_ID; do
        local val="${!name}"
        if [[ -z "$val" || "$val" == "CHANGE_ME" ]]; then
            missing+=("$name")
        fi
    done
    if (( ${#missing[@]} > 0 )); then
        echo "Error: these job arguments are unset (edit the JOB ARGUMENTS block, or export GLOBUS_CLIENT_ID):" >&2
        printf '  - %s\n' "${missing[@]}" >&2
        exit 1
    fi
}

case "${1:-install}" in
    --show)
        build_block
        ;;
    --uninstall)
        current_without_block | crontab -
        echo "Removed the AISynbio pipeline managed cron block."
        ;;
    install|"")
        if [[ ! -x "$WRAPPER" ]]; then
            echo "Error: wrapper not executable: $WRAPPER" >&2
            echo "Run: chmod +x $WRAPPER" >&2
            exit 1
        fi
        if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
            echo "Error: found no Python that can import the pipeline deps" >&2
            echo "($_DEP_CHECK)." >&2
            echo "Activate the project env first, or run:" >&2
            echo "    AISYNBIO_PYTHON=/path/to/env/bin/python ./install_pipeline_cron.sh" >&2
            exit 1
        fi
        validate_args
        if [[ ! -d "$SYNBIO_DIR" ]]; then
            echo "Error: synbio scratch directory not found: $SYNBIO_DIR" >&2
            echo "Set SYNBIO_DIR or check the mount, then re-run." >&2
            exit 1
        fi
        if [[ ! -f "$GLOBUS_TOKEN_FILE" ]]; then
            echo "Warning: no Globus token at $GLOBUS_TOKEN_FILE." >&2
            echo "The transfer job will fail until you run:" >&2
            echo "    GLOBUS_CLIENT_ID=$GLOBUS_CLIENT_ID $PYTHON_BIN aisynbiopipeline/pipeline/globus_transfer.py login --data-access $GLOBUS_SOURCE_ENDPOINT" >&2
        fi
        echo "Using interpreter: $PYTHON_BIN"
        echo "Cron log:          $CRON_LOG"
        { current_without_block; build_block; } | crontab -
        echo "Installed the AISynbio pipeline schedule:"
        echo
        build_block | grep -vE '^(#|SHELL|PATH|MAILTO|AISYNBIO_PYTHON|GLOBUS_CLIENT_ID)' | sed 's/^/  /'
        echo
        echo "Verify with: crontab -l"
        echo "Logs:        $CRON_LOG  and  aisynbiopipeline/pipeline/pipeline.log"
        ;;
    *)
        echo "Usage: $0 [install|--uninstall|--show]" >&2
        exit 1
        ;;
esac
