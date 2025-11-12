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

# Check if lims command is available
if ! command -v lims &> /dev/null; then
    echo "Error: 'lims' command not found"
    echo "Please install the package first:"
    echo "  pip install -e ."
    exit 1
fi

# Run the lims command with all provided arguments
exec lims "$@"
