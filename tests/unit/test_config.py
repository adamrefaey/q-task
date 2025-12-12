"""Unit tests for Config module.

Testing Strategy:
- pytest 9.0.1 with asyncio_mode="auto" (no decorators needed)
- AAA pattern (Arrange, Act, Assert)
- Test configuration loading, validation, and global state
- Mock environment variables for isolation
- Fast, isolated tests
"""

from typing import get_args

from pytest import fixture, main, mark, raises

from asynctasq.config import (
    ENV_VAR_MAPPING,
    Config,
    get_global_config,
    set_global_config,
)
from asynctasq.drivers import DRIVERS, DriverType


@fixture
def clean_env(monkeypatch):
    """Clear all asynctasq environment variables."""
    for _, (env_var, _, _) in ENV_VAR_MAPPING.items():
        monkeypatch.delenv(env_var, raising=False)


@fixture
def reset_global_config():
    """Reset global config before and after each test."""
    import asynctasq.config

    asynctasq.config._global_config = None
    yield
    asynctasq.config._global_config = None


@mark.unit
class TestDriverType:
    """Test DriverType TypeAlias definition."""

    def test_driver_type_contains_all_drivers(self) -> None:
        # Arrange
        expected_drivers = DRIVERS

        # Act
        actual_drivers = get_args(DriverType.__value__)

        # Assert
        assert actual_drivers == expected_drivers

    def test_driver_type_is_literal(self) -> None:
        # Assert
        assert hasattr(DriverType.__value__, "__origin__")


@mark.unit
class TestEnvVarMapping:
    """Test ENV_VAR_MAPPING structure."""

    def test_env_var_mapping_contains_all_fields(self) -> None:
        # Arrange
        expected_fields = {
            "driver",
            "redis_url",
            "redis_password",
            "redis_db",
            "redis_max_connections",
            "sqs_region",
            "sqs_queue_url_prefix",
            "aws_access_key_id",
            "aws_secret_access_key",
            "postgres_dsn",
            "postgres_queue_table",
            "postgres_dead_letter_table",
            "postgres_max_attempts",
            "postgres_retry_delay_seconds",
            "postgres_visibility_timeout_seconds",
            "postgres_min_pool_size",
            "postgres_max_pool_size",
            "mysql_dsn",
            "mysql_queue_table",
            "mysql_dead_letter_table",
            "mysql_max_attempts",
            "mysql_retry_delay_seconds",
            "mysql_visibility_timeout_seconds",
            "mysql_min_pool_size",
            "mysql_max_pool_size",
            "rabbitmq_url",
            "rabbitmq_exchange_name",
            "rabbitmq_prefetch_count",
            "events_redis_url",
            "events_channel",
            "default_queue",
            "default_max_retries",
            "default_retry_delay",
            "default_timeout",
            "process_pool_size",
            "process_pool_max_tasks_per_child",
            "task_scan_limit",
            "keep_completed_tasks",
        }

        # Assert
        assert set(ENV_VAR_MAPPING.keys()) == expected_fields

    def test_env_var_mapping_structure(self) -> None:
        # Act - Check each mapping has correct structure
        for _, mapping in ENV_VAR_MAPPING.items():
            # Assert
            assert isinstance(mapping, tuple)
            assert len(mapping) == 3
            env_var, default_value, type_converter = mapping
            assert isinstance(env_var, str)
            assert callable(type_converter)

    def test_driver_env_var_mapping(self) -> None:
        # Assert
        env_var, default, converter = ENV_VAR_MAPPING["driver"]
        assert env_var == "ASYNCTASQ_DRIVER"
        assert default == "redis"
        assert converter is str


@mark.unit
class TestConfigDefaults:
    """Test Config default values."""

    def test_config_default_driver_is_redis(self) -> None:
        # Act
        config = Config()

        # Assert
        assert config.driver == "redis"

    def test_config_default_redis_settings(self) -> None:
        # Act
        config = Config()

        # Assert
        assert config.redis_url == "redis://localhost:6379"
        assert config.redis_password is None
        assert config.redis_db == 0
        assert config.redis_max_connections == 10

    def test_config_default_sqs_settings(self) -> None:
        # Act
        config = Config()

        # Assert
        assert config.sqs_region == "us-east-1"
        assert config.sqs_queue_url_prefix is None
        assert config.aws_access_key_id is None
        assert config.aws_secret_access_key is None

    def test_config_default_postgres_settings(self) -> None:
        # Act
        config = Config()

        # Assert
        assert config.postgres_dsn == "postgresql://test:test@localhost:5432/test_db"
        assert config.postgres_queue_table == "task_queue"
        assert config.postgres_dead_letter_table == "dead_letter_queue"
        assert config.postgres_max_attempts == 3
        assert config.postgres_retry_delay_seconds == 60
        assert config.postgres_visibility_timeout_seconds == 300
        assert config.postgres_min_pool_size == 10
        assert config.postgres_max_pool_size == 10

    def test_config_default_task_settings(self) -> None:
        # Act
        config = Config()

        # Assert
        assert config.default_queue == "default"
        assert config.default_max_retries == 3
        assert config.default_retry_delay == 60
        assert config.default_timeout is None

    def test_config_default_events_settings(self) -> None:
        # Act
        config = Config()

        # Assert
        assert config.events_redis_url is None  # Falls back to redis_url
        assert config.events_channel == "asynctasq:events"


@mark.unit
class TestConfigFromEnv:
    """Test Config.from_env() method."""

    def test_from_env_with_no_env_vars_uses_defaults(self, clean_env) -> None:
        # Act
        config = Config.from_env()

        # Assert
        assert config.driver == "redis"
        assert config.redis_url == "redis://localhost:6379"
        assert config.default_queue == "default"

    def test_from_env_loads_driver_from_env(self, monkeypatch) -> None:
        # Arrange
        monkeypatch.setenv("ASYNCTASQ_DRIVER", "redis")

        # Act
        config = Config.from_env()

        # Assert
        assert config.driver == "redis"

    def test_from_env_loads_redis_settings(self, monkeypatch) -> None:
        # Arrange
        monkeypatch.setenv("ASYNCTASQ_REDIS_URL", "redis://custom:6380")
        monkeypatch.setenv("ASYNCTASQ_REDIS_PASSWORD", "secret123")
        monkeypatch.setenv("ASYNCTASQ_REDIS_DB", "5")
        monkeypatch.setenv("ASYNCTASQ_REDIS_MAX_CONNECTIONS", "50")

        # Act
        config = Config.from_env()

        # Assert
        assert config.redis_url == "redis://custom:6380"
        assert config.redis_password == "secret123"
        assert config.redis_db == 5
        assert config.redis_max_connections == 50

    def test_from_env_loads_sqs_settings(self, monkeypatch) -> None:
        # Arrange
        monkeypatch.setenv("ASYNCTASQ_SQS_REGION", "us-west-2")
        monkeypatch.setenv("ASYNCTASQ_SQS_QUEUE_PREFIX", "https://sqs.us-west-2/")
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test_key")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test_secret")

        # Act
        config = Config.from_env()

        # Assert
        assert config.sqs_region == "us-west-2"
        assert config.sqs_queue_url_prefix == "https://sqs.us-west-2/"
        assert config.aws_access_key_id == "test_key"
        assert config.aws_secret_access_key == "test_secret"

    def test_from_env_loads_postgres_settings(self, monkeypatch) -> None:
        # Arrange
        monkeypatch.setenv("ASYNCTASQ_POSTGRES_DSN", "postgresql://test:test@db:5432/test")
        monkeypatch.setenv("ASYNCTASQ_POSTGRES_QUEUE_TABLE", "custom_queue")
        monkeypatch.setenv("ASYNCTASQ_POSTGRES_DEAD_LETTER_TABLE", "custom_dlq")
        monkeypatch.setenv("ASYNCTASQ_POSTGRES_MAX_ATTEMPTS", "5")
        monkeypatch.setenv("ASYNCTASQ_POSTGRES_RETRY_DELAY_SECONDS", "120")
        monkeypatch.setenv("ASYNCTASQ_POSTGRES_VISIBILITY_TIMEOUT_SECONDS", "600")
        monkeypatch.setenv("ASYNCTASQ_POSTGRES_MIN_POOL_SIZE", "5")
        monkeypatch.setenv("ASYNCTASQ_POSTGRES_MAX_POOL_SIZE", "20")

        # Act
        config = Config.from_env()

        # Assert
        assert config.postgres_dsn == "postgresql://test:test@db:5432/test"
        assert config.postgres_queue_table == "custom_queue"
        assert config.postgres_dead_letter_table == "custom_dlq"
        assert config.postgres_max_attempts == 5
        assert config.postgres_retry_delay_seconds == 120
        assert config.postgres_visibility_timeout_seconds == 600
        assert config.postgres_min_pool_size == 5
        assert config.postgres_max_pool_size == 20

    def test_from_env_loads_task_defaults(self, monkeypatch) -> None:
        # Arrange
        monkeypatch.setenv("ASYNCTASQ_DEFAULT_QUEUE", "high_priority")
        monkeypatch.setenv("ASYNCTASQ_MAX_RETRIES", "5")
        monkeypatch.setenv("ASYNCTASQ_RETRY_DELAY", "120")
        monkeypatch.setenv("ASYNCTASQ_TIMEOUT", "300")

        # Act
        config = Config.from_env()

        # Assert
        assert config.default_queue == "high_priority"
        assert config.default_max_retries == 5
        assert config.default_retry_delay == 120
        assert config.default_timeout == 300

    def test_from_env_loads_events_settings(self, monkeypatch) -> None:
        # Arrange
        monkeypatch.setenv("ASYNCTASQ_EVENTS_REDIS_URL", "redis://events:6379")
        monkeypatch.setenv("ASYNCTASQ_EVENTS_CHANNEL", "my_app:events")

        # Act
        config = Config.from_env()

        # Assert
        assert config.events_redis_url == "redis://events:6379"
        assert config.events_channel == "my_app:events"

    def test_from_env_events_redis_url_defaults_to_none(self, clean_env) -> None:
        # Act
        config = Config.from_env()

        # Assert - events_redis_url defaults to None (falls back to redis_url at usage time)
        assert config.events_redis_url is None
        assert config.events_channel == "asynctasq:events"

    def test_from_env_with_overrides(self, clean_env) -> None:
        # Act
        config = Config.from_env(
            driver="sqs",
            redis_url="redis://override:6379",
            default_queue="custom",
        )

        # Assert
        assert config.driver == "sqs"
        assert config.redis_url == "redis://override:6379"
        assert config.default_queue == "custom"

    def test_from_env_overrides_take_precedence(self, monkeypatch) -> None:
        # Arrange
        monkeypatch.setenv("ASYNCTASQ_DRIVER", "redis")
        monkeypatch.setenv("ASYNCTASQ_DEFAULT_QUEUE", "from_env")

        # Act
        config = Config.from_env(driver="redis", default_queue="override")

        # Assert
        assert config.driver == "redis"
        assert config.default_queue == "override"

    def test_from_env_converts_integer_types(self, monkeypatch) -> None:
        # Arrange
        monkeypatch.setenv("ASYNCTASQ_REDIS_DB", "10")
        monkeypatch.setenv("ASYNCTASQ_MAX_RETRIES", "7")

        # Act
        config = Config.from_env()

        # Assert
        assert isinstance(config.redis_db, int)
        assert config.redis_db == 10
        assert isinstance(config.default_max_retries, int)
        assert config.default_max_retries == 7


@mark.unit
class TestConfigValidation:
    """Test Config._validate() method."""

    def test_validate_redis_db_below_zero_raises_error(self, clean_env) -> None:
        # Act & Assert
        with raises(ValueError, match="redis_db must be between 0 and 15"):
            Config.from_env(redis_db=-1)

    def test_validate_redis_db_above_15_raises_error(self, clean_env) -> None:
        # Act & Assert
        with raises(ValueError, match="redis_db must be between 0 and 15"):
            Config.from_env(redis_db=16)

    def test_validate_redis_db_boundaries(self, clean_env) -> None:
        # Act & Assert - 0 and 15 should be valid
        config_0 = Config.from_env(redis_db=0)
        config_15 = Config.from_env(redis_db=15)
        assert config_0.redis_db == 0
        assert config_15.redis_db == 15

    def test_validate_redis_max_connections_zero_raises_error(self, clean_env) -> None:
        # Act & Assert
        with raises(ValueError, match="redis_max_connections must be positive"):
            Config.from_env(redis_max_connections=0)

    def test_validate_redis_max_connections_negative_raises_error(self, clean_env) -> None:
        # Act & Assert
        with raises(ValueError, match="redis_max_connections must be positive"):
            Config.from_env(redis_max_connections=-1)

    def test_validate_default_max_retries_negative_raises_error(self, clean_env) -> None:
        # Act & Assert
        with raises(ValueError, match="default_max_retries must be non-negative"):
            Config.from_env(default_max_retries=-1)

    def test_validate_default_max_retries_zero_is_valid(self, clean_env) -> None:
        # Act
        config = Config.from_env(default_max_retries=0)

        # Assert
        assert config.default_max_retries == 0

    def test_validate_default_retry_delay_negative_raises_error(self, clean_env) -> None:
        # Act & Assert
        with raises(ValueError, match="default_retry_delay must be non-negative"):
            Config.from_env(default_retry_delay=-1)

    def test_validate_postgres_max_attempts_zero_raises_error(self, clean_env) -> None:
        # Act & Assert
        with raises(ValueError, match="postgres_max_attempts must be positive"):
            Config.from_env(postgres_max_attempts=0)

    def test_validate_postgres_retry_delay_negative_raises_error(self, clean_env) -> None:
        # Act & Assert
        with raises(ValueError, match="postgres_retry_delay_seconds must be non-negative"):
            Config.from_env(postgres_retry_delay_seconds=-1)

    def test_validate_postgres_visibility_timeout_zero_raises_error(self, clean_env) -> None:
        # Act & Assert
        with raises(ValueError, match="postgres_visibility_timeout_seconds must be positive"):
            Config.from_env(postgres_visibility_timeout_seconds=0)

    def test_validate_postgres_min_pool_size_zero_raises_error(self, clean_env) -> None:
        # Act & Assert
        with raises(ValueError, match="postgres_min_pool_size must be positive"):
            Config.from_env(postgres_min_pool_size=0)

    def test_validate_postgres_max_pool_size_zero_raises_error(self, clean_env) -> None:
        # Act & Assert
        with raises(ValueError, match="postgres_max_pool_size must be positive"):
            Config.from_env(postgres_max_pool_size=0)

    def test_validate_pool_size_min_greater_than_max_raises_error(self, clean_env) -> None:
        # Act & Assert
        with raises(
            ValueError,
            match="postgres_min_pool_size cannot be greater than postgres_max_pool_size",
        ):
            Config.from_env(postgres_min_pool_size=20, postgres_max_pool_size=10)

    def test_validate_pool_size_equal_is_valid(self, clean_env) -> None:
        # Act
        config = Config.from_env(postgres_min_pool_size=10, postgres_max_pool_size=10)

        # Assert
        assert config.postgres_min_pool_size == 10
        assert config.postgres_max_pool_size == 10

    def test_validate_all_valid_values_passes(self, clean_env) -> None:
        # Act & Assert - should not raise
        config = Config.from_env(
            redis_db=5,
            redis_max_connections=20,
            default_max_retries=5,
            default_retry_delay=120,
            postgres_max_attempts=10,
            postgres_retry_delay_seconds=300,
            postgres_visibility_timeout_seconds=600,
            postgres_min_pool_size=5,
            postgres_max_pool_size=50,
        )
        assert config is not None

    # --- MySQL validation tests (merged here to keep config tests together) ---
    def test_validate_mysql_max_attempts_zero_raises_error(self, clean_env) -> None:
        with raises(ValueError, match="mysql_max_attempts must be positive"):
            Config.from_env(mysql_max_attempts=0)

    def test_validate_mysql_max_attempts_negative_raises_error(self, clean_env) -> None:
        with raises(ValueError, match="mysql_max_attempts must be positive"):
            Config.from_env(mysql_max_attempts=-5)

    def test_validate_mysql_retry_delay_negative_raises_error(self, clean_env) -> None:
        with raises(ValueError, match="mysql_retry_delay_seconds must be non-negative"):
            Config.from_env(mysql_retry_delay_seconds=-1)

    def test_validate_mysql_visibility_timeout_zero_raises_error(self, clean_env) -> None:
        with raises(ValueError, match="mysql_visibility_timeout_seconds must be positive"):
            Config.from_env(mysql_visibility_timeout_seconds=0)

    def test_validate_mysql_min_pool_size_zero_raises_error(self, clean_env) -> None:
        with raises(ValueError, match="mysql_min_pool_size must be positive"):
            Config.from_env(mysql_min_pool_size=0)

    def test_validate_mysql_max_pool_size_zero_raises_error(self, clean_env) -> None:
        with raises(ValueError, match="mysql_max_pool_size must be positive"):
            Config.from_env(mysql_max_pool_size=0)

    def test_validate_mysql_min_greater_than_max_raises_error(self, clean_env) -> None:
        with raises(
            ValueError, match="mysql_min_pool_size cannot be greater than mysql_max_pool_size"
        ):
            Config.from_env(mysql_min_pool_size=20, mysql_max_pool_size=10)

    def test_validate_mysql_valid_extreme_values_passes(self, clean_env) -> None:
        config = Config.from_env(
            mysql_max_attempts=10,
            mysql_retry_delay_seconds=0,
            mysql_visibility_timeout_seconds=1,
            mysql_min_pool_size=1,
            mysql_max_pool_size=1000,
        )
        assert config.mysql_max_attempts == 10
        assert config.mysql_retry_delay_seconds == 0
        assert config.mysql_visibility_timeout_seconds == 1
        assert config.mysql_min_pool_size == 1
        assert config.mysql_max_pool_size == 1000


@mark.unit
class TestGlobalConfig:
    """Test global configuration functions."""

    def test_get_global_config_initializes_from_env(self, clean_env, reset_global_config) -> None:
        # Act
        config = get_global_config()

        # Assert
        assert config is not None
        assert isinstance(config, Config)
        assert config.driver == "redis"  # Default

    def test_get_global_config_returns_same_instance(self, clean_env, reset_global_config) -> None:
        # Act
        config1 = get_global_config()
        config2 = get_global_config()

        # Assert
        assert config1 is config2

    def test_set_global_config_creates_new_config(self, clean_env, reset_global_config) -> None:
        # Act
        set_global_config(driver="redis", default_queue="custom")
        config = get_global_config()

        # Assert
        assert config.driver == "redis"
        assert config.default_queue == "custom"

    def test_set_global_config_overrides_previous(self, clean_env, reset_global_config) -> None:
        # Arrange
        set_global_config(driver="redis")

        # Act
        set_global_config(driver="redis")
        config = get_global_config()

        # Assert
        assert config.driver == "redis"

    def test_set_global_config_with_env_vars(self, monkeypatch, reset_global_config) -> None:
        # Arrange
        monkeypatch.setenv("ASYNCTASQ_DRIVER", "sqs")
        monkeypatch.setenv("ASYNCTASQ_DEFAULT_QUEUE", "from_env")

        # Act
        set_global_config(default_queue="override")
        config = get_global_config()

        # Assert
        assert config.driver == "sqs"  # From env
        assert config.default_queue == "override"  # Override

    def test_global_config_isolated_between_calls(self, clean_env, reset_global_config) -> None:
        # Arrange
        set_global_config(driver="redis", default_queue="first")
        first_config = get_global_config()

        # Act
        set_global_config(driver="postgres", default_queue="second")
        second_config = get_global_config()

        # Assert
        assert first_config is not second_config
        assert first_config.driver == "redis"
        assert second_config.driver == "postgres"


@mark.unit
class TestConfigEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_config_with_none_optional_fields(self, clean_env) -> None:
        # Act
        config = Config.from_env(
            redis_password=None,
            sqs_queue_url_prefix=None,
            aws_access_key_id=None,
            aws_secret_access_key=None,
            default_timeout=None,
        )

        # Assert
        assert config.redis_password is None
        assert config.sqs_queue_url_prefix is None
        assert config.aws_access_key_id is None
        assert config.aws_secret_access_key is None
        assert config.default_timeout is None

    def test_config_with_all_drivers(self, clean_env) -> None:
        # Act & Assert - all driver types should be valid
        for driver in get_args(DriverType):
            config = Config.from_env(driver=driver)
            assert config.driver == driver

    def test_config_with_extreme_valid_values(self, clean_env) -> None:
        # Act
        config = Config.from_env(
            redis_db=15,
            redis_max_connections=10000,
            default_max_retries=1000,
            postgres_max_attempts=100,
            postgres_min_pool_size=1,
            postgres_max_pool_size=10000,
        )

        # Assert
        assert config.redis_db == 15
        assert config.redis_max_connections == 10000
        assert config.default_max_retries == 1000
        assert config.postgres_max_attempts == 100
        assert config.postgres_min_pool_size == 1
        assert config.postgres_max_pool_size == 10000

    def test_config_with_zero_valid_values(self, clean_env) -> None:
        # Act
        config = Config.from_env(
            redis_db=0,
            default_max_retries=0,
            default_retry_delay=0,
            postgres_retry_delay_seconds=0,
        )

        # Assert
        assert config.redis_db == 0
        assert config.default_max_retries == 0
        assert config.default_retry_delay == 0
        assert config.postgres_retry_delay_seconds == 0

    def test_config_with_special_characters_in_strings(self, clean_env) -> None:
        # Act
        config = Config.from_env(
            redis_url="redis://user:p@ss!word@host:6379/db",
            postgres_dsn="postgresql://user:p@ss!word@host:5432/db?sslmode=require",
            default_queue="queue:with:colons",
        )

        # Assert
        assert "p@ss!word" in config.redis_url
        assert "p@ss!word" in config.postgres_dsn
        assert config.default_queue == "queue:with:colons"

    def test_env_var_none_string_converts_to_none(self, monkeypatch) -> None:
        # Arrange - Some systems might set env vars to empty strings
        monkeypatch.setenv("ASYNCTASQ_REDIS_PASSWORD", "")

        # Act
        config = Config.from_env()

        # Assert
        # Empty string is still a string, not None (this is expected behavior)
        assert config.redis_password == ""


@mark.unit
class TestConfigDataclass:
    """Test Config as a dataclass."""

    def test_config_is_dataclass(self) -> None:
        # Assert
        import dataclasses

        assert dataclasses.is_dataclass(Config)

    def test_config_can_be_instantiated_directly(self) -> None:
        # Act
        config = Config(
            driver="redis",
            redis_url="redis://test:6379",
            default_queue="test",
        )

        # Assert
        assert config.driver == "redis"
        assert config.redis_url == "redis://test:6379"
        assert config.default_queue == "test"

    def test_config_fields_are_accessible(self) -> None:
        # Arrange
        config = Config()

        # Assert - all fields should be accessible
        assert hasattr(config, "driver")
        assert hasattr(config, "redis_url")
        assert hasattr(config, "sqs_region")
        assert hasattr(config, "postgres_dsn")
        assert hasattr(config, "default_queue")


@mark.unit
class TestConfigTypeConversion:
    """Test type conversion from environment variables."""

    def test_int_conversion_from_string(self, monkeypatch) -> None:
        # Arrange
        monkeypatch.setenv("ASYNCTASQ_REDIS_DB", "7")
        monkeypatch.setenv("ASYNCTASQ_MAX_RETRIES", "10")

        # Act
        config = Config.from_env()

        # Assert
        assert type(config.redis_db) is int
        assert type(config.default_max_retries) is int

    def test_str_conversion_preserves_string(self, monkeypatch) -> None:
        # Arrange
        monkeypatch.setenv("ASYNCTASQ_DRIVER", "redis")
        monkeypatch.setenv("ASYNCTASQ_DEFAULT_QUEUE", "default")

        # Act
        config = Config.from_env()

        # Assert
        assert type(config.driver) is str
        assert type(config.default_queue) is str


if __name__ == "__main__":
    main([__file__, "-s", "-m", "unit"])
