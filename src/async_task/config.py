import os
from dataclasses import dataclass
from typing import Literal, TypeAlias

DriverType: TypeAlias = Literal["redis", "sqs", "memory"]


@dataclass
class Config:
    """Configuration for Async Task library"""

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

    # Task defaults
    default_queue: str = "default"
    default_max_retries: int = 3
    default_retry_delay: int = 60
    default_timeout: int | None = None

    @staticmethod
    def from_env(**overrides) -> "Config":
        """Load configuration from environment variables"""
        config_dict = {
            "driver": os.getenv("ASYNC_TASK_DRIVER", "redis"),
            "redis_url": os.getenv("ASYNC_TASK_REDIS_URL", "redis://localhost:6379"),
            "redis_password": os.getenv("ASYNC_TASK_REDIS_PASSWORD"),
            "redis_db": int(os.getenv("ASYNC_TASK_REDIS_DB", "0")),
            "redis_max_connections": int(os.getenv("ASYNC_TASK_REDIS_MAX_CONNECTIONS", "10")),
            "sqs_region": os.getenv("ASYNC_TASK_SQS_REGION", "us-east-1"),
            "sqs_queue_url_prefix": os.getenv("ASYNC_TASK_SQS_QUEUE_PREFIX"),
            "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID"),
            "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
            "default_queue": os.getenv("ASYNC_TASK_DEFAULT_QUEUE", "default"),
            "default_max_retries": int(os.getenv("ASYNC_TASK_MAX_RETRIES", "3")),
            "default_retry_delay": int(os.getenv("ASYNC_TASK_RETRY_DELAY", "60")),
            "default_timeout": int(timeout)
            if (timeout := os.getenv("ASYNC_TASK_TIMEOUT"))
            else None,
        }

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
