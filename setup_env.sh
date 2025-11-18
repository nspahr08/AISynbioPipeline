#!/bin/bash
#
# Environment Setup Script for AISynbioPipeline
#
# This script creates a conda environment and generates an activate.sh script
# for easy activation in the lims.sh wrapper.
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_NAME="aisynbiopipeline"

echo "========================================="
echo "AISynbioPipeline Environment Setup"
echo "========================================="
echo ""

# Check if conda is available
if ! command -v conda &> /dev/null; then
    echo "Error: conda is not installed or not in PATH"
    echo "Please install Anaconda or Miniconda first"
    exit 1
fi

# Check if environment already exists
if conda env list | grep -q "^${ENV_NAME} "; then
    echo "Environment '${ENV_NAME}' already exists."
    read -p "Do you want to remove and recreate it? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Removing existing environment..."
        conda env remove -n "${ENV_NAME}" -y
    else
        echo "Using existing environment."
        SKIP_CREATE=1
    fi
fi

# Create environment from yml file
if [[ -z "$SKIP_CREATE" ]]; then
    echo "Creating conda environment from environment.yml..."
    conda env create -f "${SCRIPT_DIR}/environment.yml"
    echo "✓ Environment created successfully"
fi

# Get the conda base path
CONDA_BASE=$(conda info --base)

# Determine conda initialization script
if [[ -f "${CONDA_BASE}/etc/profile.d/conda.sh" ]]; then
    CONDA_INIT="${CONDA_BASE}/etc/profile.d/conda.sh"
else
    echo "Error: Could not find conda initialization script"
    exit 1
fi

# Create activate.sh script
echo ""
echo "Creating activate.sh script..."

cat > "${SCRIPT_DIR}/activate.sh" <<'EOF'
#!/bin/bash
# Auto-generated activation script for AISynbioPipeline environment

# Get conda base directory
CONDA_BASE=$(conda info --base 2>/dev/null)

if [[ -z "$CONDA_BASE" ]]; then
    echo "Error: conda not found"
    return 1
fi

# Source conda initialization
if [[ -f "${CONDA_BASE}/etc/profile.d/conda.sh" ]]; then
    source "${CONDA_BASE}/etc/profile.d/conda.sh"
else
    echo "Error: Could not find conda initialization script"
    return 1
fi

# Activate the environment
conda activate aisynbiopipeline

if [[ $? -eq 0 ]]; then
    echo "Activated aisynbiopipeline environment"
else
    echo "Error: Failed to activate aisynbiopipeline environment"
    return 1
fi
EOF

chmod +x "${SCRIPT_DIR}/activate.sh"

echo "✓ activate.sh created successfully"
echo ""
echo "========================================="
echo "Setup Complete!"
echo "========================================="
echo ""
echo "To activate the environment:"
echo "  source activate.sh"
echo ""
echo "To use with lims.sh wrapper:"
echo "  ./lims.sh sync"
echo "  (will automatically activate the environment)"
echo ""
echo "To start Jupyter notebook:"
echo "  source activate.sh"
echo "  jupyter notebook notebooks/"
echo ""
