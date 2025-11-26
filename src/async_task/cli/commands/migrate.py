"""Migrate command implementation."""

import argparse
import logging

from ...config import Config
from ...core.driver_factory import DriverFactory
from ...drivers.mysql_driver import MySQLDriver
from ...drivers.postgres_driver import PostgresDriver

logger = logging.getLogger(__name__)


class MigrationError(Exception):
    """Raised when migration fails."""


async def run_migrate(args: argparse.Namespace, config: Config) -> None:
    """Run the migrate command to initialize database schema.

    Supports both PostgreSQL and MySQL drivers.

    Args:
        args: Parsed command-line arguments
        config: Configuration object

    Raises:
        MigrationError: If migration fails or driver is not supported.
    """
    if config.driver == "postgres":
        logger.info("Initializing PostgreSQL schema...")
        logger.info(f"  DSN: {config.postgres_dsn}")
        logger.info(f"  Queue table: {config.postgres_queue_table}")
        logger.info(f"  Dead letter table: {config.postgres_dead_letter_table}")

        driver = DriverFactory.create_from_config(config, driver_type="postgres")

        if not isinstance(driver, PostgresDriver):
            raise MigrationError("Driver factory did not return a PostgresDriver instance")

        try:
            await driver.connect()
            await driver.init_schema()

            logger.info("✓ Schema initialized successfully!")
            logger.info(f"  - Created table: {config.postgres_queue_table}")
            logger.info(f"  - Created index: idx_{config.postgres_queue_table}_lookup")
            logger.info(f"  - Created table: {config.postgres_dead_letter_table}")
        finally:
            await driver.disconnect()

    elif config.driver == "mysql":
        logger.info("Initializing MySQL schema...")
        logger.info(f"  DSN: {config.mysql_dsn}")
        logger.info(f"  Queue table: {config.mysql_queue_table}")
        logger.info(f"  Dead letter table: {config.mysql_dead_letter_table}")

        driver = DriverFactory.create_from_config(config, driver_type="mysql")

        if not isinstance(driver, MySQLDriver):
            raise MigrationError("Driver factory did not return a MySQLDriver instance")

        try:
            await driver.connect()
            await driver.init_schema()

            logger.info("✓ Schema initialized successfully!")
            logger.info(f"  - Created table: {config.mysql_queue_table}")
            logger.info(f"  - Created index: idx_{config.mysql_queue_table}_lookup")
            logger.info(f"  - Created table: {config.mysql_dead_letter_table}")
        finally:
            await driver.disconnect()

    else:
        raise MigrationError(
            f"Migration is only supported for PostgreSQL and MySQL drivers. "
            f"Current driver: {config.driver}. Use --driver postgres or --driver mysql to migrate."
        )
