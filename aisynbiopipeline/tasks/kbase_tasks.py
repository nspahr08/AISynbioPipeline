"""
Celery tasks for KBase I/O operations.

These tasks handle downloading and uploading sequencing reads to/from KBase.
All tasks accept JSON input files and return JSON results.
"""

import json
from pathlib import Path
from celery import states
from celery.exceptions import Ignore

from ..celery_app import app
from ..workflows.kbase_io import (
    download_reads_from_kbase,
    upload_reads_to_kbase
)


@app.task(bind=True, name='kbase_io.download')
def download_kbase_reads(self, json_input_path: str) -> dict:
    """
    Download reads from KBase to local storage.

    Args:
        json_input_path: Path to JSON file containing:
            - kbase_ref: KBase reference (workspace/object_name)
            - library_name: Name of the sequencing library
            - sample_name: Name of the sample
            - read_type: Type of reads ('short' or 'long')
            - data_root: (optional) Root directory for data

    Returns:
        Dictionary with results including:
        - success: bool
        - output_files: List of downloaded file paths
        - placeholders: List of placeholder file paths
        - metadata: Download metadata
        - error: Error message if failed
    """
    # Load input parameters from JSON
    try:
        with open(json_input_path, 'r') as f:
            params = json.load(f)
    except Exception as e:
        self.update_state(
            state=states.FAILURE,
            meta={'error': f'Failed to load input JSON: {str(e)}'}
        )
        raise Ignore()

    # Validate required parameters
    required = ['kbase_ref', 'library_name', 'sample_name', 'read_type']
    missing = [p for p in required if p not in params]
    if missing:
        error_msg = f"Missing required parameters: {', '.join(missing)}"
        self.update_state(
            state=states.FAILURE,
            meta={'error': error_msg}
        )
        raise Ignore()

    # Extract parameters
    kbase_ref = params['kbase_ref']
    library_name = params['library_name']
    sample_name = params['sample_name']
    read_type = params['read_type']
    data_root = params.get('data_root', 'ai_synbio_data')

    # Update state to indicate processing
    self.update_state(
        state=states.STARTED,
        meta={
            'kbase_ref': kbase_ref,
            'library_name': library_name,
            'sample_name': sample_name
        }
    )

    # Execute the download
    result = download_reads_from_kbase(
        kbase_ref=kbase_ref,
        library_name=library_name,
        sample_name=sample_name,
        read_type=read_type,
        data_root=data_root
    )

    # Add task metadata
    result['task_id'] = self.request.id
    result['input_file'] = json_input_path

    # Write result to output JSON file
    output_path = Path(json_input_path).parent / f"{Path(json_input_path).stem}_result.json"
    with open(output_path, 'w') as f:
        json.dump(result, f, indent=2)

    result['output_file'] = str(output_path)

    return result


@app.task(bind=True, name='kbase_io.upload')
def upload_kbase_reads(self, json_input_path: str) -> dict:
    """
    Upload local reads to KBase.

    Args:
        json_input_path: Path to JSON file containing:
            - local_path: Path to local FASTQ file(s)
            - workspace: KBase workspace name
            - object_name: Name for the KBase object
            - library_name: Name of the sequencing library
            - sample_name: Name of the sample
            - read_type: Type of reads ('short' or 'long')

    Returns:
        Dictionary with results including:
        - success: bool
        - kbase_ref: KBase reference if successful
        - placeholder: Path to placeholder file
        - metadata: Upload metadata
        - error: Error message if failed
    """
    # Load input parameters from JSON
    try:
        with open(json_input_path, 'r') as f:
            params = json.load(f)
    except Exception as e:
        self.update_state(
            state=states.FAILURE,
            meta={'error': f'Failed to load input JSON: {str(e)}'}
        )
        raise Ignore()

    # Validate required parameters
    required = ['local_path', 'workspace', 'object_name', 'library_name', 'sample_name', 'read_type']
    missing = [p for p in required if p not in params]
    if missing:
        error_msg = f"Missing required parameters: {', '.join(missing)}"
        self.update_state(
            state=states.FAILURE,
            meta={'error': error_msg}
        )
        raise Ignore()

    # Extract parameters
    local_path = params['local_path']
    workspace = params['workspace']
    object_name = params['object_name']
    library_name = params['library_name']
    sample_name = params['sample_name']
    read_type = params['read_type']

    # Update state to indicate processing
    self.update_state(
        state=states.STARTED,
        meta={
            'workspace': workspace,
            'object_name': object_name,
            'library_name': library_name,
            'sample_name': sample_name
        }
    )

    # Execute the upload
    result = upload_reads_to_kbase(
        local_path=local_path,
        workspace=workspace,
        object_name=object_name,
        library_name=library_name,
        sample_name=sample_name,
        read_type=read_type
    )

    # Add task metadata
    result['task_id'] = self.request.id
    result['input_file'] = json_input_path

    # Write result to output JSON file
    output_path = Path(json_input_path).parent / f"{Path(json_input_path).stem}_result.json"
    with open(output_path, 'w') as f:
        json.dump(result, f, indent=2)

    result['output_file'] = str(output_path)

    return result
