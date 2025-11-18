#!/usr/bin/env python
"""
CLI for managing Celery-based computational tasks in AISynbioPipeline.

This CLI provides commands for:
- Starting Celery workers
- Submitting tasks to the queue
- Monitoring task status
- Retrieving task results
- Canceling tasks
"""

import argparse
import json
import sys
import os
import webbrowser
from pathlib import Path
from typing import Optional

from celery import Celery
from celery.result import AsyncResult


def get_celery_client() -> Celery:
    """
    Get a Celery client for submitting tasks and checking status.

    Returns:
        Configured Celery client
    """
    return Celery(
        'aisynbiopipeline_client',
        broker=os.getenv('CELERY_BROKER_URL', 'redis://bioseed_redis:6379/10'),
        backend=os.getenv('CELERY_RESULT_BACKEND', 'redis://bioseed_redis:6379/10')
    )


def start_worker(args):
    """Start the Celery worker."""
    from ..celery_app import app

    print("=" * 70)
    print("Starting AISynbioPipeline Celery Worker")
    print("=" * 70)
    print(f"Broker: {app.conf.broker_url}")
    print(f"Backend: {app.conf.result_backend}")
    print(f"Concurrency: {args.concurrency}")
    print("")
    print("Available tasks:")
    print("  - kbase_io.download")
    print("  - kbase_io.upload")
    print("")
    print("Monitor at: http://poplar.cels.anl.gov:5555")
    print("=" * 70)
    print("")

    # Start worker
    app.worker_main([
        'worker',
        f'--loglevel={args.loglevel}',
        f'--concurrency={args.concurrency}',
        f'--hostname=aisynbiopipeline@%h'
    ])


def submit_task(args):
    """Submit a task to the Celery queue."""
    json_file = Path(args.json_file)

    if not json_file.exists():
        print(f"Error: JSON file not found: {json_file}", file=sys.stderr)
        sys.exit(1)

    # Validate task name
    valid_tasks = ['kbase_io.download', 'kbase_io.upload']
    if args.task_name not in valid_tasks:
        print(f"Error: Unknown task: {args.task_name}", file=sys.stderr)
        print(f"Valid tasks: {', '.join(valid_tasks)}", file=sys.stderr)
        sys.exit(1)

    # Get Celery client
    client = get_celery_client()

    # Submit task
    print(f"Submitting task: {args.task_name}")
    print(f"Input file: {json_file.absolute()}")

    result = client.send_task(args.task_name, args=[str(json_file.absolute())])

    print(f"Task ID: {result.id}")
    print(f"Status: {result.state}")
    print("")
    print("Check status with:")
    print(f"  ./aisynbio.sh status {result.id}")


def check_status(args):
    """Check the status of a task."""
    client = get_celery_client()
    result = AsyncResult(args.task_id, app=client)

    print(f"Task ID: {args.task_id}")
    print(f"Status: {result.state}")

    if result.state == 'PENDING':
        print("Task is waiting to be processed")
    elif result.state == 'STARTED':
        print("Task is currently running")
        if result.info:
            print(f"Info: {json.dumps(result.info, indent=2)}")
    elif result.state == 'SUCCESS':
        print("Task completed successfully")
    elif result.state == 'FAILURE':
        print("Task failed")
        print(f"Error: {result.info}")
    elif result.state == 'RETRY':
        print("Task is being retried")
    elif result.state == 'REVOKED':
        print("Task was canceled")


def get_result(args):
    """Get the result of a completed task."""
    client = get_celery_client()
    result = AsyncResult(args.task_id, app=client)

    print(f"Task ID: {args.task_id}")
    print(f"Status: {result.state}")
    print("")

    if result.ready():
        if result.successful():
            task_result = result.get()
            print("Result:")
            print(json.dumps(task_result, indent=2))

            # Save to file if requested
            if args.output:
                output_path = Path(args.output)
                with open(output_path, 'w') as f:
                    json.dump(task_result, f, indent=2)
                print(f"\nResult saved to: {output_path}")
        else:
            print(f"Task failed: {result.info}")
    else:
        print("Task not yet complete")
        print("Current state:", result.state)
        if result.info:
            print(f"Info: {json.dumps(result.info, indent=2)}")


def cancel_task(args):
    """Cancel a running task."""
    client = get_celery_client()
    result = AsyncResult(args.task_id, app=client)

    print(f"Canceling task: {args.task_id}")

    result.revoke(terminate=True)

    print("Task revoked")
    print("Note: It may take a moment for the worker to respond")


def list_tasks(args):
    """List available task types."""
    print("Available Tasks:")
    print("=" * 70)
    print("")

    tasks = {
        'kbase_io.download': {
            'description': 'Download sequencing reads from KBase',
            'inputs': ['kbase_ref', 'library_name', 'sample_name', 'read_type', 'data_root (optional)']
        },
        'kbase_io.upload': {
            'description': 'Upload sequencing reads to KBase',
            'inputs': ['local_path', 'workspace', 'object_name', 'library_name', 'sample_name', 'read_type']
        }
    }

    for task_name, info in tasks.items():
        print(f"{task_name}")
        print(f"  Description: {info['description']}")
        print(f"  Required inputs: {', '.join(info['inputs'])}")
        print("")


def open_monitor(args):
    """Open the Flower monitoring dashboard."""
    url = "http://poplar.cels.anl.gov:5555"
    print(f"Opening Flower dashboard: {url}")

    try:
        webbrowser.open(url)
        print("Dashboard opened in browser")
    except Exception as e:
        print(f"Could not open browser: {e}")
        print(f"Please open manually: {url}")


def create_template(args):
    """Create a template JSON file for a task."""
    task_name = args.task_name
    output_file = args.output

    templates = {
        'kbase_io.download': {
            "kbase_ref": "workspace/object_name",
            "library_name": "example_library_ABC",
            "sample_name": "sample_001",
            "read_type": "short",
            "data_root": "ai_synbio_data"
        },
        'kbase_io.upload': {
            "local_path": "path/to/reads.fastq",
            "workspace": "workspace_name",
            "object_name": "object_name",
            "library_name": "example_library_ABC",
            "sample_name": "sample_001",
            "read_type": "short"
        }
    }

    if task_name not in templates:
        print(f"Error: Unknown task: {task_name}", file=sys.stderr)
        print(f"Available tasks: {', '.join(templates.keys())}", file=sys.stderr)
        sys.exit(1)

    template = templates[task_name]

    # Write template to file
    output_path = Path(output_file)
    with open(output_path, 'w') as f:
        json.dump(template, f, indent=2)

    print(f"Created task template: {output_path}")
    print(f"Task: {task_name}")
    print("")
    print("Edit this file with your parameters, then submit with:")
    print(f"  ./aisynbio.sh submit {task_name} {output_path}")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description='AISynbioPipeline Celery Task Management',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start a worker
  aisynbio worker

  # Submit a task
  aisynbio submit kbase_io.download my_download.json

  # Check task status
  aisynbio status <task-id>

  # Get task result
  aisynbio result <task-id>

  # Cancel a task
  aisynbio cancel <task-id>

  # List available tasks
  aisynbio tasks

  # Open monitoring dashboard
  aisynbio monitor

  # Create a task template
  aisynbio template kbase_io.download -o my_download.json
"""
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to execute')

    # Worker command
    worker_parser = subparsers.add_parser('worker', help='Start the Celery worker')
    worker_parser.add_argument(
        '--concurrency',
        type=int,
        default=2,
        help='Number of concurrent workers (default: 2)'
    )
    worker_parser.add_argument(
        '--loglevel',
        default='info',
        choices=['debug', 'info', 'warning', 'error'],
        help='Log level (default: info)'
    )
    worker_parser.set_defaults(func=start_worker)

    # Submit command
    submit_parser = subparsers.add_parser('submit', help='Submit a task to the queue')
    submit_parser.add_argument('task_name', help='Name of the task (e.g., kbase_io.download)')
    submit_parser.add_argument('json_file', help='Path to JSON input file')
    submit_parser.set_defaults(func=submit_task)

    # Status command
    status_parser = subparsers.add_parser('status', help='Check task status')
    status_parser.add_argument('task_id', help='Task ID')
    status_parser.set_defaults(func=check_status)

    # Result command
    result_parser = subparsers.add_parser('result', help='Get task result')
    result_parser.add_argument('task_id', help='Task ID')
    result_parser.add_argument(
        '-o', '--output',
        help='Save result to file'
    )
    result_parser.set_defaults(func=get_result)

    # Cancel command
    cancel_parser = subparsers.add_parser('cancel', help='Cancel a running task')
    cancel_parser.add_argument('task_id', help='Task ID')
    cancel_parser.set_defaults(func=cancel_task)

    # Tasks command
    tasks_parser = subparsers.add_parser('tasks', help='List available task types')
    tasks_parser.set_defaults(func=list_tasks)

    # Monitor command
    monitor_parser = subparsers.add_parser('monitor', help='Open Flower monitoring dashboard')
    monitor_parser.set_defaults(func=open_monitor)

    # Template command
    template_parser = subparsers.add_parser('template', help='Create a task template file')
    template_parser.add_argument('task_name', help='Name of the task')
    template_parser.add_argument(
        '-o', '--output',
        required=True,
        help='Output file path'
    )
    template_parser.set_defaults(func=create_template)

    # Parse arguments
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Execute command
    args.func(args)


if __name__ == '__main__':
    main()
