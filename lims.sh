#!/bin/bash
#
# LIMS CLI Wrapper Script
#
# This script resolves the project's Python interpreter (no manual environment
# activation required) and runs the LIMS CLI. Scheduled syncing/archiving is
# handled by cron (see install_cron.sh), not a daemon.
#
# Usage:
#   ./lims.sh sync
#   ./lims.sh status
#   ./lims.sh query samples --filter status=active
#

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Absolute path to the project's micromamba interpreter (aisynbio_env), which is
# NOT on PATH in non-interactive shells. Keep in sync with lims_cron.sh.
PROJECT_PYTHON="/scratch/fliu/hub_home/nspahr/.local/share/mamba/envs/aisynbio_env/bin/python"

# Pick the interpreter: prefer the project env; if that's missing, fall back to
# an already-activated env's python, then to whatever `python` is on PATH.
if [[ -x "$PROJECT_PYTHON" ]]; then
    PYTHON="$PROJECT_PYTHON"
elif [[ -n "${CONDA_PREFIX:-}" && -x "$CONDA_PREFIX/bin/python" ]]; then
    PYTHON="$CONDA_PREFIX/bin/python"
elif command -v python &> /dev/null; then
    PYTHON="$(command -v python)"
else
    echo "Error: no Python interpreter found (looked for $PROJECT_PYTHON)" >&2
    exit 1
fi

# Path to the LIMS CLI Python module
LIMS_CLI="$SCRIPT_DIR/aisynbiopipeline/cli/lims.py"

# Check if the LIMS CLI module exists
if [[ ! -f "$LIMS_CLI" ]]; then
    echo "Error: LIMS CLI module not found at $LIMS_CLI"
    exit 1
fi

# Add the project root to PYTHONPATH so Python can find the aisynbiopipeline module
export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"

# Run the LIMS CLI directly with the resolved interpreter
exec "$PYTHON" "$LIMS_CLI" "$@"
