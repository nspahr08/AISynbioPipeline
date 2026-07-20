#!/bin/bash
#
# Install (or remove) the LIMS sync + archive schedule in the current user's
# crontab. Idempotent: re-running replaces the managed block, so it never
# duplicates entries.
#
# Usage:
#   ./install_cron.sh              # install / update the schedule
#   ./install_cron.sh --uninstall  # remove the schedule
#   ./install_cron.sh --show       # print what would be installed
#
# To change WHEN things run, edit the CRON_* variables below and re-run this
# script. To change how many/long archives are kept, edit the `archive`
# retention values in aisynbiopipeline/limsapi/config.json (no cron change).
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WRAPPER="$SCRIPT_DIR/lims_cron.sh"
CONFIG_JSON="$SCRIPT_DIR/aisynbiopipeline/limsapi/config.json"

# Interpreter baked into the crontab so lims_cron.sh uses this host's env.
# Pick the first candidate that can actually import the project deps, so a bare
# `./install_cron.sh` (no env activated) can't silently bake a Python that lacks
# pandas/gspread. Override explicitly with LIMS_PYTHON=/path/to/python.
_DEP_CHECK='import pandas, gspread, jsonschema, googleapiclient'
_ENV_PYTHON="/scratch/fliu/hub_home/nspahr/.local/share/mamba/envs/aisynbio_env/bin/python"
PYTHON_BIN=""
for _cand in "${LIMS_PYTHON:-}" "$(command -v python 2>/dev/null || true)" "$_ENV_PYTHON"; do
    [[ -n "$_cand" && -x "$_cand" ]] || continue
    if "$_cand" -c "$_DEP_CHECK" >/dev/null 2>&1; then
        PYTHON_BIN="$_cand"
        break
    fi
done

# Shared data dir = parent of db_path in config.json (this host's mountpoint for
# the shared filesystem). Used to place the cron log; validated before install.
DATA_DIR=""
if [[ -x "$PYTHON_BIN" && -f "$CONFIG_JSON" ]]; then
    DATA_DIR="$("$PYTHON_BIN" -c "import json,os;print(os.path.dirname(json.load(open('$CONFIG_JSON'))['database']['db_path']))" 2>/dev/null || true)"
fi
CRON_LOG="${DATA_DIR:-/storage/synbio}/cron.log"

# --- Schedule (standard cron: minute hour day-of-month month day-of-week) ----
CRON_SYNC="30 */2 * * *"    # sync every 2 hours at :30 (off the archive minutes)
CRON_DAILY="5 0 * * *"      # daily archive at 00:05
CRON_WEEKLY="10 0 * * 0"    # weekly archive Sunday 00:10
CRON_MONTHLY="15 0 1 * *"   # monthly archive on the 1st at 00:15
CRON_CLEANUP="30 0 * * *"   # retention cleanup daily at 00:30
# -----------------------------------------------------------------------------

BEGIN_MARKER="# >>> AISYNBIO LIMS (managed by install_cron.sh) >>>"
END_MARKER="# <<< AISYNBIO LIMS (managed by install_cron.sh) <<<"

build_block() {
    cat <<EOF
$BEGIN_MARKER
SHELL=/bin/bash
PATH=/usr/bin:/bin:/usr/sbin:/sbin
MAILTO=""
LIMS_PYTHON=$PYTHON_BIN
$CRON_SYNC $WRAPPER sync >> $CRON_LOG 2>&1
$CRON_DAILY $WRAPPER archive create --type daily >> $CRON_LOG 2>&1
$CRON_WEEKLY $WRAPPER archive create --type weekly >> $CRON_LOG 2>&1
$CRON_MONTHLY $WRAPPER archive create --type monthly >> $CRON_LOG 2>&1
$CRON_CLEANUP $WRAPPER archive cleanup >> $CRON_LOG 2>&1
$END_MARKER
EOF
}

# Current crontab with any existing managed block stripped out.
current_without_block() {
    crontab -l 2>/dev/null | sed "\|$BEGIN_MARKER|,\|$END_MARKER|d" || true
}

case "${1:-install}" in
    --show)
        build_block
        ;;
    --uninstall)
        current_without_block | crontab -
        echo "Removed the LIMS managed cron block."
        ;;
    install|"")
        if [[ ! -x "$WRAPPER" ]]; then
            echo "Error: wrapper not executable: $WRAPPER" >&2
            echo "Run: chmod +x $WRAPPER" >&2
            exit 1
        fi
        if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
            echo "Error: found no Python that can import the project deps" >&2
            echo "($_DEP_CHECK)." >&2
            echo "Activate the project env first, or run:" >&2
            echo "    LIMS_PYTHON=/path/to/env/bin/python ./install_cron.sh" >&2
            exit 1
        fi
        if [[ -z "$DATA_DIR" || ! -d "$DATA_DIR" ]]; then
            echo "Error: shared data directory not found: '${DATA_DIR:-<none>}'" >&2
            echo "Check database.db_path in $CONFIG_JSON and that the mount is up." >&2
            exit 1
        fi
        echo "Using interpreter: $PYTHON_BIN"
        echo "Data directory:    $DATA_DIR"
        { current_without_block; build_block; } | crontab -
        echo "Installed the LIMS sync + archive schedule:"
        echo
        build_block | grep -vE '^(#|SHELL|PATH|MAILTO)' | sed 's/^/  /'
        echo
        echo "Verify with: crontab -l"
        echo "Logs:        $CRON_LOG  and  the sync log in config.json"
        ;;
    *)
        echo "Usage: $0 [install|--uninstall|--show]" >&2
        exit 1
        ;;
esac
