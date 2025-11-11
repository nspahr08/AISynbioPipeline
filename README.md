# AISynbioPipeline

Autonomous lab system for adaptive lab evolution of ADP1.

## Overview

AISynbioPipeline is a framework for managing an autonomous lab system that supports adaptive lab evolution experiments. The system provides:

- **LIMS Integration**: Synchronization between Google Sheets and local SQLite database
- **Workflow Management**: Tools for running and managing lab automation workflows
- **CLI Interface**: Command-line tools for system operations

## Installation

### Prerequisites

- Python 3.8 or higher
- Google Cloud Platform service account with Google Sheets API access

### Install from source

```bash
git clone <repository-url>
cd AISynbioPipeline
pip install -e .
```

### Install dependencies

```bash
pip install -r requirements.txt
```

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
   - Place it in the project root as `service_account.json`

2. Configure the LIMS API:
   - Edit `aisynbiopipeline/limsapi/config.json`
   - Set your spreadsheet ID and other preferences

### Quick Start

```python
from aisynbiopipeline.limsapi import start_sync_daemon, query_table

# Start the background sync daemon
start_sync_daemon()

# Query data
results = query_table('samples', filters={'status': 'active'})
for row in results:
    print(row)
```

### CLI Usage

The `lims` command provides access to all LIMS functionality:

#### Sync Operations

```bash
# Run a manual sync
lims sync

# Start the background sync daemon
lims daemon start

# Stop the daemon
lims daemon stop

# Check sync status
lims status
```

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

## Configuration

### LIMS Configuration

Edit `aisynbiopipeline/limsapi/config.json`:

```json
{
  "google_sheets": {
    "spreadsheet_id": "your-spreadsheet-id",
    "credentials_file": "service_account.json"
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

## Architecture

```
aisynbiopipeline/
├── cli/          # Command-line interfaces
├── limsapi/      # LIMS API modules
│   ├── config.py     # Configuration management
│   ├── sheets.py     # Google Sheets integration
│   ├── database.py   # SQLite database management
│   ├── sync.py       # Synchronization daemon
│   ├── archive.py    # Archive management
│   └── query.py      # Query API
└── workflow/     # Workflow management (future)
```

## License

MIT License

## Support

For issues and questions, please open an issue on GitHub.
