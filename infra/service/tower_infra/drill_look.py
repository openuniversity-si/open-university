"""DRILLS: the live service's look (drills.Drills with fastdeploy's Lambda client). Apart from drills.py, which the port's
Lambda imports for its routes: this module's imports (fastdeploy, boto3) are the service's alone.

This module runs in the service alone: no port Lambda's package holds it (scripts/lib/deploy_classify.LAMBDA_MODULES),
so a change here is a code-only merge of the service (QUEUE-SWAP: its heir is up before the landing).
"""
import logging

from . import drills

LOG = logging.getLogger('tower_infra.drills')


def start(scope, stop, wait, active=None, environ=None, make=None):
    """The look in a daemon thread (the live service's alone); its Lambda client made at its first active look."""
    import os
    import threading
    environ = os.environ if environ is None else environ

    def made():
        import boto3
        from botocore.config import Config
        from . import fastdeploy
        return drills.Drills(fastdeploy.FastDeploy(boto3.client('lambda', region_name=environ.get('AWS_REGION'), config=Config(
            connect_timeout=3, read_timeout=60, retries={'max_attempts': 1})), None, None))
    look = None

    def loop():
        nonlocal look
        while not stop.is_set():
            if active is None or active():
                try:
                    look = look or (make or made)()
                    with scope() as db:
                        look.step(db)
                except Exception:  # noqa: BLE001 - the next notification looks again
                    LOG.exception('drills: look failed')
            wait(60)
    thread = threading.Thread(target=loop, name='drills', daemon=True)
    thread.start()
    return thread
