"""Configuration utilities for CLI."""

import argparse
from typing import Any

from ..config import Config


def build_config_overrides(args: argparse.Namespace) -> dict[str, Any]:
    """Extract configuration overrides from parsed arguments.

    Maps CLI argument names (with hyphens) to config field names (with underscores).
    Only includes arguments that were actually provided (not None).

    Args:
        args: Parsed command-line arguments

    Returns:
        Dictionary of config overrides to pass to Config.from_env()
    """
    # Map of CLI argument names to config field names
    arg_mapping = {
        "driver": "driver",
        "redis_url": "redis_url",
        "redis_password": "redis_password",
        "redis_db": "redis_db",
        "redis_max_connections": "redis_max_connections",
        "sqs_region": "sqs_region",
        "sqs_queue_url_prefix": "sqs_queue_url_prefix",
        "aws_access_key_id": "aws_access_key_id",
        "aws_secret_access_key": "aws_secret_access_key",
        "postgres_dsn": "postgres_dsn",
        "postgres_queue_table": "postgres_queue_table",
        "postgres_dead_letter_table": "postgres_dead_letter_table",
        "mysql_dsn": "mysql_dsn",
        "mysql_queue_table": "mysql_queue_table",
        "mysql_dead_letter_table": "mysql_dead_letter_table",
    }

    overrides: dict[str, Any] = {}
    for arg_name, config_key in arg_mapping.items():
        value = getattr(args, arg_name, None)
        if value is not None:
            overrides[config_key] = value

    return overrides


def build_config(args: argparse.Namespace) -> Config:
    """Build Config object from parsed arguments and environment variables.

    Args:
        args: Parsed command-line arguments

    Returns:
        Configured Config instance
    """
    overrides = build_config_overrides(args)
    return Config.from_env(**overrides)
