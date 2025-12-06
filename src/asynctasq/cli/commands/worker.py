"""Worker command implementation."""

import argparse
import logging

from asynctasq.cli.utils import DEFAULT_CONCURRENCY, parse_queues
from asynctasq.core.driver_factory import DriverFactory
from asynctasq.core.events import create_event_emitter
from asynctasq.core.worker import Worker

logger = logging.getLogger(__name__)


async def run_worker(args: argparse.Namespace, config) -> None:
    """Run the worker command to process tasks from queues.

    Args:
        args: Parsed command-line arguments
        config: Configuration object
    """
    queues = parse_queues(getattr(args, "queues", None))
    concurrency = getattr(args, "concurrency", DEFAULT_CONCURRENCY)

    logger.info(
        f"Starting worker: driver={config.driver}, queues={queues}, concurrency={concurrency}"
    )

    driver = DriverFactory.create_from_config(config)

    # Create event emitter for real-time monitoring (Redis Pub/Sub + logging)
    event_emitter = create_event_emitter()

    worker = Worker(
        queue_driver=driver,
        queues=queues,
        concurrency=concurrency,
        event_emitter=event_emitter,
    )

    try:
        await worker.start()
    finally:
        await event_emitter.close()
