"""
Celery task for creating Breseq_params and Breseq objects, and running breseq.run().

This module configures the Celery app for the breseq worker.
This worker can be deployed anywhere with access to the Redis broker.
"""

import json
from pathlib import Path
from celery import states
from celery.exceptions import Ignore
import os, sys
from celery import Celery
from aisynbiopipeline.workflows.breseq import Breseq_params, Breseq
from typing import List
from kombu import Exchange, Queue

QUEUE = 'breseq'


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
def breseq(self,
           read_paths,
           reference,
           polymorphism_prediction,
           breseq_folder=None,
           limit_fold_coverage=0,
           num_processors=4,
           polymorphism_frequency_cutoff=0.05
          ):
    """
    Celery task to run breseq.
    """

    # --- Validate inputs ---
    required = {
        'read_paths': read_paths,
        'breseq_folder': breseq_folder,
        'reference': reference,
        'polymorphism_prediction': polymorphism_prediction
    }

    missing = [name for name, value in required.items() if value is None]
    if missing:
        msg = f"Missing required parameters: {', '.join(missing)}"
        self.update_state(state=states.FAILURE, meta={'error': msg})
        raise Ignore()

    def norm(x):
        return str(x) if isinstance(x, Path) else x

    # for p in read_paths:
    #     norm(p)
    # breseq_folder = norm(breseq_folder)

    # --- Update state: task started ---
    self.update_state(
        state=states.STARTED,
        meta={
            'read_paths': read_paths,
            'breseq_folder': breseq_folder,
            'reference': reference,
            'polymorphism_prediction': polymorphism_prediction,
            'limit_fold_coverage': limit_fold_coverage,
            'num_processors': num_processors,
            'polymorphism_frequency_cutoff': polymorphism_frequency_cutoff
        }
    )

    # --- Run breseq ---
    try:
        params = Breseq_params(
            reference,
            polymorphism_prediction,
            limit_fold_coverage=limit_fold_coverage,
            num_processors=num_processors,
            polymorphism_frequency_cutoff=polymorphism_frequency_cutoff
        )
        breseq = Breseq(read_paths, params, breseq_folder)
        print(breseq.params.version_name)
        breseq.run()
        result = norm(breseq.output_folder)
    except Exception as e:
        self.update_state(state=states.FAILURE, meta={"error": str(e)})
        raise

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
     
