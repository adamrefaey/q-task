from unittest.mock import AsyncMock, MagicMock

from pytest import mark

from asynctasq.drivers.postgres_driver import PostgresDriver


@mark.unit
class TestPostgresDriverStatsAndManagement:
    @mark.asyncio
    async def test_get_queue_stats_and_global(self) -> None:
        driver = PostgresDriver(dsn="postgresql://user:pass@localhost/db")
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()

        mock_acquire_context = MagicMock()
        mock_acquire_context.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire_context.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire = MagicMock(return_value=mock_acquire_context)

        # transaction context manager for asyncpg (async with conn.transaction())
        tx_ctx = MagicMock()
        tx_ctx.__aenter__ = AsyncMock(return_value=None)
        tx_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_conn.transaction = MagicMock(return_value=tx_ctx)

        # fetchrow side effects for get_queue_stats: depth, processing, failed
        # then for get_global_stats: pending, processing, failed, total
        mock_conn.fetchrow.side_effect = [
            {"count": 5},
            {"count": 2},
            {"count": 1},
            {"count": 10},
            {"count": 3},
            {"count": 1},
            {"count": 20},
        ]

        driver.pool = mock_pool

        qs = await driver.get_queue_stats("default")
        assert qs["name"] == "default"
        assert qs["depth"] == 5
        assert qs["processing"] == 2

        g = await driver.get_global_stats()
        assert g["pending"] == 10
        assert g["running"] == 3
        assert g["failed"] == 1

    @mark.asyncio
    async def test_get_all_queue_names_and_running_tasks(self) -> None:
        driver = PostgresDriver(dsn="postgresql://user:pass@localhost/db")
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()

        mock_acquire_context = MagicMock()
        mock_acquire_context.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire_context.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire = MagicMock(return_value=mock_acquire_context)

        tx_ctx = MagicMock()
        tx_ctx.__aenter__ = AsyncMock(return_value=None)
        tx_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_conn.transaction = MagicMock(return_value=tx_ctx)

        # fetch for get_all_queue_names
        mock_conn.fetch.return_value = [{"queue_name": "a"}, {"queue_name": "b"}]

        # fetch for get_running_tasks (now returns payload, queue_name)
        mock_conn.fetch.side_effect = [
            [{"queue_name": "a"}, {"queue_name": "b"}],
            [
                {
                    "payload": b"task_data",
                    "queue_name": "default",
                }
            ],
        ]

        driver.pool = mock_pool

        names = await driver.get_all_queue_names()
        assert names == ["a", "b"]

        tasks = await driver.get_running_tasks()
        assert isinstance(tasks, list)
        # Now returns list of (bytes, str) tuples
        assert len(tasks) == 1
        assert tasks[0] == (b"task_data", "default")

    @mark.asyncio
    async def test_get_tasks_and_get_task_by_id(self) -> None:
        driver = PostgresDriver(dsn="postgresql://user:pass@localhost/db")
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()

        mock_acquire_context = MagicMock()
        mock_acquire_context.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire_context.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire = MagicMock(return_value=mock_acquire_context)

        tx_ctx = MagicMock()
        tx_ctx.__aenter__ = AsyncMock(return_value=None)
        tx_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_conn.transaction = MagicMock(return_value=tx_ctx)

        # fetch for list (now returns payload, queue_name, status)
        mock_conn.fetch.return_value = [
            {
                "payload": b"task_data",
                "queue_name": "default",
                "status": "pending",
            }
        ]
        mock_conn.fetchrow.return_value = {"count": 1}

        driver.pool = mock_pool

        tasks, total = await driver.get_tasks()
        assert total == 1
        assert len(tasks) == 1
        # Now returns list of (bytes, queue_name, status) tuples
        assert tasks[0] == (b"task_data", "default", "pending")

        # get_task_by_id (now returns just payload bytes)
        mock_conn.fetchrow.return_value = {
            "payload": b"task_data_by_id",
        }
        t = await driver.get_task_by_id("1")
        assert t is not None
        assert t == b"task_data_by_id"

    @mark.asyncio
    async def test_retry_and_delete_task(self) -> None:
        driver = PostgresDriver(dsn="postgresql://user:pass@localhost/db")
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()

        mock_acquire_context = MagicMock()
        mock_acquire_context.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire_context.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire = MagicMock(return_value=mock_acquire_context)

        tx_ctx = MagicMock()
        tx_ctx.__aenter__ = AsyncMock(return_value=None)
        tx_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_conn.transaction = MagicMock(return_value=tx_ctx)

        # retry_task: fetchrow returns dead-letter row
        mock_conn.fetchrow.side_effect = [
            {"queue_name": "default", "payload": b"p", "attempts": 0},
            None,
        ]

        driver.pool = mock_pool

        ok = await driver.retry_task("1")
        assert ok is True

        # delete_task: first delete returns row
        mock_conn.fetchrow.side_effect = [{"id": 1}, None]
        deleted = await driver.delete_task("1")
        assert deleted is True

    @mark.asyncio
    async def test_get_worker_stats_empty(self) -> None:
        driver = PostgresDriver(dsn="postgresql://user:pass@localhost/db")
        workers = await driver.get_worker_stats()
        assert workers == []
