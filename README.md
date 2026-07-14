# AISynbioPipeline

Autonomous lab system for adaptive lab evolution of ADP1.

## Overview

AISynbioPipeline is a framework for managing an autonomous lab system that supports adaptive lab evolution experiments. The system provides:

- **LIMS Integration**: Synchronization between Google Sheets and local SQLite database
- **Workflow Management**: Tools for running and managing lab automation workflows
- **CLI Interface**: Command-line tools for system operations

## Installation

### Prerequisites

- Python 3.11 or higher (Anaconda/Miniconda recommended)
- Google Cloud Platform service account with Google Sheets API access

### Environment Setup (Recommended)

The easiest way to set up the environment is using the provided setup script:

```bash
git clone <repository-url>
cd AISynbioPipeline

# Create conda environment with all dependencies
./setup_env.sh

# Activate the environment
source activate.sh
```

The setup script will:
- Create a conda environment named `aisynbiopipeline`
- Install all required dependencies
- Generate an `activate.sh` script for easy environment activation

### Manual Setup

If you prefer to manage dependencies manually:

```bash
# Using conda
conda env create -f environment.yml
conda activate aisynbiopipeline

# Or using pip
pip install -r requirements.txt
```

**Note**: Installation via `pip install -e .` is optional. The `lims.sh` wrapper script runs the CLI directly without requiring package installation.

## LIMS API

The LIMS API provides a Python interface for synchronizing data from Google Sheets to a local SQLite database.

### Features

- **Automatic Sync**: Continuously monitors Google Sheets and mirrors data locally
- **Soft Deletes**: Marks deleted rows instead of removing them
- **Automatic Archival**: Hourly, daily, weekly, and monthly backups with retention policies
- **Read-Only API**: Query interface for accessing synchronized data

### Configuration

1. Set up Google Sheets API credentials:
   - Create a service account in Google Cloud Platform
   - Download the credentials JSON file
   - Create a `credentials` directory in the project root
   - Place the credentials file as `credentials/service_account.json`

2. Configure the LIMS API:
   - Edit `aisynbiopipeline/limsapi/config.json`
   - Set your spreadsheet ID and other preferences

### Quick Start (CLI)

```bash
# Run a one-off sync
./lims.sh sync

# Install the automatic sync + archive schedule (cron)
./install_cron.sh

# Query data
./lims.sh query samples --filter status=active
```

### Quick Start (Python API)

```python
# Add the project directory to your Python path or run from project root
from aisynbiopipeline.limsapi import sync_all_sheets, query_table

# Run a one-off sync (automatic syncing is handled by cron; see below)
sync_all_sheets()

# Query data
results = query_table('samples', filters={'status': 'active'})
for row in results:
    print(row)
```

### CLI Usage

The `lims` command provides access to all LIMS functionality.

**Wrapper Script**: Use `lims.sh` which automatically activates your Python environment and runs the CLI:

```bash
./lims.sh sync
./lims.sh daemon start
./lims.sh query samples --filter status=active
```

The wrapper script will:
- Check if a virtual environment is already activated
- Automatically source `activate.sh` if found and not activated
- Run the LIMS CLI directly with Python (no installation required)

#### Sync Operations

Automatic syncing and archiving run via **cron**, not a long-lived daemon. Each
run is an independent, lock-guarded process, so nothing has to stay alive and the
schedule survives reboots (cron re-reads it automatically).

```bash
# Run a manual sync now
./lims.sh sync

# Install / update the automatic schedule (sync every 2h + hourly/daily/weekly/
# monthly archives + daily retention cleanup)
./install_cron.sh

# Show what would be installed, or remove the schedule
./install_cron.sh --show
./install_cron.sh --uninstall

# See the installed schedule and check status
crontab -l
./lims.sh status
```

**Changing the schedule:** edit the `CRON_*` variables at the top of
`install_cron.sh` and re-run it (idempotent). **Changing archive retention:**
edit the `archive` section of `aisynbiopipeline/limsapi/config.json`.

> The old `./lims.sh daemon start/stop` commands are deprecated — they ran a
> background thread that died when the command exited and never synced reliably.
> They now print a pointer to the cron workflow. All sync/archive operations
> (manual or scheduled) share a single on-disk lock, so two can never run at once.


#### Query Operations

```bash
# List all tables
lims list
lims list --count  # Show row counts

# Get table schema
lims schema samples

# Query a table
lims query samples
lims query samples --filter status=active
lims query samples --filter status=active --columns id,name,date
lims query samples --limit 10 --offset 20
lims query samples --order-by date --desc
lims query samples --format json  # Output as JSON
lims query samples --format csv   # Output as CSV
```

#### Archive Operations

```bash
# Create a manual archive
lims archive create

# List all archives
lims archive list
lims archive list --type daily

# Restore from archive
lims archive restore lims_daily_20231115.db.gz
lims archive restore lims_daily_20231115.db.gz --force

# Cleanup old archives
lims archive cleanup
```

### Python API

#### Sync Functions

```python
from aisynbiopipeline.limsapi import (
    sync_all_sheets,
    start_sync_daemon,
    stop_sync_daemon,
    get_sync_status
)

# Manual sync
result = sync_all_sheets()
print(f"Synced {result['tables_synced']} tables")

# Background daemon
start_sync_daemon()  # Starts in background
status = get_sync_status()
stop_sync_daemon()
```

#### Query Functions

```python
from aisynbiopipeline.limsapi import (
    list_tables,
    get_table_schema,
    query_table,
    get_all_records,
    search_table
)

# List tables
tables = list_tables()

# Get schema
schema = get_table_schema('samples')

# Query with filters
results = query_table(
    'samples',
    filters={'status': 'active', 'type': 'control'},
    columns=['id', 'name', 'date'],
    limit=100,
    order_by='date',
    order_desc=True
)

# Search
results = search_table('samples', 'name', 'ADP1')
```

#### Archive Functions

```python
from aisynbiopipeline.limsapi import (
    create_archive,
    list_archives,
    restore_archive,
    cleanup_archives
)

# Create archive
archive_path = create_archive('manual')

# List archives
archives = list_archives()
for archive in archives:
    print(f"{archive['filename']}: {archive['timestamp']}")

# Restore
restore_archive('lims_daily_20231115.db.gz')

# Cleanup
deleted = cleanup_archives()
print(f"Deleted {sum(deleted.values())} archives")
```

## Jupyter Notebooks

Example notebooks are provided in the `notebooks/` directory to help you get started with the LIMS API.

### Running Notebooks

```bash
# Activate the environment
source activate.sh

# Start Jupyter notebook
jupyter notebook notebooks/
```

### Available Notebooks

- **APIExamples.ipynb** - Comprehensive examples of using the LIMS API to query data

The notebooks use `util_simple.py` which provides helper functions for:
- `query_lims()` - Query tables and get pandas DataFrames
- `search_lims()` - Search for records containing text
- `get_lims_tables()` - List all available tables
- `get_lims_schema()` - Get table structure
- `count_lims_rows()` - Count rows in a table

## Configuration

### LIMS Configuration

Edit `aisynbiopipeline/limsapi/config.json`:

```json
{
  "google_sheets": {
    "spreadsheet_id": "your-spreadsheet-id",
    "credentials_file": "credentials/service_account.json"
  },
  "database": {
    "db_path": "aisynbiopipeline/limsapi/lims_mirror.db",
    "archive_path": "aisynbiopipeline/limsapi/archive/"
  },
  "sync": {
    "interval_minutes": 10,
    "enabled": true,
    "log_level": "INFO"
  },
  "archive": {
    "hourly_retention": 24,
    "daily_retention": 7,
    "weekly_retention": 4,
    "monthly_retention": -1
  }
}
```

## Development

### Running Tests

```bash
pytest
pytest --cov=aisynbiopipeline
```

### Code Quality

```bash
# Format code
black aisynbiopipeline

# Lint
flake8 aisynbiopipeline

# Type checking
mypy aisynbiopipeline
```

## Task System (Celery)

The AISynbioPipeline uses Celery for distributed task execution. Workers can be deployed anywhere with access to the Redis broker, enabling scalable computational analyses.

### Features

- **Distributed Task Queue**: Celery-based task management with Redis broker
- **Scalable Workers**: Deploy workers anywhere (local, remote, containers)
- **KBase Integration**: Upload/download sequencing reads to/from KBase
- **Task Monitoring**: Web-based monitoring via Flower dashboard
- **Standardized Data Structure**: Organized folder hierarchy for sequencing libraries and analysis results

### Prerequisites

The task system requires:
- **Redis server**: Running at `redis://bioseed_redis:6379/10` (configurable via `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND`)
- **Celery**: Installed via environment.yml
- **Flower** (optional): For web-based monitoring

### Quick Start

```bash
# Start a worker
./aisynbio.sh worker

# In another terminal, submit a task
./aisynbio.sh template kbase_io.download -o download.json
# Edit download.json with your parameters
./aisynbio.sh submit kbase_io.download download.json

# Check task status
./aisynbio.sh status <task-id>

# Get task result
./aisynbio.sh result <task-id>

# Open monitoring dashboard
./aisynbio.sh monitor
```

### Available Tasks

#### kbase_io.download

Download sequencing reads from KBase to local storage.

**Input JSON:**
```json
{
  "kbase_ref": "workspace/object_name",
  "library_name": "example_library_ABC",
  "sample_name": "sample_001",
  "read_type": "short",
  "data_root": "ai_synbio_data"
}
```

**Output JSON:**
```json
{
  "success": true,
  "kbase_ref": "workspace/object_name",
  "library_name": "example_library_ABC",
  "sample_name": "sample_001",
  "read_type": "short",
  "output_files": ["ai_synbio_data/.../received/sample_001_R1.fastq", "..."],
  "placeholders": ["...sample_001_R1.fastq.kbase_placeholder.json", "..."],
  "metadata": {
    "start_time": "2025-11-17T10:00:00",
    "end_time": "2025-11-17T10:05:00",
    "duration_seconds": 300,
    "files": [{"path": "...", "size": 12345678}]
  },
  "task_id": "abc-123-def",
  "output_file": "download_result.json"
}
```

#### kbase_io.upload

Upload local sequencing reads to KBase.

**Input JSON:**
```json
{
  "local_path": "path/to/reads.fastq",
  "workspace": "workspace_name",
  "object_name": "object_name",
  "library_name": "example_library_ABC",
  "sample_name": "sample_001",
  "read_type": "short"
}
```

**Output JSON:**
```json
{
  "success": true,
  "kbase_ref": "workspace_name/object_name",
  "library_name": "example_library_ABC",
  "sample_name": "sample_001",
  "read_type": "short",
  "local_path": "path/to/reads.fastq",
  "workspace": "workspace_name",
  "object_name": "object_name",
  "placeholder": "path/to/reads.fastq.kbase_placeholder.json",
  "metadata": {
    "start_time": "2025-11-17T10:00:00",
    "end_time": "2025-11-17T10:05:00",
    "duration_seconds": 300,
    "file_size": 12345678
  },
  "task_id": "abc-123-def",
  "output_file": "upload_result.json"
}
```

### Data Directory Structure

The task system uses a standardized directory structure for experimental data:

```
ai_synbio_data/
├── experimental_data/
│   ├── sequencing_libraries/
│   │   └── <library_name>/
│   │       ├── <library_name>_short_reads/
│   │       │   ├── received/             # Raw data from sequencing
│   │       │   ├── trimmed/              # Quality-trimmed reads
│   │       │   ├── breseq/               # Breseq analysis results
│   │       │   │   └── breseq_<params>/  # Parameter-specific results
│   │       │   └── mapped/               # Mapped reads
│   │       │       └── mapped_<params>/  # Parameter-specific results
│   │       ├── <library_name>_long_reads/
│   │       │   ├── received/             # Raw data from sequencing
│   │       │   └── filtered/             # Filtered reads
│   │       └── <library_name>_hybrid_assemblies/
│   ├── proteomics_data/
│   └── robotic_OD_data/
└── reference_data/
    ├── reference_genomes/
    └── blast_dbs/
```

**Naming Conventions:**
- Library base folders: `<library_name>/`
- Read type folders: `<library_name>_short_reads/`, `<library_name>_long_reads/`
- Breseq folders: `breseq_<ref_genome>_<pop|con>_<coverage>_<other_params>/`
  - Examples: `breseq_ADP1_pop_100x/`, `breseq_ADP1_con/`
- Mapped folders: `mapped_<params>/`
- Hybrid assemblies: `<library_name>_hybrid_assemblies/`

#### Setting Up Data Structure

```bash
# Set up the root data directory
python aisynbiopipeline/data/setup_data_structure.py --root ai_synbio_data

# Set up with reference data directories
python aisynbiopipeline/data/setup_data_structure.py --root ai_synbio_data --reference

# Create a library structure
python aisynbiopipeline/data/setup_data_structure.py \
  --root ai_synbio_data \
  --library my_library_ABC

# Create multiple libraries at once
python aisynbiopipeline/data/setup_data_structure.py \
  --root ai_synbio_data \
  --library lib1 lib2 lib3

# Create only short read directories
python aisynbiopipeline/data/setup_data_structure.py \
  --root ai_synbio_data \
  --library my_library_ABC \
  --read-types short
```

### CLI Commands

```bash
# Start a worker
./aisynbio.sh worker
./aisynbio.sh worker --concurrency 4  # Start with 4 concurrent workers

# List available tasks
./aisynbio.sh tasks

# Create a task template
./aisynbio.sh template kbase_io.download -o my_download.json
./aisynbio.sh template kbase_io.upload -o my_upload.json

# Submit a task
./aisynbio.sh submit kbase_io.download my_download.json

# Check task status
./aisynbio.sh status <task-id>

# Get task result
./aisynbio.sh result <task-id>
./aisynbio.sh result <task-id> -o result.json  # Save to file

# Cancel a running task
./aisynbio.sh cancel <task-id>

# Open Flower monitoring dashboard
./aisynbio.sh monitor
```

### Python API

#### Submitting Tasks

```python
from celery import Celery
import os

# Create Celery client
client = Celery(
    'client',
    broker=os.getenv('CELERY_BROKER_URL', 'redis://bioseed_redis:6379/10'),
    backend=os.getenv('CELERY_RESULT_BACKEND', 'redis://bioseed_redis:6379/10')
)

# Submit a task
result = client.send_task('kbase_io.download', args=['path/to/input.json'])

# Get task ID
task_id = result.id

# Check if complete
if result.ready():
    output = result.get()
    print(output)
```

#### Accessing Workflow Functions

```python
from aisynbiopipeline.workflows.kbase_io import (
    download_reads_from_kbase,
    upload_reads_to_kbase
)

# Use workflow functions directly (without Celery)
result = download_reads_from_kbase(
    kbase_ref='workspace/object',
    library_name='my_library',
    sample_name='sample_001',
    read_type='short'
)
```

### Creating Custom Tasks

To create a new task type:

1. **Create a workflow function** in `aisynbiopipeline/workflows/` (Celery-agnostic)
2. **Create a Celery task** in `aisynbiopipeline/tasks/` that wraps the workflow
3. **Update task registry** in `aisynbiopipeline/tasks/__init__.py`
4. **Update CLI** in `aisynbiopipeline/cli/aisynbio.py` to include the new task

Example:

```python
# 1. Create workflow/my_analysis.py
def run_analysis(input_file: str, output_dir: str) -> dict:
    # Your analysis logic here (no Celery imports)
    return {
        'success': True,
        'output_files': [...],
        'metadata': {...}
    }

# 2. Create tasks/my_tasks.py
from ..celery_app import app
from ..workflows.my_analysis import run_analysis

@app.task(bind=True, name='my_analysis.run')
def run_my_analysis(self, json_input_path: str) -> dict:
    # Load JSON, call workflow function, return result
    pass
```

### Configuration

Set Redis connection via environment variables:

```bash
export CELERY_BROKER_URL="redis://your-redis-host:6379/10"
export CELERY_RESULT_BACKEND="redis://your-redis-host:6379/10"
```

Or use the default: `redis://bioseed_redis:6379/10`

## Architecture

```
aisynbiopipeline/
├── cli/              # Command-line interfaces
│   ├── lims.py           # LIMS API CLI
│   └── aisynbio.py       # Celery task management CLI
├── limsapi/          # LIMS API modules
│   ├── config.py         # Configuration management
│   ├── sheets.py         # Google Sheets integration
│   ├── database.py       # SQLite database management
│   ├── sync.py           # Synchronization daemon
│   ├── archive.py        # Archive management
│   └── query.py          # Query API
├── tasks/            # Celery task definitions
│   └── kbase_tasks.py    # KBase I/O tasks
├── workflows/        # Analysis workflows (Celery-agnostic)
│   ├── kbase_io.py       # KBase download/upload logic
│   └── blast.py          # BLAST analysis workflows
├── data/             # Data management utilities
│   ├── setup_data_structure.py  # Data directory setup
│   └── __init__.py              # Path helper functions
└── celery_app.py     # Celery application configuration
```

## License

MIT License

## Support

For issues and questions, please open an issue on GitHub.
