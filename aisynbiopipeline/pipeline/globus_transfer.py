#!/usr/bin/env python3
"""Transfer data between two Globus endpoints programmatically.

This script wraps the Globus Transfer API (globus-sdk) so data can be moved
into /scratch1/fliu/hub_scratch/synbio/ (served by the Globus Connect
Personal endpoint running on poplar) without using the web interface.

Authentication uses a registered Globus *Native App* plus a stored refresh
token, mirroring the OAuth-token pattern already used for Google Drive in
this project. You log in interactively once; the refresh token is saved and
reused on every subsequent (including unattended / cron) run.

Two subcommands:

  login     One-time interactive browser login. Stores a refresh token to
            --token-file. Re-run with --data-access <collection-uuid> if a
            transfer reports that consent is required for a GCS v5 collection.

  transfer  Recursively transfer the entire contents of a source directory
            into a destination directory (Globus does the recursion
            server-side) and, by default, wait for it to finish, logging
            progress. Use --no-recursive to transfer a single file instead.

Setup (one time):
  1. Register a Native App at https://app.globus.org/settings/developers
     ("Register a thick client / native application"). Copy its Client ID.
  2. Provide the Client ID via --client-id or the GLOBUS_CLIENT_ID env var.
  3. python globus_transfer.py login
  4. python globus_transfer.py transfer <SRC_ID> <DST_ID> <src_path> <dst_path>

The destination endpoint defaults to this host's Globus Connect Personal
endpoint (read from ~/.globusonline/lta/client-id.txt) when given as "local".
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import globus_sdk
from globus_sdk.scopes import TransferScopes, GCSCollectionScopes


# Resource server key under which transfer tokens are stored.
TRANSFER_RS = "transfer.api.globus.org"

# Destination paths must live under this prefix unless --allow-any-dest is set.
ALLOWED_DEST_PREFIX = "/scratch1/fliu/hub_scratch/synbio"

# Local Globus Connect Personal config (its client-id.txt holds this host's
# collection/endpoint UUID).
LOCAL_GCP_ID_FILE = Path.home() / ".globusonline" / "lta" / "client-id.txt"

# Default location for the stored refresh/access tokens.
DEFAULT_TOKEN_FILE = Path.home() / ".globus_aisynbio_tokens.json"

# Optional hard-coded Client ID; leave blank and pass via --client-id / env.
DEFAULT_CLIENT_ID = ""

LOG_FILE = Path(__file__).resolve().parent / 'pipeline.log'


def configure_logging():
    """Set up logging to file and console."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.touch(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
        handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
    )
    return logging.getLogger(__name__)


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description='Transfer data between two Globus endpoints'
    )
    parser.add_argument(
        '--client-id', default=None,
        help='Globus Native App Client ID (default: $GLOBUS_CLIENT_ID or the '
             'DEFAULT_CLIENT_ID constant)',
    )
    parser.add_argument(
        '--token-file', default=str(DEFAULT_TOKEN_FILE),
        help=f'Where the refresh/access tokens are stored (default: {DEFAULT_TOKEN_FILE})',
    )

    sub = parser.add_subparsers(dest='command', required=True)

    # login -------------------------------------------------------------
    p_login = sub.add_parser('login', help='One-time interactive login; stores a refresh token')
    p_login.add_argument(
        '--data-access', action='append', default=[], metavar='COLLECTION_UUID',
        help='Also request the data_access scope for this GCS v5 collection '
             '(repeatable). Needed when a transfer reports ConsentRequired.',
    )
    p_login.add_argument(
        '--raw-scope', action='append', default=[], metavar='SCOPE',
        help='Additional raw scope string(s) to request (repeatable).',
    )

    # transfer ----------------------------------------------------------
    p_tx = sub.add_parser('transfer', help='Submit and monitor a transfer')
    p_tx.add_argument('source_endpoint', help='Source endpoint/collection UUID')
    p_tx.add_argument(
        'dest_endpoint',
        help='Destination endpoint/collection UUID, or "local" for this host\'s '
             'Globus Connect Personal endpoint',
    )
    p_tx.add_argument('source_path', help='Source directory whose entire contents are transferred (or a file with --no-recursive)')
    p_tx.add_argument(
        'dest_path',
        help=f'Destination directory the contents are placed into (must be under '
             f'{ALLOWED_DEST_PREFIX} unless --allow-any-dest is given)',
    )
    p_tx.add_argument('--label', default=None, help='Human-readable label for the transfer task')
    p_tx.add_argument(
        '--sync-level', default='checksum',
        choices=['exists', 'size', 'mtime', 'checksum'],
        help='Skip files already present at the destination per this rule (default: checksum)',
    )
    p_tx.add_argument(
        '--recursive', dest='recursive', action='store_true', default=True,
        help='Transfer source_path as a directory, contents and all (default)',
    )
    p_tx.add_argument(
        '--no-recursive', dest='recursive', action='store_false',
        help='Transfer source_path as a single file',
    )
    p_tx.add_argument('--no-verify-checksum', action='store_true', help='Disable post-transfer checksum verification')
    p_tx.add_argument(
        '--notify-on-success', action='store_true',
        help='Send a Globus email on successful transfers too '
             '(default: only email on failure/inactive)',
    )
    p_tx.add_argument('--no-wait', action='store_true', help='Submit and exit without waiting for completion')
    p_tx.add_argument('--poll-interval', type=int, default=30, help='Seconds between status polls while waiting (default: 30)')
    p_tx.add_argument('--allow-any-dest', action='store_true', help=f'Permit destination paths outside {ALLOWED_DEST_PREFIX}')

    return parser.parse_args()


def resolve_client_id(args, logger):
    """Determine the Globus Native App Client ID from args/env/constant."""
    client_id = args.client_id or os.environ.get('GLOBUS_CLIENT_ID') or DEFAULT_CLIENT_ID
    if not client_id:
        logger.error(
            'No Globus Client ID. Register a Native App at '
            'https://app.globus.org/settings/developers and pass --client-id '
            'or set GLOBUS_CLIENT_ID.'
        )
        raise SystemExit(2)
    return client_id


def resolve_local_endpoint_id(logger):
    """Read this host's Globus Connect Personal endpoint UUID."""
    if not LOCAL_GCP_ID_FILE.exists():
        logger.error(
            'Could not find the local Globus Connect Personal endpoint id at %s. '
            'Pass the destination endpoint UUID explicitly instead of "local".',
            LOCAL_GCP_ID_FILE,
        )
        raise SystemExit(2)
    return LOCAL_GCP_ID_FILE.read_text().strip()


def build_requested_scope(data_access_collections, raw_scopes):
    """Build the transfer scope string, adding data_access dependencies if any.

    The dependent-scope form ``transfer:all[*<data_access> ...]`` grants the
    transfer token permission to touch the named GCS v5 collections.
    """
    scopes = []
    base = str(TransferScopes.all)
    if data_access_collections:
        inner = ' '.join('*' + str(GCSCollectionScopes(c).data_access) for c in data_access_collections)
        scopes.append(f'{base}[{inner}]')
    else:
        scopes.append(base)
    scopes.extend(raw_scopes)
    return ' '.join(scopes)


def load_token_data(token_file):
    """Load the stored token dict, keyed by resource server."""
    path = Path(token_file)
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def save_token_data(token_file, data):
    """Persist the token dict with owner-only permissions."""
    path = Path(token_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
    os.chmod(path, 0o600)


def do_login(client_id, token_file, requested_scope, logger):
    """Run the interactive Native App OAuth flow and store the tokens."""
    auth_client = globus_sdk.NativeAppAuthClient(client_id)
    auth_client.oauth2_start_flow(requested_scopes=requested_scope, refresh_tokens=True)

    authorize_url = auth_client.oauth2_get_authorize_url()
    print('\nOpen this URL in a browser, log in, and authorize access:\n')
    print(authorize_url + '\n')
    auth_code = input('Paste the authorization code here: ').strip()

    token_response = auth_client.oauth2_exchange_code_for_tokens(auth_code)
    data = load_token_data(token_file)
    data.update(token_response.by_resource_server)
    save_token_data(token_file, data)
    logger.info('Stored Globus tokens to %s', token_file)


def build_transfer_client(client_id, token_file, logger):
    """Build a TransferClient from stored refresh tokens."""
    data = load_token_data(token_file)
    if TRANSFER_RS not in data:
        logger.error(
            'No stored transfer token in %s. Run the "login" subcommand first.',
            token_file,
        )
        raise SystemExit(2)

    tokens = data[TRANSFER_RS]
    auth_client = globus_sdk.NativeAppAuthClient(client_id)

    def on_refresh(refresh_response):
        # Persist newly issued access tokens so they survive across runs.
        updated = load_token_data(token_file)
        updated.update(refresh_response.by_resource_server)
        save_token_data(token_file, updated)
        logger.info('Refreshed and saved Globus access token')

    authorizer = globus_sdk.RefreshTokenAuthorizer(
        tokens['refresh_token'],
        auth_client,
        access_token=tokens.get('access_token'),
        expires_at=tokens.get('expires_at_seconds'),
        on_refresh=on_refresh,
    )
    return globus_sdk.TransferClient(authorizer=authorizer)


def monitor_task(tc, task_id, poll_interval, logger):
    """Poll a transfer task until it finishes; return True on success."""
    while True:
        task = tc.get_task(task_id)
        logger.info(
            'task %s: status=%s files=%s/%s bytes=%s',
            task_id, task['status'],
            task.get('files_transferred'), task.get('files'),
            task.get('bytes_transferred'),
        )
        if task['status'] in ('SUCCEEDED', 'FAILED'):
            break
        # task_wait returns early if the task completes before the timeout.
        tc.task_wait(task_id, timeout=poll_interval, polling_interval=poll_interval)

    if task['status'] == 'SUCCEEDED':
        logger.info('Transfer %s SUCCEEDED', task_id)
        return True

    logger.error('Transfer %s FAILED: %s', task_id, task.get('nice_status_details') or task.get('nice_status'))
    for event in tc.task_event_list(task_id, limit=10):
        if event.get('is_error'):
            logger.error('  event: %s - %s', event.get('code'), event.get('description'))
    return False


def run_transfer(args, logger):
    """Build, submit, and (optionally) monitor a transfer task."""
    client_id = resolve_client_id(args, logger)

    src = args.source_endpoint
    dst = resolve_local_endpoint_id(logger) if args.dest_endpoint == 'local' else args.dest_endpoint

    # Enforce the destination prefix unless explicitly overridden.
    dest_path = args.dest_path
    if not args.allow_any_dest:
        norm = os.path.normpath(dest_path)
        if not (norm == ALLOWED_DEST_PREFIX or norm.startswith(ALLOWED_DEST_PREFIX + os.sep)):
            logger.error(
                'Destination path %s is not under %s (use --allow-any-dest to override).',
                dest_path, ALLOWED_DEST_PREFIX,
            )
            raise SystemExit(2)

    tc = build_transfer_client(client_id, token_file=args.token_file, logger=logger)

    label = args.label or f'aisynbio {Path(args.source_path).name}'
    transfer_data = globus_sdk.TransferData(
        source_endpoint=src,
        destination_endpoint=dst,
        label=label,
        sync_level=args.sync_level,
        verify_checksum=not args.no_verify_checksum,
        # Only email on problems. Globus defaults all three to True, which is
        # why every successful scheduled transfer sent a notification.
        notify_on_succeeded=args.notify_on_success,
        notify_on_failed=True,
        notify_on_inactive=True,
    )

    # Recursive by default: Globus copies the entire contents of the source
    # directory into the destination directory (server-side recursion).
    transfer_data.add_item(args.source_path, dest_path, recursive=args.recursive)

    logger.info(
        'Submitting transfer: %s:%s -> %s:%s (recursive=%s, sync=%s)',
        src, args.source_path, dst, dest_path, args.recursive, args.sync_level,
    )

    try:
        task = tc.submit_transfer(transfer_data)
    except globus_sdk.TransferAPIError as err:
        if err.info.consent_required:
            required = err.info.consent_required.required_scopes
            logger.error(
                'Consent required for this transfer. Re-run login to grant it, e.g.:\n'
                '    python %s login --data-access <SRC_COLLECTION_UUID> '
                '--data-access <DST_COLLECTION_UUID>\n'
                'Required scopes reported by Globus: %s',
                Path(__file__).name, required,
            )
            raise SystemExit(3)
        logger.error('Transfer submission failed: %s', err)
        raise

    task_id = task['task_id']
    logger.info('Submitted transfer task %s', task_id)

    if args.no_wait:
        logger.info('Not waiting for completion (--no-wait). Track with: globus task show %s', task_id)
        return

    if not monitor_task(tc, task_id, args.poll_interval, logger):
        raise SystemExit(1)


def main():
    """Main entry point."""
    args = parse_args()
    logger = configure_logging()

    if args.command == 'login':
        client_id = resolve_client_id(args, logger)
        requested_scope = build_requested_scope(args.data_access, args.raw_scope)
        logger.info('Starting Globus login (scopes: %s)', requested_scope)
        do_login(client_id, args.token_file, requested_scope, logger)
    elif args.command == 'transfer':
        run_transfer(args, logger)


if __name__ == '__main__':
    main()
