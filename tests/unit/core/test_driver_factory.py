"""Unit tests for DriverFactory.

Testing Strategy:
- pytest 9.0.1 with asyncio_mode="auto" (no decorators needed)
- AAA pattern (Arrange, Act, Assert)
- Test behavior over implementation details
- Mock driver instantiation to avoid real connections
- Fast, isolated tests
"""

from typing import get_args
from unittest.mock import MagicMock, patch

from pytest import main, mark, raises

from asynctasq.config import Config
from asynctasq.core.driver_factory import DriverFactory
from asynctasq.drivers import DriverType
from asynctasq.drivers.mysql_driver import MySQLDriver
from asynctasq.drivers.postgres_driver import PostgresDriver
from asynctasq.drivers.redis_driver import RedisDriver
from asynctasq.drivers.sqs_driver import SQSDriver


@mark.unit
class TestDriverFactoryCreateFromConfig:
    """Test DriverFactory.create_from_config() method."""

    @patch("asynctasq.drivers.redis_driver.RedisDriver")
    def test_create_from_config_with_redis_driver(self, mock_redis: MagicMock) -> None:
        # Arrange
        config = Config(
            driver="redis",
            redis_url="redis://test:6379",
            redis_password="secret123",
            redis_db=5,
            redis_max_connections=20,
        )
        mock_instance = MagicMock(spec=RedisDriver)
        mock_redis.return_value = mock_instance

        # Act
        result = DriverFactory.create_from_config(config)

        # Assert
        mock_redis.assert_called_once_with(
            url="redis://test:6379",
            password="secret123",
            db=5,
            max_connections=20,
            keep_completed_tasks=False,
        )
        assert result == mock_instance

    @patch("asynctasq.drivers.sqs_driver.SQSDriver")
    def test_create_from_config_with_sqs_driver(self, mock_sqs: MagicMock) -> None:
        # Arrange
        config = Config(
            driver="sqs",
            sqs_region="us-west-2",
            sqs_queue_url_prefix="https://sqs.us-west-2.amazonaws.com/123456789/",
            aws_access_key_id="test_key_id",
            aws_secret_access_key="test_secret_key",
        )
        mock_instance = MagicMock(spec=SQSDriver)
        mock_sqs.return_value = mock_instance

        # Act
        result = DriverFactory.create_from_config(config)

        # Assert
        mock_sqs.assert_called_once_with(
            region_name="us-west-2",
            queue_url_prefix="https://sqs.us-west-2.amazonaws.com/123456789/",
            aws_access_key_id="test_key_id",
            aws_secret_access_key="test_secret_key",
        )
        assert result == mock_instance

    @patch("asynctasq.drivers.postgres_driver.PostgresDriver")
    def test_create_from_config_with_postgres_driver(self, mock_postgres: MagicMock) -> None:
        # Arrange
        config = Config(
            driver="postgres",
            postgres_dsn="postgresql://user:pass@testdb:5432/taskdb",
            postgres_queue_table="custom_queue",
            postgres_dead_letter_table="custom_dlq",
            postgres_max_attempts=5,
            postgres_retry_delay_seconds=120,
            postgres_visibility_timeout_seconds=600,
            postgres_min_pool_size=5,
            postgres_max_pool_size=20,
        )
        mock_instance = MagicMock(spec=PostgresDriver)
        mock_postgres.return_value = mock_instance

        # Act
        result = DriverFactory.create_from_config(config)

        # Assert
        mock_postgres.assert_called_once_with(
            dsn="postgresql://user:pass@testdb:5432/taskdb",
            queue_table="custom_queue",
            dead_letter_table="custom_dlq",
            max_attempts=5,
            retry_delay_seconds=120,
            visibility_timeout_seconds=600,
            min_pool_size=5,
            max_pool_size=20,
            keep_completed_tasks=False,
        )
        assert result == mock_instance

    @patch("asynctasq.drivers.mysql_driver.MySQLDriver")
    def test_create_from_config_with_mysql_driver(self, mock_mysql: MagicMock) -> None:
        # Arrange
        config = Config(
            driver="mysql",
            mysql_dsn="mysql://user:pass@testdb:3306/taskdb",
            mysql_queue_table="custom_queue",
            mysql_dead_letter_table="custom_dlq",
            mysql_max_attempts=5,
            mysql_retry_delay_seconds=120,
            mysql_visibility_timeout_seconds=600,
            mysql_min_pool_size=5,
            mysql_max_pool_size=20,
        )
        mock_instance = MagicMock(spec=MySQLDriver)
        mock_mysql.return_value = mock_instance

        # Act
        result = DriverFactory.create_from_config(config)

        # Assert
        mock_mysql.assert_called_once_with(
            dsn="mysql://user:pass@testdb:3306/taskdb",
            queue_table="custom_queue",
            dead_letter_table="custom_dlq",
            max_attempts=5,
            retry_delay_seconds=120,
            visibility_timeout_seconds=600,
            min_pool_size=5,
            max_pool_size=20,
            keep_completed_tasks=False,
        )
        assert result == mock_instance

    @patch("asynctasq.drivers.postgres_driver.PostgresDriver")
    @patch("asynctasq.drivers.redis_driver.RedisDriver")
    def test_create_from_config_with_driver_type_override(
        self, mock_redis: MagicMock, mock_postgres: MagicMock
    ) -> None:
        # Arrange
        config = Config(driver="redis")  # Config says redis
        mock_instance = MagicMock(spec=PostgresDriver)
        mock_postgres.return_value = mock_instance

        # Act - override with postgres driver
        result = DriverFactory.create_from_config(config, driver_type="postgres")

        # Assert
        mock_postgres.assert_called_once()
        mock_redis.assert_not_called()  # Redis should not be called
        assert result == mock_instance

    @patch("asynctasq.drivers.postgres_driver.PostgresDriver")
    @patch("asynctasq.drivers.sqs_driver.SQSDriver")
    def test_create_from_config_override_sqs_with_postgres(
        self, mock_sqs: MagicMock, mock_postgres: MagicMock
    ) -> None:
        # Arrange
        config = Config(
            driver="sqs",
            postgres_dsn="postgresql://override:pass@localhost/db",
        )
        mock_instance = MagicMock(spec=PostgresDriver)
        mock_postgres.return_value = mock_instance

        # Act
        result = DriverFactory.create_from_config(config, driver_type="postgres")

        # Assert
        mock_postgres.assert_called_once()
        mock_sqs.assert_not_called()
        assert result == mock_instance

    @patch("asynctasq.drivers.mysql_driver.MySQLDriver")
    @patch("asynctasq.drivers.postgres_driver.PostgresDriver")
    def test_create_from_config_override_postgres_with_mysql(
        self, mock_postgres: MagicMock, mock_mysql: MagicMock
    ) -> None:
        # Arrange
        config = Config(
            driver="postgres",
            mysql_dsn="mysql://override:pass@localhost:3306/db",
        )
        mock_instance = MagicMock(spec=MySQLDriver)
        mock_mysql.return_value = mock_instance

        # Act
        result = DriverFactory.create_from_config(config, driver_type="mysql")

        # Assert
        mock_mysql.assert_called_once()
        mock_postgres.assert_not_called()
        assert result == mock_instance

    @patch("asynctasq.drivers.mysql_driver.MySQLDriver")
    @patch("asynctasq.drivers.redis_driver.RedisDriver")
    def test_create_from_config_override_mysql_with_redis(
        self, mock_redis: MagicMock, mock_mysql: MagicMock
    ) -> None:
        # Arrange
        config = Config(
            driver="mysql",
            redis_url="redis://override:6379",
        )
        mock_instance = MagicMock(spec=RedisDriver)
        mock_redis.return_value = mock_instance

        # Act
        result = DriverFactory.create_from_config(config, driver_type="redis")

        # Assert
        mock_redis.assert_called_once()
        mock_mysql.assert_not_called()
        assert result == mock_instance


@mark.unit
class TestDriverFactoryCreate:
    """Test DriverFactory.create() method with different driver types."""

    @patch("asynctasq.drivers.redis_driver.RedisDriver")
    def test_create_redis_driver_with_defaults(self, mock_redis: MagicMock) -> None:
        # Arrange
        mock_instance = MagicMock(spec=RedisDriver)
        mock_redis.return_value = mock_instance

        # Act
        result = DriverFactory.create("redis")

        # Assert
        mock_redis.assert_called_once_with(
            url="redis://localhost:6379",
            password=None,
            db=0,
            max_connections=10,
            keep_completed_tasks=False,
        )
        assert result == mock_instance

    @patch("asynctasq.drivers.redis_driver.RedisDriver")
    def test_create_redis_driver_with_custom_params(self, mock_redis: MagicMock) -> None:
        # Arrange
        mock_instance = MagicMock(spec=RedisDriver)
        mock_redis.return_value = mock_instance

        # Act
        result = DriverFactory.create(
            "redis",
            redis_url="redis://custom.host:6380",
            redis_password="custom_pass",
            redis_db=3,
            redis_max_connections=50,
        )

        # Assert
        mock_redis.assert_called_once_with(
            url="redis://custom.host:6380",
            password="custom_pass",
            db=3,
            max_connections=50,
            keep_completed_tasks=False,
        )
        assert result == mock_instance

    @patch("asynctasq.drivers.sqs_driver.SQSDriver")
    def test_create_sqs_driver_with_defaults(self, mock_sqs: MagicMock) -> None:
        # Arrange
        mock_instance = MagicMock(spec=SQSDriver)
        mock_sqs.return_value = mock_instance

        # Act
        result = DriverFactory.create("sqs")

        # Assert
        mock_sqs.assert_called_once_with(
            region_name="us-east-1",
            queue_url_prefix=None,
            aws_access_key_id=None,
            aws_secret_access_key=None,
        )
        assert result == mock_instance

    @patch("asynctasq.drivers.sqs_driver.SQSDriver")
    def test_create_sqs_driver_with_custom_params(self, mock_sqs: MagicMock) -> None:
        # Arrange
        mock_instance = MagicMock(spec=SQSDriver)
        mock_sqs.return_value = mock_instance

        # Act
        result = DriverFactory.create(
            "sqs",
            sqs_region="eu-west-1",
            sqs_queue_url_prefix="https://sqs.eu-west-1.amazonaws.com/987654321/",
            aws_access_key_id="custom_key",
            aws_secret_access_key="custom_secret",
        )

        # Assert
        mock_sqs.assert_called_once_with(
            region_name="eu-west-1",
            queue_url_prefix="https://sqs.eu-west-1.amazonaws.com/987654321/",
            aws_access_key_id="custom_key",
            aws_secret_access_key="custom_secret",
        )
        assert result == mock_instance

    @patch("asynctasq.drivers.postgres_driver.PostgresDriver")
    def test_create_postgres_driver_with_defaults(self, mock_postgres: MagicMock) -> None:
        # Arrange
        mock_instance = MagicMock(spec=PostgresDriver)
        mock_postgres.return_value = mock_instance

        # Act
        result = DriverFactory.create("postgres")

        # Assert
        mock_postgres.assert_called_once_with(
            dsn="postgresql://user:pass@localhost/dbname",
            queue_table="task_queue",
            dead_letter_table="dead_letter_queue",
            max_attempts=3,
            retry_delay_seconds=60,
            visibility_timeout_seconds=300,
            min_pool_size=10,
            max_pool_size=10,
            keep_completed_tasks=False,
        )
        assert result == mock_instance

    @patch("asynctasq.drivers.postgres_driver.PostgresDriver")
    def test_create_postgres_driver_with_custom_params(self, mock_postgres: MagicMock) -> None:
        # Arrange
        mock_instance = MagicMock(spec=PostgresDriver)
        mock_postgres.return_value = mock_instance

        # Act
        result = DriverFactory.create(
            "postgres",
            postgres_dsn="postgresql://admin:secret@db.example.com:5432/prod",
            postgres_queue_table="production_queue",
            postgres_dead_letter_table="production_dlq",
            postgres_max_attempts=10,
            postgres_retry_delay_seconds=300,
            postgres_visibility_timeout_seconds=1800,
            postgres_min_pool_size=20,
            postgres_max_pool_size=100,
        )

        # Assert
        mock_postgres.assert_called_once_with(
            dsn="postgresql://admin:secret@db.example.com:5432/prod",
            queue_table="production_queue",
            dead_letter_table="production_dlq",
            max_attempts=10,
            retry_delay_seconds=300,
            visibility_timeout_seconds=1800,
            min_pool_size=20,
            max_pool_size=100,
            keep_completed_tasks=False,
        )
        assert result == mock_instance

    @patch("asynctasq.drivers.mysql_driver.MySQLDriver")
    def test_create_mysql_driver_with_defaults(self, mock_mysql: MagicMock) -> None:
        # Arrange
        mock_instance = MagicMock(spec=MySQLDriver)
        mock_mysql.return_value = mock_instance

        # Act
        result = DriverFactory.create("mysql")

        # Assert
        mock_mysql.assert_called_once_with(
            dsn="mysql://user:pass@localhost:3306/dbname",
            queue_table="task_queue",
            dead_letter_table="dead_letter_queue",
            max_attempts=3,
            retry_delay_seconds=60,
            visibility_timeout_seconds=300,
            min_pool_size=10,
            max_pool_size=10,
            keep_completed_tasks=False,
        )
        assert result == mock_instance

    @patch("asynctasq.drivers.mysql_driver.MySQLDriver")
    def test_create_mysql_driver_with_custom_params(self, mock_mysql: MagicMock) -> None:
        # Arrange
        mock_instance = MagicMock(spec=MySQLDriver)
        mock_mysql.return_value = mock_instance

        # Act
        result = DriverFactory.create(
            "mysql",
            mysql_dsn="mysql://admin:secret@db.example.com:3306/prod",
            mysql_queue_table="production_queue",
            mysql_dead_letter_table="production_dlq",
            mysql_max_attempts=10,
            mysql_retry_delay_seconds=300,
            mysql_visibility_timeout_seconds=1800,
            mysql_min_pool_size=20,
            mysql_max_pool_size=100,
        )

        # Assert
        mock_mysql.assert_called_once_with(
            dsn="mysql://admin:secret@db.example.com:3306/prod",
            queue_table="production_queue",
            dead_letter_table="production_dlq",
            max_attempts=10,
            retry_delay_seconds=300,
            visibility_timeout_seconds=1800,
            min_pool_size=20,
            max_pool_size=100,
            keep_completed_tasks=False,
        )
        assert result == mock_instance


@mark.unit
class TestDriverFactoryErrorHandling:
    """Test error handling for unknown driver types."""

    def test_create_with_unknown_driver_type_raises_error(self) -> None:
        # Act & Assert
        with raises(ValueError, match="Unknown driver type: unknown"):
            DriverFactory.create("unknown")  # type: ignore

    def test_create_from_config_with_unknown_driver_type_raises_error(self) -> None:
        # Arrange
        config = Config()
        config.driver = "unknown"  # type: ignore

        # Act & Assert
        with raises(ValueError, match="Unknown driver type: unknown"):
            DriverFactory.create_from_config(config)

    def test_error_message_includes_supported_types(self) -> None:
        # Act & Assert
        with raises(ValueError, match=f"Supported types: {', '.join(list(get_args(DriverType)))}"):
            DriverFactory.create("invalid")  # type: ignore


@mark.unit
class TestDriverFactoryParameterPassing:
    """Test that parameters are correctly passed through."""

    @patch("asynctasq.drivers.redis_driver.RedisDriver")
    def test_create_redis_with_partial_params(self, mock_redis: MagicMock) -> None:
        # Arrange
        mock_instance = MagicMock(spec=RedisDriver)
        mock_redis.return_value = mock_instance

        # Act - only provide some parameters
        result = DriverFactory.create(
            "redis",
            redis_url="redis://partial:6379",
            redis_db=7,
        )

        # Assert - defaults should be used for unspecified params
        mock_redis.assert_called_once_with(
            url="redis://partial:6379",
            password=None,  # Default
            db=7,
            max_connections=10,  # Default
            keep_completed_tasks=False,
        )
        assert result == mock_instance

    @patch("asynctasq.drivers.sqs_driver.SQSDriver")
    def test_create_sqs_with_only_credentials(self, mock_sqs: MagicMock) -> None:
        # Arrange
        mock_instance = MagicMock(spec=SQSDriver)
        mock_sqs.return_value = mock_instance

        # Act
        result = DriverFactory.create(
            "sqs",
            aws_access_key_id="only_key",
            aws_secret_access_key="only_secret",
        )

        # Assert
        mock_sqs.assert_called_once_with(
            region_name="us-east-1",  # Default
            queue_url_prefix=None,  # Default
            aws_access_key_id="only_key",
            aws_secret_access_key="only_secret",
        )
        assert result == mock_instance

    @patch("asynctasq.drivers.postgres_driver.PostgresDriver")
    def test_create_postgres_with_minimal_params(self, mock_postgres: MagicMock) -> None:
        # Arrange
        mock_instance = MagicMock(spec=PostgresDriver)
        mock_postgres.return_value = mock_instance

        # Act
        result = DriverFactory.create(
            "postgres",
            postgres_dsn="postgresql://minimal:pass@localhost/db",
        )

        # Assert
        mock_postgres.assert_called_once_with(
            dsn="postgresql://minimal:pass@localhost/db",
            queue_table="task_queue",  # Default
            dead_letter_table="dead_letter_queue",  # Default
            max_attempts=3,  # Default
            retry_delay_seconds=60,  # Default
            visibility_timeout_seconds=300,  # Default
            min_pool_size=10,  # Default
            max_pool_size=10,  # Default
            keep_completed_tasks=False,
        )
        assert result == mock_instance

    @patch("asynctasq.drivers.mysql_driver.MySQLDriver")
    def test_create_mysql_with_minimal_params(self, mock_mysql: MagicMock) -> None:
        # Arrange
        mock_instance = MagicMock(spec=MySQLDriver)
        mock_mysql.return_value = mock_instance

        # Act
        result = DriverFactory.create(
            "mysql",
            mysql_dsn="mysql://minimal:pass@localhost:3306/db",
        )

        # Assert
        mock_mysql.assert_called_once_with(
            dsn="mysql://minimal:pass@localhost:3306/db",
            queue_table="task_queue",  # Default
            dead_letter_table="dead_letter_queue",  # Default
            max_attempts=3,  # Default
            retry_delay_seconds=60,  # Default
            visibility_timeout_seconds=300,  # Default
            min_pool_size=10,  # Default
            max_pool_size=10,  # Default
            keep_completed_tasks=False,
        )
        assert result == mock_instance


@mark.unit
class TestDriverFactoryConfigIntegration:
    """Test integration between Config and DriverFactory."""

    @patch("asynctasq.drivers.redis_driver.RedisDriver")
    def test_config_defaults_are_used(self, mock_redis: MagicMock) -> None:
        # Arrange
        config = Config()  # Use all defaults
        mock_instance = MagicMock(spec=RedisDriver)
        mock_redis.return_value = mock_instance

        # Act
        result = DriverFactory.create_from_config(config)

        # Assert - default Redis configuration
        mock_redis.assert_called_once()
        assert result == mock_instance

    @patch("asynctasq.drivers.postgres_driver.PostgresDriver")
    def test_all_postgres_config_fields_passed_correctly(self, mock_postgres: MagicMock) -> None:
        # Arrange - create config with all postgres fields customized
        config = Config(
            driver="postgres",
            postgres_dsn="postgresql://test:test@testhost:5432/testdb",
            postgres_queue_table="test_queue",
            postgres_dead_letter_table="test_dlq",
            postgres_max_attempts=7,
            postgres_retry_delay_seconds=180,
            postgres_visibility_timeout_seconds=900,
            postgres_min_pool_size=15,
            postgres_max_pool_size=50,
        )
        mock_instance = MagicMock(spec=PostgresDriver)
        mock_postgres.return_value = mock_instance

        # Act
        result = DriverFactory.create_from_config(config)

        # Assert - all fields should be passed through
        mock_postgres.assert_called_once_with(
            dsn="postgresql://test:test@testhost:5432/testdb",
            queue_table="test_queue",
            dead_letter_table="test_dlq",
            max_attempts=7,
            retry_delay_seconds=180,
            visibility_timeout_seconds=900,
            min_pool_size=15,
            max_pool_size=50,
            keep_completed_tasks=False,
        )
        assert result == mock_instance

    @patch("asynctasq.drivers.sqs_driver.SQSDriver")
    def test_all_sqs_config_fields_passed_correctly(self, mock_sqs: MagicMock) -> None:
        # Arrange - create config with all SQS fields customized
        config = Config(
            driver="sqs",
            sqs_region="ap-south-1",
            sqs_queue_url_prefix="https://sqs.ap-south-1.amazonaws.com/111222333/",
            aws_access_key_id="test_access_key",
            aws_secret_access_key="test_secret_access_key",
        )
        mock_instance = MagicMock(spec=SQSDriver)
        mock_sqs.return_value = mock_instance

        # Act
        result = DriverFactory.create_from_config(config)

        # Assert - all fields should be passed through
        mock_sqs.assert_called_once_with(
            region_name="ap-south-1",
            queue_url_prefix="https://sqs.ap-south-1.amazonaws.com/111222333/",
            aws_access_key_id="test_access_key",
            aws_secret_access_key="test_secret_access_key",
        )
        assert result == mock_instance

    @patch("asynctasq.drivers.redis_driver.RedisDriver")
    def test_all_redis_config_fields_passed_correctly(self, mock_redis: MagicMock) -> None:
        # Arrange - create config with all Redis fields customized
        config = Config(
            driver="redis",
            redis_url="redis://prod.redis.example.com:6380",
            redis_password="super_secret_password",
            redis_db=15,
            redis_max_connections=100,
        )
        mock_instance = MagicMock(spec=RedisDriver)
        mock_redis.return_value = mock_instance

        # Act
        result = DriverFactory.create_from_config(config)

        # Assert - all fields should be passed through
        mock_redis.assert_called_once_with(
            url="redis://prod.redis.example.com:6380",
            password="super_secret_password",
            db=15,
            max_connections=100,
            keep_completed_tasks=False,
        )
        assert result == mock_instance

    @patch("asynctasq.drivers.mysql_driver.MySQLDriver")
    def test_all_mysql_config_fields_passed_correctly(self, mock_mysql: MagicMock) -> None:
        # Arrange - create config with all mysql fields customized
        config = Config(
            driver="mysql",
            mysql_dsn="mysql://test:test@testhost:3306/testdb",
            mysql_queue_table="test_queue",
            mysql_dead_letter_table="test_dlq",
            mysql_max_attempts=7,
            mysql_retry_delay_seconds=180,
            mysql_visibility_timeout_seconds=900,
            mysql_min_pool_size=15,
            mysql_max_pool_size=50,
        )
        mock_instance = MagicMock(spec=MySQLDriver)
        mock_mysql.return_value = mock_instance

        # Act
        result = DriverFactory.create_from_config(config)

        # Assert - all fields should be passed through
        mock_mysql.assert_called_once_with(
            dsn="mysql://test:test@testhost:3306/testdb",
            queue_table="test_queue",
            dead_letter_table="test_dlq",
            max_attempts=7,
            retry_delay_seconds=180,
            visibility_timeout_seconds=900,
            min_pool_size=15,
            max_pool_size=50,
            keep_completed_tasks=False,
        )
        assert result == mock_instance


@mark.unit
class TestDriverFactoryEdgeCases:
    """Test edge cases and boundary conditions."""

    @patch("asynctasq.drivers.redis_driver.RedisDriver")
    def test_none_values_passed_correctly(self, mock_redis: MagicMock) -> None:
        # Arrange
        mock_instance = MagicMock(spec=RedisDriver)
        mock_redis.return_value = mock_instance

        # Act - explicitly pass None for optional parameters
        result = DriverFactory.create(
            "redis",
            redis_password=None,
        )

        # Assert
        mock_redis.assert_called_once_with(
            url="redis://localhost:6379",
            password=None,
            db=0,
            max_connections=10,
            keep_completed_tasks=False,
        )
        assert result == mock_instance

    @patch("asynctasq.drivers.sqs_driver.SQSDriver")
    def test_empty_string_values_passed_correctly(self, mock_sqs: MagicMock) -> None:
        # Arrange
        mock_instance = MagicMock(spec=SQSDriver)
        mock_sqs.return_value = mock_instance

        # Act
        result = DriverFactory.create(
            "sqs",
            sqs_queue_url_prefix="",  # Empty string (different from None)
        )

        # Assert
        mock_sqs.assert_called_once_with(
            region_name="us-east-1",
            queue_url_prefix="",  # Should be passed as-is
            aws_access_key_id=None,
            aws_secret_access_key=None,
        )
        assert result == mock_instance

    @patch("asynctasq.drivers.postgres_driver.PostgresDriver")
    def test_boundary_pool_sizes(self, mock_postgres: MagicMock) -> None:
        # Arrange
        mock_instance = MagicMock(spec=PostgresDriver)
        mock_postgres.return_value = mock_instance

        # Act - test with same min and max pool size
        result = DriverFactory.create(
            "postgres",
            postgres_min_pool_size=1,
            postgres_max_pool_size=1000,
        )

        # Assert
        mock_postgres.assert_called_once()
        call_kwargs = mock_postgres.call_args[1]
        assert call_kwargs["min_pool_size"] == 1
        assert call_kwargs["max_pool_size"] == 1000
        assert result == mock_instance

    @patch("asynctasq.drivers.mysql_driver.MySQLDriver")
    def test_boundary_pool_sizes_mysql(self, mock_mysql: MagicMock) -> None:
        # Arrange
        mock_instance = MagicMock(spec=MySQLDriver)
        mock_mysql.return_value = mock_instance

        # Act - test with same min and max pool size
        result = DriverFactory.create(
            "mysql",
            mysql_min_pool_size=1,
            mysql_max_pool_size=1000,
        )

        # Assert
        mock_mysql.assert_called_once()
        call_kwargs = mock_mysql.call_args[1]
        assert call_kwargs["min_pool_size"] == 1
        assert call_kwargs["max_pool_size"] == 1000
        assert result == mock_instance

    @patch("asynctasq.drivers.redis_driver.RedisDriver")
    def test_kwargs_get_method_with_fallback(self, mock_redis: MagicMock) -> None:
        # Arrange
        mock_instance = MagicMock(spec=RedisDriver)
        mock_redis.return_value = mock_instance

        # Act - pass unrelated kwargs that shouldn't affect Redis
        result = DriverFactory.create(
            "redis",
            postgres_dsn="should_be_ignored",
            sqs_region="should_be_ignored",
            unrelated_param="should_be_ignored",
        )

        # Assert - only Redis params should be used
        mock_redis.assert_called_once_with(
            url="redis://localhost:6379",
            password=None,
            db=0,
            max_connections=10,
            keep_completed_tasks=False,
        )
        assert result == mock_instance

    @patch("asynctasq.drivers.mysql_driver.MySQLDriver")
    def test_mysql_ignores_unrelated_kwargs(self, mock_mysql: MagicMock) -> None:
        # Arrange
        mock_instance = MagicMock(spec=MySQLDriver)
        mock_mysql.return_value = mock_instance

        # Act - pass unrelated kwargs that shouldn't affect MySQL
        result = DriverFactory.create(
            "mysql",
            redis_url="should_be_ignored",
            sqs_region="should_be_ignored",
            postgres_dsn="should_be_ignored",
            unrelated_param="should_be_ignored",
        )

        # Assert - only MySQL params should be used
        mock_mysql.assert_called_once_with(
            dsn="mysql://user:pass@localhost:3306/dbname",
            queue_table="task_queue",
            dead_letter_table="dead_letter_queue",
            max_attempts=3,
            retry_delay_seconds=60,
            visibility_timeout_seconds=300,
            min_pool_size=10,
            max_pool_size=10,
            keep_completed_tasks=False,
        )
        assert result == mock_instance


if __name__ == "__main__":
    main([__file__, "-s", "-m", "unit"])
