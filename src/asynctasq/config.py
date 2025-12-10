from collections.abc import Callable
from dataclasses import dataclass
import os
from typing import Any

from asynctasq.drivers import DriverType

# Environment variable mapping: field_name -> (env_var, default_value, type_converter)
ENV_VAR_MAPPING: dict[str, tuple[str, Any, Callable[[str], Any]]] = {
    # Driver selection
    "driver": ("asynctasq_DRIVER", "redis", str),
    # Redis configuration
    "redis_url": ("asynctasq_REDIS_URL", "redis://localhost:6379", str),
    "redis_password": ("asynctasq_REDIS_PASSWORD", None, str),
    "redis_db": ("asynctasq_REDIS_DB", "0", int),
    "redis_max_connections": ("asynctasq_REDIS_MAX_CONNECTIONS", "10", int),
    # SQS configuration
    "sqs_region": ("asynctasq_SQS_REGION", "us-east-1", str),
    "sqs_queue_url_prefix": ("asynctasq_SQS_QUEUE_PREFIX", None, str),
    "aws_access_key_id": ("AWS_ACCESS_KEY_ID", None, str),
    "aws_secret_access_key": ("AWS_SECRET_ACCESS_KEY", None, str),
    # PostgreSQL configuration
    "postgres_dsn": (
        "asynctasq_POSTGRES_DSN",
        "postgresql://test:test@localhost:5432/test_db",
        str,
    ),
    "postgres_queue_table": ("asynctasq_POSTGRES_QUEUE_TABLE", "task_queue", str),
    "postgres_dead_letter_table": (
        "asynctasq_POSTGRES_DEAD_LETTER_TABLE",
        "dead_letter_queue",
        str,
    ),
    "postgres_max_attempts": ("asynctasq_POSTGRES_MAX_ATTEMPTS", "3", int),
    "postgres_retry_delay_seconds": ("asynctasq_POSTGRES_RETRY_DELAY_SECONDS", "60", int),
    "postgres_visibility_timeout_seconds": (
        "asynctasq_POSTGRES_VISIBILITY_TIMEOUT_SECONDS",
        "300",
        int,
    ),
    "postgres_min_pool_size": ("asynctasq_POSTGRES_MIN_POOL_SIZE", "10", int),
    "postgres_max_pool_size": ("asynctasq_POSTGRES_MAX_POOL_SIZE", "10", int),
    # MySQL configuration
    "mysql_dsn": (
        "asynctasq_MYSQL_DSN",
        "mysql://test:test@localhost:3306/test_db",
        str,
    ),
    "mysql_queue_table": ("asynctasq_MYSQL_QUEUE_TABLE", "task_queue", str),
    "mysql_dead_letter_table": (
        "asynctasq_MYSQL_DEAD_LETTER_TABLE",
        "dead_letter_queue",
        str,
    ),
    "mysql_max_attempts": ("asynctasq_MYSQL_MAX_ATTEMPTS", "3", int),
    "mysql_retry_delay_seconds": ("asynctasq_MYSQL_RETRY_DELAY_SECONDS", "60", int),
    "mysql_visibility_timeout_seconds": (
        "asynctasq_MYSQL_VISIBILITY_TIMEOUT_SECONDS",
        "300",
        int,
    ),
    "mysql_min_pool_size": ("asynctasq_MYSQL_MIN_POOL_SIZE", "10", int),
    "mysql_max_pool_size": ("asynctasq_MYSQL_MAX_POOL_SIZE", "10", int),
    # RabbitMQ configuration
    "rabbitmq_url": ("asynctasq_RABBITMQ_URL", "amqp://guest:guest@localhost:5672/", str),
    "rabbitmq_exchange_name": ("asynctasq_RABBITMQ_EXCHANGE_NAME", "asynctasq", str),
    "rabbitmq_prefetch_count": ("asynctasq_RABBITMQ_PREFETCH_COUNT", "1", int),
    # Events/Monitoring configuration
    "events_redis_url": ("asynctasq_EVENTS_REDIS_URL", None, str),
    "events_channel": ("asynctasq_EVENTS_CHANNEL", "asynctasq:events", str),
    # Task defaults
    "default_queue": ("asynctasq_DEFAULT_QUEUE", "default", str),
    "default_max_retries": ("asynctasq_MAX_RETRIES", "3", int),
    "default_retry_delay": ("asynctasq_RETRY_DELAY", "60", int),
    "default_timeout": ("asynctasq_TIMEOUT", None, int),
    # ProcessTask/ProcessPoolExecutor configuration
    "process_pool_size": ("asynctasq_PROCESS_POOL_SIZE", None, int),
    "process_pool_max_tasks_per_child": ("asynctasq_PROCESS_POOL_MAX_TASKS_PER_CHILD", None, int),
}


@dataclass
class Config:
    """Configuration for AsyncTasQ library"""

    # Driver selection
    driver: DriverType = "redis"

    # Redis configuration
    redis_url: str = "redis://localhost:6379"
    redis_password: str | None = None
    redis_db: int = 0
    redis_max_connections: int = 10

    # SQS configuration
    sqs_region: str = "us-east-1"
    sqs_queue_url_prefix: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None

    # PostgreSQL configuration
    postgres_dsn: str = "postgresql://test:test@localhost:5432/test_db"
    postgres_queue_table: str = "task_queue"
    postgres_dead_letter_table: str = "dead_letter_queue"
    postgres_max_attempts: int = 3
    postgres_retry_delay_seconds: int = 60
    postgres_visibility_timeout_seconds: int = 300
    postgres_min_pool_size: int = 10
    postgres_max_pool_size: int = 10

    # MySQL configuration
    mysql_dsn: str = "mysql://test:test@localhost:3306/test_db"
    mysql_queue_table: str = "task_queue"
    mysql_dead_letter_table: str = "dead_letter_queue"
    mysql_max_attempts: int = 3
    mysql_retry_delay_seconds: int = 60
    mysql_visibility_timeout_seconds: int = 300
    mysql_min_pool_size: int = 10
    mysql_max_pool_size: int = 10

    # RabbitMQ configuration
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    rabbitmq_exchange_name: str = "asynctasq"
    rabbitmq_prefetch_count: int = 1

    # Events/Monitoring configuration
    # If None, falls back to redis_url for Pub/Sub events
    events_redis_url: str | None = None
    events_channel: str = "asynctasq:events"

    # Task defaults
    default_queue: str = "default"
    default_max_retries: int = 3
    default_retry_delay: int = 60
    default_timeout: int | None = None

    # ProcessTask/ProcessPoolExecutor configuration
    # If None, ProcessTask will auto-initialize using os.process_cpu_count() or 4
    process_pool_size: int | None = None
    # If None, worker processes live until pool shutdown (no recycling)
    # Recommended: 100-1000 to prevent memory leaks (Python 3.11+)
    process_pool_max_tasks_per_child: int | None = None

    @staticmethod
    def from_env(**overrides) -> "Config":
        """Load configuration from environment variables"""
        config_dict = {}

        for field_name, (env_var, default_value, type_converter) in ENV_VAR_MAPPING.items():
            env_value = os.getenv(env_var)

            if env_value is None:
                # Use default value, converting if not None
                if default_value is not None:
                    config_dict[field_name] = type_converter(default_value)
                else:
                    config_dict[field_name] = None
            else:
                # Convert the string value to appropriate type
                config_dict[field_name] = type_converter(env_value)

        # Apply overrides
        config_dict.update(overrides)

        Config._validate(config_dict)

        return Config(**config_dict)

    @staticmethod
    def _validate(config: dict):
        """Validate configuration after initialization."""
        if config["redis_db"] < 0 or config["redis_db"] > 15:
            raise ValueError("redis_db must be between 0 and 15")
        if config["redis_max_connections"] < 1:
            raise ValueError("redis_max_connections must be positive")
        if config["default_max_retries"] < 0:
            raise ValueError("default_max_retries must be non-negative")
        if config["default_retry_delay"] < 0:
            raise ValueError("default_retry_delay must be non-negative")
        if config["postgres_max_attempts"] < 1:
            raise ValueError("postgres_max_attempts must be positive")
        if config["postgres_retry_delay_seconds"] < 0:
            raise ValueError("postgres_retry_delay_seconds must be non-negative")
        if config["postgres_visibility_timeout_seconds"] < 1:
            raise ValueError("postgres_visibility_timeout_seconds must be positive")
        if config["postgres_min_pool_size"] < 1:
            raise ValueError("postgres_min_pool_size must be positive")
        if config["postgres_max_pool_size"] < 1:
            raise ValueError("postgres_max_pool_size must be positive")
        if config["postgres_min_pool_size"] > config["postgres_max_pool_size"]:
            raise ValueError("postgres_min_pool_size cannot be greater than postgres_max_pool_size")
        if config.get("mysql_max_attempts", 3) < 1:
            raise ValueError("mysql_max_attempts must be positive")
        if config.get("mysql_retry_delay_seconds", 60) < 0:
            raise ValueError("mysql_retry_delay_seconds must be non-negative")
        if config.get("mysql_visibility_timeout_seconds", 300) < 1:
            raise ValueError("mysql_visibility_timeout_seconds must be positive")
        if config.get("mysql_min_pool_size", 10) < 1:
            raise ValueError("mysql_min_pool_size must be positive")
        if config.get("mysql_max_pool_size", 10) < 1:
            raise ValueError("mysql_max_pool_size must be positive")
        if config.get("mysql_min_pool_size", 10) > config.get("mysql_max_pool_size", 10):
            raise ValueError("mysql_min_pool_size cannot be greater than mysql_max_pool_size")


_global_config: Config | None = None


def set_global_config(**overrides) -> None:
    """Set global configuration for the asynctasq library.

    This function sets the global configuration that will be used by all tasks
    and workers. Configuration can be provided via keyword arguments, which
    override environment variables and defaults.

    Args:
        **overrides: Configuration options to override. All options can also be
            set via environment variables (see below for mappings).

    General Options:
        driver (str): Queue driver to use. Choices: "redis", "sqs", "postgres", "mysql", "rabbitmq"
            Env var: asynctasq_DRIVER
            Default: "redis"

        default_queue (str): Default queue name for tasks
            Env var: asynctasq_DEFAULT_QUEUE
            Default: "default"

        default_max_retries (int): Default maximum retry attempts for tasks
            Env var: asynctasq_MAX_RETRIES
            Default: 3

        default_retry_delay (int): Default retry delay in seconds
            Env var: asynctasq_RETRY_DELAY
            Default: 60

        default_timeout (int | None): Default task timeout in seconds (None = no timeout)
            Env var: asynctasq_TIMEOUT
            Default: None

    Redis Options:
        redis_url (str): Redis connection URL
            Env var: asynctasq_REDIS_URL
            Default: "redis://localhost:6379"

        redis_password (str | None): Redis password
            Env var: asynctasq_REDIS_PASSWORD
            Default: None

        redis_db (int): Redis database number (0-15)
            Env var: asynctasq_REDIS_DB
            Default: 0

        redis_max_connections (int): Maximum number of connections in Redis pool
            Env var: asynctasq_REDIS_MAX_CONNECTIONS
            Default: 10

    PostgreSQL Options:
        postgres_dsn (str): PostgreSQL connection DSN
            Env var: asynctasq_POSTGRES_DSN
            Default: "postgresql://test:test@localhost:5432/test_db"

        postgres_queue_table (str): PostgreSQL queue table name
            Env var: asynctasq_POSTGRES_QUEUE_TABLE
            Default: "task_queue"

        postgres_dead_letter_table (str): PostgreSQL dead letter table name
            Env var: asynctasq_POSTGRES_DEAD_LETTER_TABLE
            Default: "dead_letter_queue"

        postgres_max_attempts (int): Maximum attempts before moving to dead letter queue
            Env var: asynctasq_POSTGRES_MAX_ATTEMPTS
            Default: 3

        postgres_retry_delay_seconds (int): Retry delay in seconds for PostgreSQL driver
            Env var: asynctasq_POSTGRES_RETRY_DELAY_SECONDS
            Default: 60

        postgres_visibility_timeout_seconds (int): Visibility timeout in seconds
            Env var: asynctasq_POSTGRES_VISIBILITY_TIMEOUT_SECONDS
            Default: 300

        postgres_min_pool_size (int): Minimum connection pool size
            Env var: asynctasq_POSTGRES_MIN_POOL_SIZE
            Default: 10

        postgres_max_pool_size (int): Maximum connection pool size
            Env var: asynctasq_POSTGRES_MAX_POOL_SIZE
            Default: 10

    MySQL Options:
        mysql_dsn (str): MySQL connection DSN
            Env var: asynctasq_MYSQL_DSN
            Default: "mysql://test:test@localhost:3306/test_db"

        mysql_queue_table (str): MySQL queue table name
            Env var: asynctasq_MYSQL_QUEUE_TABLE
            Default: "task_queue"

        mysql_dead_letter_table (str): MySQL dead letter table name
            Env var: asynctasq_MYSQL_DEAD_LETTER_TABLE
            Default: "dead_letter_queue"

        mysql_max_attempts (int): Maximum attempts before moving to dead letter queue
            Env var: asynctasq_MYSQL_MAX_ATTEMPTS
            Default: 3

        mysql_retry_delay_seconds (int): Retry delay in seconds for MySQL driver
            Env var: asynctasq_MYSQL_RETRY_DELAY_SECONDS
            Default: 60

        mysql_visibility_timeout_seconds (int): Visibility timeout in seconds
            Env var: asynctasq_MYSQL_VISIBILITY_TIMEOUT_SECONDS
            Default: 300

        mysql_min_pool_size (int): Minimum connection pool size
            Env var: asynctasq_MYSQL_MIN_POOL_SIZE
            Default: 10

        mysql_max_pool_size (int): Maximum connection pool size
            Env var: asynctasq_MYSQL_MAX_POOL_SIZE
            Default: 10

    SQS Options:
        sqs_region (str): AWS SQS region
            Env var: asynctasq_SQS_REGION
            Default: "us-east-1"

        sqs_queue_url_prefix (str | None): SQS queue URL prefix
            Env var: asynctasq_SQS_QUEUE_PREFIX
            Default: None

        aws_access_key_id (str | None): AWS access key ID
            Env var: AWS_ACCESS_KEY_ID
            Default: None (uses AWS credential chain)

        aws_secret_access_key (str | None): AWS secret access key
            Env var: AWS_SECRET_ACCESS_KEY
            Default: None (uses AWS credential chain)

    RabbitMQ Options:
        rabbitmq_url (str): RabbitMQ connection URL
            Env var: asynctasq_RABBITMQ_URL
            Default: "amqp://guest:guest@localhost:5672/"

        rabbitmq_exchange_name (str): RabbitMQ exchange name
            Env var: asynctasq_RABBITMQ_EXCHANGE_NAME
            Default: "asynctasq"

        rabbitmq_prefetch_count (int): RabbitMQ consumer prefetch count
            Env var: asynctasq_RABBITMQ_PREFETCH_COUNT
            Default: 1

    Events/Monitoring Options:
        events_redis_url (str | None): Redis URL for event Pub/Sub (monitor integration)
            Env var: asynctasq_EVENTS_REDIS_URL
            Default: None (falls back to redis_url)

        events_channel (str): Redis Pub/Sub channel for events
            Env var: asynctasq_EVENTS_CHANNEL
            Default: "asynctasq:events"

    Examples:
        # Basic configuration with Redis
        set_global_config(
            driver='redis',
            redis_url='redis://localhost:6379',
            default_queue='default'
        )

        # PostgreSQL with custom settings
        set_global_config(
            driver='postgres',
            postgres_dsn='postgresql://user:pass@localhost:5432/mydb',
            postgres_queue_table='my_queue',
            postgres_max_attempts=5,
            postgres_min_pool_size=5,
            postgres_max_pool_size=20
        )

        # MySQL with custom settings
        set_global_config(
            driver='mysql',
            mysql_dsn='mysql://user:pass@localhost:3306/mydb',
            mysql_queue_table='my_queue',
            mysql_max_attempts=5,
            mysql_min_pool_size=5,
            mysql_max_pool_size=20
        )

        # SQS configuration
        set_global_config(
            driver='sqs',
            sqs_region='us-west-2',
            sqs_queue_url_prefix='https://sqs.us-west-2.amazonaws.com/123456789/',
            aws_access_key_id='your_key',
            aws_secret_access_key='your_secret'
        )

        # RabbitMQ configuration
        set_global_config(
            driver='rabbitmq',
            rabbitmq_url='amqp://user:pass@localhost:5672/',
            rabbitmq_exchange_name='my_exchange',
            rabbitmq_prefetch_count=10
        )

        # Task defaults
        set_global_config(
            default_max_retries=5,
            default_retry_delay=120,
            default_timeout=300
        )

    Note:
        Configuration precedence (highest to lowest):
        1. Keyword arguments to set_global_config()
        2. Environment variables
        3. Default values
    """
    global _global_config
    _global_config = Config.from_env(**overrides)


def get_global_config() -> Config:
    """Get global configuration for the asynctasq library, initializing from environment if not set"""
    global _global_config
    if _global_config is None:
        _global_config = Config.from_env()

    return _global_config
