"""
Celery task for identifying and extracting amplicon barcodes based on adjacent anchor sequences.

This module configures the Celery app for the worker.
This worker can be deployed anywhere with access to the Redis broker.
"""

import json
from pathlib import Path
from celery import states
from celery.exceptions import Ignore
import os, sys
from celery import Celery
from aisynbiopipeline.workflows.barcodes import load_barcodes, process_fastq
from typing import List
from kombu import Exchange, Queue
from traceback import format_tb

QUEUE = 'barcode'


# Configure Celery app
app = Celery(
    QUEUE,
    broker=os.getenv('CELERY_BROKER_URL', 'redis://bioseed_redis:6379/10'),
    backend=os.getenv('CELERY_RESULT_BACKEND', 'redis://bioseed_redis:6379/10')
)

# Configure Celery settings
app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=86400,  # 24 hour default timeout 18000,  # 5 hour default timeout 10800,  # 3 hour default timeout
    worker_prefetch_multiplier=1,
    result_expires=86400,  # Results expire after 24 hours

    # IMPORTANT PART:
    task_default_queue=QUEUE,
    task_default_exchange=QUEUE,
    task_default_routing_key=QUEUE,

    task_queues=(
        Queue(QUEUE, Exchange(QUEUE), routing_key=QUEUE),
    ),

    task_routes={
        f'{QUEUE}.*': {'queue': QUEUE, 'routing_key': QUEUE},
    },
)


@app.task(bind=True, name=f"{QUEUE}.run")
def barcode(self, fq, barcodes_A, barcodes_B, extract_dir
          ):
    """
    Celery task to run barcode extraction.
    """

    # --- Validate inputs ---
    required = {
            'fq': fq, 'barcodes_A': barcodes_A, 'barcodes_B': barcodes_B, 'extract_dir': extract_dir
    }

    missing = [name for name, value in required.items() if value is None]
    if missing:
        msg = f"Missing required parameters: {', '.join(missing)}"
        self.update_state(state=states.FAILURE, meta={'error': msg})
        raise Ignore()

    # def norm(x):
    #     return str(x) if isinstance(x, Path) else x


    # --- Update state: task started ---
    self.update_state(
        state=states.STARTED,
        meta={
            'fq': fq, 'barcodes_A': barcodes_A, 'barcodes_B': barcodes_B, 'extract_dir': extract_dir
        }
    )

    # --- Run extract barcodes ---
    try:
        result = process_fastq(fq, barcodes_A, barcodes_B, extract_dir)
    except Exception as exc:
        self.update_state(
            state=states.FAILURE,
            meta={
                'exc_type': type(exc).__name__,
                'exc_message': str(exc),
                'traceback': format_tb(exc.__traceback__),
            }
        )
        raise exc

    return {"status": "success", "output": result}


if __name__ == "__main__":

    """Start the Celery worker."""

    print("=" * 70)
    print(f"Starting {QUEUE} Celery Worker")
    print("=" * 70)
    # print(f"Broker: {app.conf.broker_url}")
    # print(f"Backend: {app.conf.result_backend}")
    # print(f"Concurrency: {args.concurrency}")
    print("")
    print("Monitor at: http://poplar.cels.anl.gov:5555")
    print("=" * 70)
    print("")

    # Start worker
    app.worker_main([
        'worker',
        '--loglevel=info',
        '--concurrency=2',
        f'--queues={QUEUE}',
        f'--hostname={QUEUE}_{sys.argv[1]}@%h'
    ])
     
