"""
Celery task for running fastp.

This module configures the Celery app that the fastp worker.
This worker can be deployed anywhere with access to the Redis broker.
"""

import json
from pathlib import Path
from celery import states
from celery.exceptions import Ignore
import os, sys
from celery import Celery
from aisynbiopipeline.workflows.read_qc import run_fastp
from typing import List
from kombu import Exchange, Queue

QUEUE = 'fastp'

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
    task_time_limit=7200,  # 2 hour default timeout
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
def fastp(self,
          path_to_fwd,
          path_to_rev,
          path_to_fwd_out,
          path_to_rev_out,
          threads=16,
          polyG=10):
    """
    Celery task to run fastp read trimming.
    """

    # --- Validate inputs ---
    required = {
        "path_to_fwd": path_to_fwd,
        "path_to_rev": path_to_rev,
        "path_to_fwd_out": path_to_fwd_out,
        "path_to_rev_out": path_to_rev_out
    }

    missing = [name for name, value in required.items() if value is None]
    if missing:
        msg = f"Missing required parameters: {', '.join(missing)}"
        self.update_state(state=states.FAILURE, meta={'error': msg})
        raise Ignore()

    def norm(x):
        return str(x) if isinstance(x, Path) else x

    path_to_fwd = norm(path_to_fwd)
    path_to_rev = norm(path_to_rev)
    path_to_fwd_out = norm(path_to_fwd_out)
    path_to_rev_out = norm(path_to_rev_out)

    # --- Update state: task started ---
    self.update_state(
        state=states.STARTED,
        meta={
            "path_to_fwd": path_to_fwd,
            "path_to_rev": path_to_rev,
            "threads": threads,
            "polyG": polyG
        }
    )

    # --- Run fastp ---
    try:
        result = run_fastp(
            path_to_fwd,
            path_to_rev,
            path_to_fwd_out,
            path_to_rev_out,
            threads,
            polyG
        )
    except Exception as e:
        self.update_state(state=states.FAILURE, meta={"error": str(e)})
        raise

    return {"status": "success", "output": result}


# @app.task(bind=True, name='fastp.run')
# def fastp(self, args_dict: List[dict]) -> dict:
    
#     # Load input parameters from dict and validate required parameters
#     params = args_dict.keys()
#     required = ['path_to_fwd', 'path_to_rev', 'path_to_fwd_out', 'path_to_rev_out']
#     optional = ['threads', 'polyG']
#     missing = [p for p in required if p not in params]
#     if missing:
#         error_msg = f"Missing required parameters: {', '.join(missing)}"
#         self.update_state(
#             state=states.FAILURE,
#             meta={'error': error_msg}
#         )
#         raise Ignore()

#     path_to_fwd = args_dict['path_to_fwd']
#     path_to_rev = args_dict['path_to_rev']
#     path_to_fwd_out = args_dict['path_to_fwd_out']
#     path_to_rev_out = args_dict['path_to_rev_out']
#     if 'threads' in args_dict:
#         threads = args_dict['threads']
#     else:
#         threads = 16
#     if 'polyG' in args_dict:
#         polyG = args_dict['polyG']
#     else:
#         polyG = 10
    
#     # Update state to indicate processing
#     self.update_state(
#         state=states.STARTED,
#         meta = args_dict
#     )
    
#     result = run_fastp(
#         path_to_fwd,
#         path_to_rev,
#         path_to_fwd_out,
#         path_to_rev_out,
#         threads,
#         polyG
#     )
#     return result


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
     
