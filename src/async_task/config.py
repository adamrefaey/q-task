import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias

DriverType: TypeAlias = Literal["redis", "sqs", "memory", "postgres"]


# Environment variable mapping: field_name -> (env_var, default_value, type_converter)
ENV_VAR_MAPPING: dict[str, tuple[str, Any, Callable[[str], Any]]] = {
    # Driver selection
    "driver": ("ASYNC_TASK_DRIVER", "redis", str),
    # Redis configuration
    "redis_url": ("ASYNC_TASK_REDIS_URL", "redis://localhost:6379", str),
    "redis_password": ("ASYNC_TASK_REDIS_PASSWORD", None, str),
    "redis_db": ("ASYNC_TASK_REDIS_DB", "0", int),
    "redis_max_connections": ("ASYNC_TASK_REDIS_MAX_CONNECTIONS", "10", int),
    # SQS configuration
    "sqs_region": ("ASYNC_TASK_SQS_REGION", "us-east-1", str),
    "sqs_queue_url_prefix": ("ASYNC_TASK_SQS_QUEUE_PREFIX", None, str),
    "aws_access_key_id": ("AWS_ACCESS_KEY_ID", None, str),
    "aws_secret_access_key": ("AWS_SECRET_ACCESS_KEY", None, str),
    # PostgreSQL configuration
    "postgres_dsn": (
        "ASYNC_TASK_POSTGRES_DSN",
        "postgresql://test:test@localhost:5432/test_db",
        str,
    ),
    "postgres_queue_table": ("ASYNC_TASK_POSTGRES_QUEUE_TABLE", "task_queue", str),
    "postgres_dead_letter_table": (
        "ASYNC_TASK_POSTGRES_DEAD_LETTER_TABLE",
        "dead_letter_queue",
        str,
    ),
    "postgres_max_attempts": ("ASYNC_TASK_POSTGRES_MAX_ATTEMPTS", "3", int),
    "postgres_retry_delay_seconds": ("ASYNC_TASK_POSTGRES_RETRY_DELAY_SECONDS", "60", int),
    "postgres_visibility_timeout_seconds": (
        "ASYNC_TASK_POSTGRES_VISIBILITY_TIMEOUT_SECONDS",
        "300",
        int,
    ),
    "postgres_min_pool_size": ("ASYNC_TASK_POSTGRES_MIN_POOL_SIZE", "10", int),
    "postgres_max_pool_size": ("ASYNC_TASK_POSTGRES_MAX_POOL_SIZE", "10", int),
    # Task defaults
    "default_queue": ("ASYNC_TASK_DEFAULT_QUEUE", "default", str),
    "default_max_retries": ("ASYNC_TASK_MAX_RETRIES", "3", int),
    "default_retry_delay": ("ASYNC_TASK_RETRY_DELAY", "60", int),
    "default_timeout": ("ASYNC_TASK_TIMEOUT", None, int),
}


@dataclass
class Config:
    """Configuration for Async Task library"""

    # Driver selection
    driver: DriverType = "memory"

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

    # Task defaults
    default_queue: str = "default"
    default_max_retries: int = 3
    default_retry_delay: int = 60
    default_timeout: int | None = None

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


_global_config: Config | None = None


def set_global_config(**overrides) -> None:
    """Set global configuration for the async_task library"""
    global _global_config
    _global_config = Config.from_env(**overrides)


def get_global_config() -> Config:
    """Get global configuration for the async_task library, initializing from environment if not set"""
    global _global_config
    if _global_config is None:
        _global_config = Config.from_env()

    return _global_config
