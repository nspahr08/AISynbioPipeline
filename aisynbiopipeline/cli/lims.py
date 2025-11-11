#!/usr/bin/env python3
"""
LIMS CLI commands.

Command-line interface for LIMS sync operations, queries, and management.
"""

import argparse
import json
import sys
from datetime import datetime
from typing import Optional

from aisynbiopipeline.limsapi import (
    # Sync functions
    sync_all_sheets,
    start_sync_daemon,
    stop_sync_daemon,
    get_sync_status,
    # Query functions
    list_tables,
    get_table_schema,
    query_table,
    get_all_records,
    get_table_count,
    # Archive functions
    create_archive,
    list_archives,
    restore_archive,
    cleanup_archives,
)


def cmd_sync(args) -> int:
    """Run a manual sync."""
    try:
        print("Starting manual sync...")
        result = sync_all_sheets()

        print("\nSync Results:")
        print(f"  Status: {'SUCCESS' if result['success'] else 'FAILED'}")
        print(f"  Tables synced: {result['tables_synced']}")
        print(f"  Rows inserted: {result['total_rows_inserted']}")
        print(f"  Rows updated: {result['total_rows_updated']}")
        print(f"  Rows deleted: {result['total_rows_deleted']}")
        print(f"  Duration: {result['start_time']} to {result['end_time']}")

        if result['errors']:
            print(f"\nErrors ({len(result['errors'])}):")
            for error in result['errors']:
                print(f"  - {error}")

        return 0 if result['success'] else 1

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_daemon_start(args) -> int:
    """Start the sync daemon."""
    try:
        print("Starting sync daemon...")
        start_sync_daemon()
        print("Sync daemon started successfully")
        print("The daemon will run in the background and sync every configured interval")
        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_daemon_stop(args) -> int:
    """Stop the sync daemon."""
    try:
        print("Stopping sync daemon...")
        stop_sync_daemon()
        print("Sync daemon stopped successfully")
        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_status(args) -> int:
    """Get sync status."""
    try:
        status = get_sync_status()

        print("Sync Daemon Status:")
        print(f"  Running: {status['daemon_running']}")
        print(f"  Last sync: {status['last_sync'] or 'Never'}")
        print(f"  Last success: {status['last_success'] or 'Never'}")
        print(f"  Syncs completed: {status['syncs_completed']}")
        print(f"  Syncs failed: {status['syncs_failed']}")

        if status['last_error']:
            print(f"  Last error: {status['last_error']}")

        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_list_tables(args) -> int:
    """List all tables."""
    try:
        tables = list_tables()

        if not tables:
            print("No tables found in database")
            return 0

        print(f"Tables ({len(tables)}):")
        for table in tables:
            if args.count:
                count = get_table_count(table, include_deleted=args.include_deleted)
                print(f"  - {table} ({count} rows)")
            else:
                print(f"  - {table}")

        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_schema(args) -> int:
    """Get table schema."""
    try:
        schema = get_table_schema(args.table)

        print(f"Schema for table '{args.table}':")
        for col_name, col_type in schema.items():
            print(f"  {col_name}: {col_type}")

        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_query(args) -> int:
    """Query a table."""
    try:
        # Parse filters if provided
        filters = None
        if args.filter:
            filters = {}
            for f in args.filter:
                try:
                    col, val = f.split('=', 1)
                    filters[col.strip()] = val.strip()
                except ValueError:
                    print(f"Invalid filter format: {f}. Use column=value", file=sys.stderr)
                    return 1

        # Parse columns if provided
        columns = args.columns.split(',') if args.columns else None

        # Execute query
        results = query_table(
            args.table,
            filters=filters,
            columns=columns,
            include_deleted=args.include_deleted,
            limit=args.limit,
            offset=args.offset,
            order_by=args.order_by,
            order_desc=args.desc
        )

        # Output results
        if args.format == 'json':
            print(json.dumps(results, indent=2, default=str))
        elif args.format == 'table':
            if not results:
                print("No results found")
                return 0

            # Get column names
            cols = list(results[0].keys())

            # Print header
            print(' | '.join(cols))
            print('-' * (len(' | '.join(cols))))

            # Print rows
            for row in results:
                print(' | '.join(str(row.get(col, '')) for col in cols))

            print(f"\n{len(results)} row(s) returned")
        else:
            # CSV format
            if not results:
                print("No results found")
                return 0

            # Get column names
            cols = list(results[0].keys())

            # Print header
            print(','.join(cols))

            # Print rows
            for row in results:
                values = [str(row.get(col, '')).replace(',', ';') for col in cols]
                print(','.join(values))

        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_archive_create(args) -> int:
    """Create an archive."""
    try:
        print(f"Creating {args.type} archive...")
        archive_path = create_archive(args.type)
        print(f"Archive created: {archive_path}")
        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_archive_list(args) -> int:
    """List archives."""
    try:
        archives = list_archives(args.type)

        if not archives:
            print("No archives found")
            return 0

        print(f"Archives ({len(archives)}):")
        for archive in archives:
            size_mb = archive['size_bytes'] / (1024 * 1024)
            compressed = " (compressed)" if archive['compressed'] else ""
            print(f"  {archive['filename']}: {archive['type']}, "
                  f"{archive['timestamp']}, {size_mb:.2f} MB{compressed}")

        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_archive_restore(args) -> int:
    """Restore an archive."""
    try:
        if not args.force:
            response = input(
                f"This will overwrite the current database. Are you sure? (yes/no): "
            )
            if response.lower() != 'yes':
                print("Restore cancelled")
                return 0

        print(f"Restoring archive: {args.archive}")
        restored_path = restore_archive(args.archive, args.target)
        print(f"Database restored to: {restored_path}")
        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_archive_cleanup(args) -> int:
    """Cleanup old archives."""
    try:
        print("Cleaning up old archives based on retention policy...")
        deleted = cleanup_archives()

        print("Archives deleted:")
        for archive_type, count in deleted.items():
            if count > 0:
                print(f"  {archive_type}: {count}")

        total = sum(deleted.values())
        print(f"\nTotal: {total} archive(s) deleted")
        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="LIMS sync and query command-line interface"
    )
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')

    # Sync command
    parser_sync = subparsers.add_parser('sync', help='Run manual sync')
    parser_sync.set_defaults(func=cmd_sync)

    # Daemon commands
    parser_daemon = subparsers.add_parser('daemon', help='Manage sync daemon')
    daemon_subparsers = parser_daemon.add_subparsers(dest='daemon_command')

    parser_daemon_start = daemon_subparsers.add_parser('start', help='Start daemon')
    parser_daemon_start.set_defaults(func=cmd_daemon_start)

    parser_daemon_stop = daemon_subparsers.add_parser('stop', help='Stop daemon')
    parser_daemon_stop.set_defaults(func=cmd_daemon_stop)

    # Status command
    parser_status = subparsers.add_parser('status', help='Get sync status')
    parser_status.set_defaults(func=cmd_status)

    # List tables command
    parser_list = subparsers.add_parser('list', help='List all tables')
    parser_list.add_argument('--count', action='store_true', help='Show row counts')
    parser_list.add_argument('--include-deleted', action='store_true',
                            help='Include deleted rows in counts')
    parser_list.set_defaults(func=cmd_list_tables)

    # Schema command
    parser_schema = subparsers.add_parser('schema', help='Get table schema')
    parser_schema.add_argument('table', help='Table name')
    parser_schema.set_defaults(func=cmd_schema)

    # Query command
    parser_query = subparsers.add_parser('query', help='Query a table')
    parser_query.add_argument('table', help='Table name')
    parser_query.add_argument('-f', '--filter', action='append',
                             help='Filter: column=value (can specify multiple)')
    parser_query.add_argument('-c', '--columns', help='Comma-separated list of columns')
    parser_query.add_argument('--include-deleted', action='store_true',
                             help='Include deleted rows')
    parser_query.add_argument('--limit', type=int, help='Limit number of results')
    parser_query.add_argument('--offset', type=int, help='Offset for pagination')
    parser_query.add_argument('--order-by', help='Column to order by')
    parser_query.add_argument('--desc', action='store_true', help='Order descending')
    parser_query.add_argument('--format', choices=['json', 'csv', 'table'],
                             default='table', help='Output format')
    parser_query.set_defaults(func=cmd_query)

    # Archive commands
    parser_archive = subparsers.add_parser('archive', help='Manage archives')
    archive_subparsers = parser_archive.add_subparsers(dest='archive_command')

    parser_archive_create = archive_subparsers.add_parser('create', help='Create archive')
    parser_archive_create.add_argument('--type', default='manual',
                                      choices=['manual', 'hourly', 'daily', 'weekly', 'monthly'],
                                      help='Archive type')
    parser_archive_create.set_defaults(func=cmd_archive_create)

    parser_archive_list = archive_subparsers.add_parser('list', help='List archives')
    parser_archive_list.add_argument('--type', help='Filter by archive type')
    parser_archive_list.set_defaults(func=cmd_archive_list)

    parser_archive_restore = archive_subparsers.add_parser('restore', help='Restore archive')
    parser_archive_restore.add_argument('archive', help='Archive filename')
    parser_archive_restore.add_argument('--target', help='Target path (optional)')
    parser_archive_restore.add_argument('--force', action='store_true',
                                       help='Skip confirmation')
    parser_archive_restore.set_defaults(func=cmd_archive_restore)

    parser_archive_cleanup = archive_subparsers.add_parser('cleanup',
                                                           help='Cleanup old archives')
    parser_archive_cleanup.set_defaults(func=cmd_archive_cleanup)

    # Parse and execute
    args = parser.parse_args()

    if not hasattr(args, 'func'):
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
