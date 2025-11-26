"""Argument parser for CLI commands."""

import argparse

from .utils import DEFAULT_CONCURRENCY, DEFAULT_QUEUE


def add_driver_args(parser: argparse.ArgumentParser, default_driver: str | None = None) -> None:
    """Add common driver configuration arguments to a parser.

    Args:
        parser: Argument parser to add driver arguments to
        default_driver: Optional default driver value to use if not specified
    """
    # Driver selection
    parser.add_argument(
        "--driver",
        type=str,
        choices=["redis", "sqs", "memory", "postgres", "mysql"],
        default=default_driver,
        help="Queue driver to use (default: from ASYNC_TASK_DRIVER env var or 'redis')",
    )

    # Redis options
    redis_group = parser.add_argument_group("Redis options")
    redis_group.add_argument(
        "--redis-url",
        type=str,
        help="Redis connection URL (default: from ASYNC_TASK_REDIS_URL env var or 'redis://localhost:6379')",
    )
    redis_group.add_argument(
        "--redis-password",
        type=str,
        help="Redis password (default: from ASYNC_TASK_REDIS_PASSWORD env var)",
    )
    redis_group.add_argument(
        "--redis-db",
        type=int,
        help="Redis database number (default: from ASYNC_TASK_REDIS_DB env var or 0)",
    )
    redis_group.add_argument(
        "--redis-max-connections",
        type=int,
        help="Redis max connections (default: from ASYNC_TASK_REDIS_MAX_CONNECTIONS env var or 10)",
    )

    # SQS options
    sqs_group = parser.add_argument_group("SQS options")
    sqs_group.add_argument(
        "--sqs-region",
        type=str,
        help="AWS SQS region (default: from ASYNC_TASK_SQS_REGION env var or 'us-east-1')",
    )
    sqs_group.add_argument(
        "--sqs-queue-url-prefix",
        type=str,
        help="SQS queue URL prefix (default: from ASYNC_TASK_SQS_QUEUE_PREFIX env var)",
    )
    sqs_group.add_argument(
        "--aws-access-key-id",
        type=str,
        help="AWS access key ID (default: from AWS_ACCESS_KEY_ID env var)",
    )
    sqs_group.add_argument(
        "--aws-secret-access-key",
        type=str,
        help="AWS secret access key (default: from AWS_SECRET_ACCESS_KEY env var)",
    )

    # PostgreSQL options
    postgres_group = parser.add_argument_group("PostgreSQL options")
    postgres_group.add_argument(
        "--postgres-dsn",
        type=str,
        help="PostgreSQL connection DSN (default: from ASYNC_TASK_POSTGRES_DSN env var)",
    )
    postgres_group.add_argument(
        "--postgres-queue-table",
        type=str,
        help="PostgreSQL queue table name (default: from ASYNC_TASK_POSTGRES_QUEUE_TABLE env var or 'task_queue')",
    )
    postgres_group.add_argument(
        "--postgres-dead-letter-table",
        type=str,
        help="PostgreSQL dead letter table name (default: from ASYNC_TASK_POSTGRES_DEAD_LETTER_TABLE env var or 'dead_letter_queue')",
    )

    # MySQL options
    mysql_group = parser.add_argument_group("MySQL options")
    mysql_group.add_argument(
        "--mysql-dsn",
        type=str,
        help="MySQL connection DSN (default: from ASYNC_TASK_MYSQL_DSN env var)",
    )
    mysql_group.add_argument(
        "--mysql-queue-table",
        type=str,
        help="MySQL queue table name (default: from ASYNC_TASK_MYSQL_QUEUE_TABLE env var or 'task_queue')",
    )
    mysql_group.add_argument(
        "--mysql-dead-letter-table",
        type=str,
        help="MySQL dead letter table name (default: from ASYNC_TASK_MYSQL_DEAD_LETTER_TABLE env var or 'dead_letter_queue')",
    )


def create_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser.

    Returns:
        Configured argument parser with all subcommands
    """
    parser = argparse.ArgumentParser(
        description="Async Task - Task queue system for Python",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(
        dest="command",
        help="Available commands",
        required=True,
    )

    # Worker subcommand
    worker_parser = subparsers.add_parser(
        "worker",
        description="Start a worker to process tasks from queues",
        help="Start a worker to process tasks",
    )
    add_driver_args(worker_parser)
    worker_parser.add_argument(
        "--queues",
        type=str,
        help=f"Comma-separated list of queue names to process (default: '{DEFAULT_QUEUE}')",
    )
    worker_parser.add_argument(
        "--concurrency",
        type=int,
        help=f"Maximum number of concurrent tasks (default: {DEFAULT_CONCURRENCY})",
        default=DEFAULT_CONCURRENCY,
    )

    # Migrate subcommand
    migrate_parser = subparsers.add_parser(
        "migrate",
        description="Initialize database schema for PostgreSQL or MySQL driver",
        help="Initialize database schema",
    )
    add_driver_args(migrate_parser, default_driver="postgres")

    return parser
