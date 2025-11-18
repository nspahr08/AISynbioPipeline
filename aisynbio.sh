#!/bin/bash
#
# AISynbioPipeline Celery Task Management CLI Wrapper
#
# This script activates the conda environment and runs the aisynbio CLI.
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLI_MODULE="aisynbiopipeline.cli.aisynbio"

# Check if conda environment is active
if [[ -z "$CONDA_DEFAULT_ENV" ]] || [[ "$CONDA_DEFAULT_ENV" != "aisynbiopipeline" ]]; then
    # Try to activate the environment
    if [[ -f "$SCRIPT_DIR/activate.sh" ]]; then
        echo "Activating aisynbiopipeline environment..."
        source "$SCRIPT_DIR/activate.sh"
    else
        echo "Error: conda environment not active and activate.sh not found"
        echo "Please run: source activate.sh"
        exit 1
    fi
fi

# Set PYTHONPATH to include the project root
export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"

# Run the CLI
exec python -m "$CLI_MODULE" "$@"
