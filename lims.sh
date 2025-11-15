#!/bin/bash
#
# LIMS CLI Wrapper Script
#
# This script automatically activates the Python environment (if needed)
# before running LIMS CLI commands.
#
# Usage:
#   ./lims.sh sync
#   ./lims.sh daemon start
#   ./lims.sh query samples --filter status=active
#

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Path to activate script
ACTIVATE_SCRIPT="$SCRIPT_DIR/activate.sh"

# Function to check if virtual environment is activated
is_venv_activated() {
    # Check if VIRTUAL_ENV is set or if we're in a conda environment
    if [[ -n "$VIRTUAL_ENV" ]] || [[ -n "$CONDA_DEFAULT_ENV" ]]; then
        return 0
    fi
    return 1
}

# Activate environment if not already activated
if ! is_venv_activated; then
    if [[ -f "$ACTIVATE_SCRIPT" ]]; then
        echo "Activating environment..."
        source "$ACTIVATE_SCRIPT"
    else
        echo "Warning: activate.sh not found at $ACTIVATE_SCRIPT"
        echo "Attempting to run LIMS CLI without environment activation..."
    fi
fi

# Path to the LIMS CLI Python module
LIMS_CLI="$SCRIPT_DIR/aisynbiopipeline/cli/lims.py"

# Check if the LIMS CLI module exists
if [[ ! -f "$LIMS_CLI" ]]; then
    echo "Error: LIMS CLI module not found at $LIMS_CLI"
    exit 1
fi

# Check if python is available
if ! command -v python &> /dev/null; then
    echo "Error: 'python' command not found"
    echo "Please ensure Python is installed and in your PATH"
    exit 1
fi

# Add the project root to PYTHONPATH so Python can find the aisynbiopipeline module
export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"

# Run the LIMS CLI directly with Python
exec python "$LIMS_CLI" "$@"
