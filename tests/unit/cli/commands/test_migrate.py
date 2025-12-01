"""Unit tests for migrate command.

Testing Strategy:
- pytest 9.0.1 with asyncio_mode="auto" (no decorators needed)
- AAA pattern (Arrange, Act, Assert)
- Mock PostgresDriver, MySQLDriver and DriverFactory to avoid real database connections
- Fast, isolated tests
"""

import argparse
from unittest.mock import AsyncMock, MagicMock, patch

from pytest import main, mark, raises

from async_task_q.cli.commands.migrate import MigrationError, run_migrate
from async_task_q.config import Config


@mark.unit
class TestMigrationError:
    """Test MigrationError exception."""

    def test_migration_error_is_exception(self) -> None:
        # Assert
        assert issubclass(MigrationError, Exception)

    def test_migration_error_can_be_raised(self) -> None:
        # Act & Assert
        with raises(MigrationError, match="test error"):
            raise MigrationError("test error")

    def test_migration_error_message(self) -> None:
        # Arrange
        error = MigrationError("Custom error message")

        # Assert
        assert str(error) == "Custom error message"


@mark.unit
class TestRunMigrate:
    """Test run_migrate() function."""

    @mark.asyncio
    async def test_run_migrate_with_non_postgres_driver_raises_error(self) -> None:
        # Arrange
        args = argparse.Namespace()
        config = Config(driver="redis")

        # Act & Assert
        with raises(
            MigrationError, match="Migration is only supported for PostgreSQL and MySQL drivers"
        ):
            await run_migrate(args, config)

    @mark.asyncio
    async def test_run_migrate_with_redis_driver_raises_error(self) -> None:
        # Arrange
        args = argparse.Namespace()
        config = Config(driver="redis")

        # Act & Assert
        with raises(
            MigrationError, match="Migration is only supported for PostgreSQL and MySQL drivers"
        ):
            await run_migrate(args, config)

    @mark.asyncio
    async def test_run_migrate_with_sqs_driver_raises_error(self) -> None:
        # Arrange
        args = argparse.Namespace()
        config = Config(driver="sqs")

        # Act & Assert
        with raises(
            MigrationError, match="Migration is only supported for PostgreSQL and MySQL drivers"
        ):
            await run_migrate(args, config)

    @patch("async_task_q.cli.commands.migrate.isinstance")
    @patch("async_task_q.drivers.postgres_driver.PostgresDriver")
    @patch("async_task_q.cli.commands.migrate.DriverFactory")
    @patch("async_task_q.cli.commands.migrate.logger")
    @mark.asyncio
    async def test_run_migrate_with_postgres_driver_success(
        self, mock_logger, mock_driver_factory, mock_postgres_driver_class, mock_isinstance
    ) -> None:
        # Arrange
        args = argparse.Namespace()
        config = Config(
            driver="postgres",
            postgres_dsn="postgresql://user:pass@localhost/db",
            postgres_queue_table="task_queue",
            postgres_dead_letter_table="dead_letter_queue",
        )
        mock_driver = AsyncMock()
        mock_driver_factory.create_from_config.return_value = mock_driver
        # Make isinstance return True for PostgresDriver check
        mock_isinstance.return_value = True

        # Act
        await run_migrate(args, config)

        # Assert
        mock_driver_factory.create_from_config.assert_called_once_with(
            config, driver_type="postgres"
        )
        mock_driver.connect.assert_awaited_once()
        mock_driver.init_schema.assert_awaited_once()
        mock_driver.disconnect.assert_awaited_once()
        assert mock_logger.info.call_count >= 4  # Initial info + success messages

    @patch("async_task_q.cli.commands.migrate.isinstance")
    @patch("async_task_q.drivers.postgres_driver.PostgresDriver")
    @patch("async_task_q.cli.commands.migrate.DriverFactory")
    @mark.asyncio
    async def test_run_migrate_with_wrong_driver_type_raises_error(
        self, mock_driver_factory, mock_postgres_driver_class, mock_isinstance
    ) -> None:
        # Arrange
        args = argparse.Namespace()
        config = Config(driver="postgres")
        mock_driver = MagicMock()  # Not a PostgresDriver instance
        mock_driver_factory.create_from_config.return_value = mock_driver
        # Make isinstance return False to simulate wrong driver type
        mock_isinstance.return_value = False

        # Act & Assert
        with raises(
            MigrationError, match="Driver factory did not return a PostgresDriver instance"
        ):
            await run_migrate(args, config)

    @patch("async_task_q.cli.commands.migrate.isinstance")
    @patch("async_task_q.drivers.postgres_driver.PostgresDriver")
    @patch("async_task_q.cli.commands.migrate.DriverFactory")
    @patch("async_task_q.cli.commands.migrate.logger")
    @mark.asyncio
    async def test_run_migrate_logs_configuration(
        self, mock_logger, mock_driver_factory, mock_postgres_driver_class, mock_isinstance
    ) -> None:
        # Arrange
        args = argparse.Namespace()
        config = Config(
            driver="postgres",
            postgres_dsn="postgresql://test:pass@db:5432/testdb",
            postgres_queue_table="custom_queue",
            postgres_dead_letter_table="custom_dlq",
        )
        mock_driver = AsyncMock()
        mock_driver_factory.create_from_config.return_value = mock_driver
        # Make isinstance return True for PostgresDriver check
        mock_isinstance.return_value = True

        # Act
        await run_migrate(args, config)

        # Assert
        assert any(
            "Initializing PostgreSQL schema" in str(call)
            for call in mock_logger.info.call_args_list
        )
        assert any(
            "postgresql://test:pass@db:5432/testdb" in str(call)
            for call in mock_logger.info.call_args_list
        )
        assert any("custom_queue" in str(call) for call in mock_logger.info.call_args_list)
        assert any("custom_dlq" in str(call) for call in mock_logger.info.call_args_list)

    @patch("async_task_q.cli.commands.migrate.isinstance")
    @patch("async_task_q.drivers.postgres_driver.PostgresDriver")
    @patch("async_task_q.cli.commands.migrate.DriverFactory")
    @patch("async_task_q.cli.commands.migrate.logger")
    @mark.asyncio
    async def test_run_migrate_logs_success_messages(
        self, mock_logger, mock_driver_factory, mock_postgres_driver_class, mock_isinstance
    ) -> None:
        # Arrange
        args = argparse.Namespace()
        config = Config(
            driver="postgres",
            postgres_dsn="postgresql://user:pass@localhost/db",
            postgres_queue_table="task_queue",
            postgres_dead_letter_table="dead_letter_queue",
        )
        mock_driver = AsyncMock()
        mock_driver_factory.create_from_config.return_value = mock_driver
        # Make isinstance return True for PostgresDriver check
        mock_isinstance.return_value = True

        # Act
        await run_migrate(args, config)

        # Assert
        assert any(
            "Schema initialized successfully" in str(call)
            for call in mock_logger.info.call_args_list
        )
        assert any("task_queue" in str(call) for call in mock_logger.info.call_args_list)
        assert any("idx_task_queue_lookup" in str(call) for call in mock_logger.info.call_args_list)
        assert any("dead_letter_queue" in str(call) for call in mock_logger.info.call_args_list)

    @patch("async_task_q.cli.commands.migrate.isinstance")
    @patch("async_task_q.drivers.postgres_driver.PostgresDriver")
    @patch("async_task_q.cli.commands.migrate.DriverFactory")
    @mark.asyncio
    async def test_run_migrate_disconnects_on_error(
        self, mock_driver_factory, mock_postgres_driver_class, mock_isinstance
    ) -> None:
        # Arrange
        args = argparse.Namespace()
        config = Config(driver="postgres")
        mock_driver = AsyncMock()
        mock_driver.connect.return_value = None
        mock_driver.init_schema.side_effect = Exception("Schema error")
        mock_driver_factory.create_from_config.return_value = mock_driver
        # Make isinstance return True for PostgresDriver check
        mock_isinstance.return_value = True

        # Act & Assert
        with raises(Exception, match="Schema error"):
            await run_migrate(args, config)

        # Assert - disconnect should be called even on error
        mock_driver.disconnect.assert_awaited_once()

    @patch("async_task_q.cli.commands.migrate.isinstance")
    @patch("async_task_q.drivers.postgres_driver.PostgresDriver")
    @patch("async_task_q.cli.commands.migrate.DriverFactory")
    @mark.asyncio
    async def test_run_migrate_disconnects_on_connect_error(
        self, mock_driver_factory, mock_postgres_driver_class, mock_isinstance
    ) -> None:
        # Arrange
        args = argparse.Namespace()
        config = Config(driver="postgres")
        mock_driver = AsyncMock()
        mock_driver.connect.side_effect = Exception("Connection error")
        mock_driver_factory.create_from_config.return_value = mock_driver
        # Make isinstance return True for PostgresDriver check
        mock_isinstance.return_value = True

        # Act & Assert
        with raises(Exception, match="Connection error"):
            await run_migrate(args, config)

        # Assert - disconnect should still be called
        mock_driver.disconnect.assert_awaited_once()

    @patch("async_task_q.cli.commands.migrate.isinstance")
    @patch("async_task_q.drivers.postgres_driver.PostgresDriver")
    @patch("async_task_q.cli.commands.migrate.DriverFactory")
    @patch("async_task_q.cli.commands.migrate.logger")
    @mark.asyncio
    async def test_run_migrate_with_custom_table_names(
        self, mock_logger, mock_driver_factory, mock_postgres_driver_class, mock_isinstance
    ) -> None:
        # Arrange
        args = argparse.Namespace()
        config = Config(
            driver="postgres",
            postgres_dsn="postgresql://user:pass@localhost/db",
            postgres_queue_table="my_queue",
            postgres_dead_letter_table="my_dlq",
        )
        mock_driver = AsyncMock()
        mock_driver_factory.create_from_config.return_value = mock_driver
        # Make isinstance return True for PostgresDriver check
        mock_isinstance.return_value = True

        # Act
        await run_migrate(args, config)

        # Assert
        assert any("my_queue" in str(call) for call in mock_logger.info.call_args_list)
        assert any("my_dlq" in str(call) for call in mock_logger.info.call_args_list)
        assert any("idx_my_queue_lookup" in str(call) for call in mock_logger.info.call_args_list)

    @patch("async_task_q.cli.commands.migrate.isinstance")
    @patch("async_task_q.drivers.mysql_driver.MySQLDriver")
    @patch("async_task_q.cli.commands.migrate.DriverFactory")
    @patch("async_task_q.cli.commands.migrate.logger")
    @mark.asyncio
    async def test_run_migrate_with_mysql_driver_success(
        self, mock_logger, mock_driver_factory, mock_mysql_driver_class, mock_isinstance
    ) -> None:
        # Arrange
        args = argparse.Namespace()
        config = Config(
            driver="mysql",
            mysql_dsn="mysql://user:pass@localhost/db",
            mysql_queue_table="task_queue",
            mysql_dead_letter_table="dead_letter_queue",
        )
        mock_driver = AsyncMock()
        mock_driver_factory.create_from_config.return_value = mock_driver
        # Make isinstance return True for MySQLDriver check
        mock_isinstance.return_value = True

        # Act
        await run_migrate(args, config)

        # Assert
        mock_driver_factory.create_from_config.assert_called_once_with(config, driver_type="mysql")
        mock_driver.connect.assert_awaited_once()
        mock_driver.init_schema.assert_awaited_once()
        mock_driver.disconnect.assert_awaited_once()
        assert mock_logger.info.call_count >= 4  # Initial info + success messages

    @patch("async_task_q.cli.commands.migrate.isinstance")
    @patch("async_task_q.drivers.mysql_driver.MySQLDriver")
    @patch("async_task_q.cli.commands.migrate.DriverFactory")
    @mark.asyncio
    async def test_run_migrate_with_wrong_mysql_driver_type_raises_error(
        self, mock_driver_factory, mock_mysql_driver_class, mock_isinstance
    ) -> None:
        # Arrange
        args = argparse.Namespace()
        config = Config(driver="mysql")
        mock_driver = MagicMock()  # Not a MySQLDriver instance
        mock_driver_factory.create_from_config.return_value = mock_driver
        # Make isinstance return False to simulate wrong driver type
        mock_isinstance.return_value = False

        # Act & Assert
        with raises(MigrationError, match="Driver factory did not return a MySQLDriver instance"):
            await run_migrate(args, config)

    @patch("async_task_q.cli.commands.migrate.isinstance")
    @patch("async_task_q.drivers.mysql_driver.MySQLDriver")
    @patch("async_task_q.cli.commands.migrate.DriverFactory")
    @patch("async_task_q.cli.commands.migrate.logger")
    @mark.asyncio
    async def test_run_migrate_logs_mysql_configuration(
        self, mock_logger, mock_driver_factory, mock_mysql_driver_class, mock_isinstance
    ) -> None:
        # Arrange
        args = argparse.Namespace()
        config = Config(
            driver="mysql",
            mysql_dsn="mysql://test:pass@db:3306/testdb",
            mysql_queue_table="custom_queue",
            mysql_dead_letter_table="custom_dlq",
        )
        mock_driver = AsyncMock()
        mock_driver_factory.create_from_config.return_value = mock_driver
        # Make isinstance return True for MySQLDriver check
        mock_isinstance.return_value = True

        # Act
        await run_migrate(args, config)

        # Assert
        assert any(
            "Initializing MySQL schema" in str(call) for call in mock_logger.info.call_args_list
        )
        assert any(
            "mysql://test:pass@db:3306/testdb" in str(call)
            for call in mock_logger.info.call_args_list
        )
        assert any("custom_queue" in str(call) for call in mock_logger.info.call_args_list)
        assert any("custom_dlq" in str(call) for call in mock_logger.info.call_args_list)

    @patch("async_task_q.cli.commands.migrate.isinstance")
    @patch("async_task_q.drivers.mysql_driver.MySQLDriver")
    @patch("async_task_q.cli.commands.migrate.DriverFactory")
    @patch("async_task_q.cli.commands.migrate.logger")
    @mark.asyncio
    async def test_run_migrate_logs_mysql_success_messages(
        self, mock_logger, mock_driver_factory, mock_mysql_driver_class, mock_isinstance
    ) -> None:
        # Arrange
        args = argparse.Namespace()
        config = Config(
            driver="mysql",
            mysql_dsn="mysql://user:pass@localhost/db",
            mysql_queue_table="task_queue",
            mysql_dead_letter_table="dead_letter_queue",
        )
        mock_driver = AsyncMock()
        mock_driver_factory.create_from_config.return_value = mock_driver
        # Make isinstance return True for MySQLDriver check
        mock_isinstance.return_value = True

        # Act
        await run_migrate(args, config)

        # Assert
        assert any(
            "Schema initialized successfully" in str(call)
            for call in mock_logger.info.call_args_list
        )
        assert any("task_queue" in str(call) for call in mock_logger.info.call_args_list)
        assert any("idx_task_queue_lookup" in str(call) for call in mock_logger.info.call_args_list)
        assert any("dead_letter_queue" in str(call) for call in mock_logger.info.call_args_list)

    @patch("async_task_q.cli.commands.migrate.isinstance")
    @patch("async_task_q.drivers.mysql_driver.MySQLDriver")
    @patch("async_task_q.cli.commands.migrate.DriverFactory")
    @mark.asyncio
    async def test_run_migrate_mysql_disconnects_on_error(
        self, mock_driver_factory, mock_mysql_driver_class, mock_isinstance
    ) -> None:
        # Arrange
        args = argparse.Namespace()
        config = Config(driver="mysql")
        mock_driver = AsyncMock()
        mock_driver.connect.return_value = None
        mock_driver.init_schema.side_effect = Exception("Schema error")
        mock_driver_factory.create_from_config.return_value = mock_driver
        # Make isinstance return True for MySQLDriver check
        mock_isinstance.return_value = True

        # Act & Assert
        with raises(Exception, match="Schema error"):
            await run_migrate(args, config)

        # Assert - disconnect should be called even on error
        mock_driver.disconnect.assert_awaited_once()

    @patch("async_task_q.cli.commands.migrate.isinstance")
    @patch("async_task_q.drivers.mysql_driver.MySQLDriver")
    @patch("async_task_q.cli.commands.migrate.DriverFactory")
    @mark.asyncio
    async def test_run_migrate_mysql_disconnects_on_connect_error(
        self, mock_driver_factory, mock_mysql_driver_class, mock_isinstance
    ) -> None:
        # Arrange
        args = argparse.Namespace()
        config = Config(driver="mysql")
        mock_driver = AsyncMock()
        mock_driver.connect.side_effect = Exception("Connection error")
        mock_driver_factory.create_from_config.return_value = mock_driver
        # Make isinstance return True for MySQLDriver check
        mock_isinstance.return_value = True

        # Act & Assert
        with raises(Exception, match="Connection error"):
            await run_migrate(args, config)

        # Assert - disconnect should still be called
        mock_driver.disconnect.assert_awaited_once()

    @patch("async_task_q.cli.commands.migrate.isinstance")
    @patch("async_task_q.drivers.mysql_driver.MySQLDriver")
    @patch("async_task_q.cli.commands.migrate.DriverFactory")
    @patch("async_task_q.cli.commands.migrate.logger")
    @mark.asyncio
    async def test_run_migrate_mysql_with_custom_table_names(
        self, mock_logger, mock_driver_factory, mock_mysql_driver_class, mock_isinstance
    ) -> None:
        # Arrange
        args = argparse.Namespace()
        config = Config(
            driver="mysql",
            mysql_dsn="mysql://user:pass@localhost/db",
            mysql_queue_table="my_queue",
            mysql_dead_letter_table="my_dlq",
        )
        mock_driver = AsyncMock()
        mock_driver_factory.create_from_config.return_value = mock_driver
        # Make isinstance return True for MySQLDriver check
        mock_isinstance.return_value = True

        # Act
        await run_migrate(args, config)

        # Assert
        assert any("my_queue" in str(call) for call in mock_logger.info.call_args_list)
        assert any("my_dlq" in str(call) for call in mock_logger.info.call_args_list)
        assert any("idx_my_queue_lookup" in str(call) for call in mock_logger.info.call_args_list)


if __name__ == "__main__":
    main([__file__, "-s", "-m", "unit"])
