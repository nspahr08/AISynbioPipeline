"""
Celery application configuration for AISynbioPipeline.

This module configures the Celery app that coordinates all computational tasks
in the pipeline. Workers can be deployed anywhere with access to the Redis broker.
"""

import os
from celery import Celery

# Configure Celery app
app = Celery(
    'aisynbiopipeline',
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
)

# Auto-discover tasks from tasks module
app.autodiscover_tasks(['aisynbiopipeline.tasks'])
