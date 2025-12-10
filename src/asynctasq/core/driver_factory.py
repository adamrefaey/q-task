from typing import Any, get_args

from asynctasq.config import Config
from asynctasq.drivers import DriverType
from asynctasq.drivers.base_driver import BaseDriver


class DriverFactory:
    """Factory for creating queue drivers from configuration.

    Provides a unified interface for instantiating queue drivers without
    coupling code to specific driver implementations. Supports switching
    drivers by changing configuration only.
    """

    @staticmethod
    def create_from_config(config: Config, driver_type: DriverType | None = None) -> BaseDriver:
        """Create driver from configuration object.

        Args:
            config: Config instance
            driver_type: Optional driver type to override config.driver
                        Useful for testing or runtime driver switching

        Returns:
            Configured BaseDriver instance

        Raises:
            ValueError: If driver type is unknown
        """
        return DriverFactory.create(
            driver_type if driver_type is not None else config.driver,
            redis_url=config.redis_url,
            redis_password=config.redis_password,
            redis_db=config.redis_db,
            redis_max_connections=config.redis_max_connections,
            sqs_region=config.sqs_region,
            sqs_queue_url_prefix=config.sqs_queue_url_prefix,
            aws_access_key_id=config.aws_access_key_id,
            aws_secret_access_key=config.aws_secret_access_key,
            postgres_dsn=config.postgres_dsn,
            postgres_queue_table=config.postgres_queue_table,
            postgres_dead_letter_table=config.postgres_dead_letter_table,
            postgres_max_attempts=config.postgres_max_attempts,
            postgres_retry_delay_seconds=config.postgres_retry_delay_seconds,
            postgres_visibility_timeout_seconds=config.postgres_visibility_timeout_seconds,
            postgres_min_pool_size=config.postgres_min_pool_size,
            postgres_max_pool_size=config.postgres_max_pool_size,
            mysql_dsn=config.mysql_dsn,
            mysql_queue_table=config.mysql_queue_table,
            mysql_dead_letter_table=config.mysql_dead_letter_table,
            mysql_max_attempts=config.mysql_max_attempts,
            mysql_retry_delay_seconds=config.mysql_retry_delay_seconds,
            mysql_visibility_timeout_seconds=config.mysql_visibility_timeout_seconds,
            mysql_min_pool_size=config.mysql_min_pool_size,
            mysql_max_pool_size=config.mysql_max_pool_size,
            rabbitmq_url=config.rabbitmq_url,
            rabbitmq_exchange_name=config.rabbitmq_exchange_name,
            rabbitmq_prefetch_count=config.rabbitmq_prefetch_count,
            keep_completed_tasks=config.keep_completed_tasks,
        )

    @staticmethod
    def create(driver_type: DriverType, **kwargs: Any) -> BaseDriver:
        """Create driver by type with specific configuration.

        Args:
            driver_type: Type of driver
            **kwargs: Driver-specific configuration

        Returns:
            Configured BaseDriver instance

        Raises:
            ValueError: If driver type is unknown

        """
        match driver_type:
            case "redis":
                from asynctasq.drivers.redis_driver import RedisDriver

                return RedisDriver(
                    url=kwargs.get("redis_url", "redis://localhost:6379"),
                    password=kwargs.get("redis_password"),
                    db=kwargs.get("redis_db", 0),
                    max_connections=kwargs.get("redis_max_connections", 10),
                    keep_completed_tasks=kwargs.get("keep_completed_tasks", False),
                )
            case "sqs":
                from asynctasq.drivers.sqs_driver import SQSDriver

                return SQSDriver(
                    region_name=kwargs.get("sqs_region", "us-east-1"),
                    queue_url_prefix=kwargs.get("sqs_queue_url_prefix"),
                    aws_access_key_id=kwargs.get("aws_access_key_id"),
                    aws_secret_access_key=kwargs.get("aws_secret_access_key"),
                )
            case "postgres":
                from asynctasq.drivers.postgres_driver import PostgresDriver

                return PostgresDriver(
                    dsn=kwargs.get("postgres_dsn", "postgresql://user:pass@localhost/dbname"),
                    queue_table=kwargs.get("postgres_queue_table", "task_queue"),
                    dead_letter_table=kwargs.get("postgres_dead_letter_table", "dead_letter_queue"),
                    max_attempts=kwargs.get("postgres_max_attempts", 3),
                    retry_delay_seconds=kwargs.get("postgres_retry_delay_seconds", 60),
                    visibility_timeout_seconds=kwargs.get(
                        "postgres_visibility_timeout_seconds", 300
                    ),
                    min_pool_size=kwargs.get("postgres_min_pool_size", 10),
                    max_pool_size=kwargs.get("postgres_max_pool_size", 10),
                    keep_completed_tasks=kwargs.get("keep_completed_tasks", False),
                )
            case "mysql":
                from asynctasq.drivers.mysql_driver import MySQLDriver

                return MySQLDriver(
                    dsn=kwargs.get("mysql_dsn", "mysql://user:pass@localhost:3306/dbname"),
                    queue_table=kwargs.get("mysql_queue_table", "task_queue"),
                    dead_letter_table=kwargs.get("mysql_dead_letter_table", "dead_letter_queue"),
                    max_attempts=kwargs.get("mysql_max_attempts", 3),
                    retry_delay_seconds=kwargs.get("mysql_retry_delay_seconds", 60),
                    visibility_timeout_seconds=kwargs.get("mysql_visibility_timeout_seconds", 300),
                    min_pool_size=kwargs.get("mysql_min_pool_size", 10),
                    max_pool_size=kwargs.get("mysql_max_pool_size", 10),
                    keep_completed_tasks=kwargs.get("keep_completed_tasks", False),
                )
            case "rabbitmq":
                from asynctasq.drivers.rabbitmq_driver import RabbitMQDriver

                return RabbitMQDriver(
                    url=kwargs.get("rabbitmq_url", "amqp://guest:guest@localhost:5672/"),
                    exchange_name=kwargs.get("rabbitmq_exchange_name", "asynctasq"),
                    prefetch_count=kwargs.get("rabbitmq_prefetch_count", 1),
                    keep_completed_tasks=kwargs.get("keep_completed_tasks", False),
                )
            case _:
                raise ValueError(
                    f"Unknown driver type: {driver_type}. "
                    f"Supported types: {', '.join(list(get_args(DriverType)))}"
                )
