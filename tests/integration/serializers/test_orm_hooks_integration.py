"""
Integration tests for ORM hooks using real ORMs and PostgreSQL.

These tests use real ORM libraries (SQLAlchemy, Django, Tortoise) with a real
PostgreSQL database to validate end-to-end serialization and deserialization
of ORM models using the hook system.

Setup:
    1. Ensure PostgreSQL is running (see Docker setup)
    2. Install optional dependencies:
       - pip install sqlalchemy django tortoise-orm asyncpg
    3. Run tests: pytest -m integration tests/integration/serializers/

Note:
    These are INTEGRATION tests requiring:
    - PostgreSQL running
    - Optional ORM dependencies installed
"""

from collections.abc import AsyncGenerator, Generator
import contextvars
from datetime import datetime

import asyncpg
import django
from django.conf import settings
from django.db import models
from pytest import fixture, mark
import pytest_asyncio
from sqlalchemy import Column, DateTime, Integer, String, create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from tortoise import Tortoise
from tortoise.fields import CharField, IntField
from tortoise.fields import DatetimeField as DateTimeField
from tortoise.models import Model

from asynctasq.serializers.hooks import HookRegistry, SerializationPipeline
from asynctasq.serializers.orm_hooks import (
    DjangoOrmHook,
    SqlalchemyOrmHook,
    TortoiseOrmHook,
    register_orm_hooks,
)

# Test configuration
POSTGRES_DSN = "postgresql://test:test@localhost:5432/test_db"
POSTGRES_ASYNC_DSN = "postgresql+asyncpg://test:test@localhost:5432/test_db"

# Django setup
if not settings.configured:
    settings.configure(
        DEBUG=True,
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": "test_db",
                "USER": "test",
                "PASSWORD": "test",
                "HOST": "localhost",
                "PORT": "5432",
            }
        },
        INSTALLED_APPS=[],
        USE_TZ=True,
    )
    django.setup()


# =============================================================================
# SQLAlchemy Models
# =============================================================================


class Base(DeclarativeBase):
    pass


class SQLAlchemyUser(Base):
    __tablename__ = "sqlalchemy_test_users"

    id = Column(Integer, primary_key=True)
    username = Column(String(100), unique=True, nullable=False)
    email = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now)


class SQLAlchemyUserSession(Base):
    """Model with composite primary key."""

    __tablename__ = "sqlalchemy_test_user_sessions"

    user_id = Column(Integer, primary_key=True)
    session_id = Column(String(100), primary_key=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now)


# =============================================================================
# Django Models
# =============================================================================


class DjangoUser(models.Model):
    username = models.CharField(max_length=100, unique=True)
    email = models.EmailField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "test_app"
        db_table = "django_test_users"


# =============================================================================
# Tortoise Models
# =============================================================================


class TortoiseUser(Model):
    id = IntField(pk=True)
    username = CharField(max_length=100, unique=True)
    email = CharField(max_length=255)
    created_at = DateTimeField(auto_now_add=True)

    class Meta:  # type: ignore[reportIncompatibleVariableOverride]
        table = "tortoise_test_users"


# =============================================================================
# Fixtures
# =============================================================================


@fixture(scope="module")
def postgres_dsn() -> str:
    """PostgreSQL DSN for sync connections."""
    return POSTGRES_DSN


@pytest_asyncio.fixture
async def postgres_conn() -> AsyncGenerator[asyncpg.Connection, None]:
    """Create async PostgreSQL connection for setup/teardown."""
    conn = await asyncpg.connect(
        host="localhost",
        port=5432,
        user="test",
        password="test",
        database="test_db",
    )
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def async_engine():
    """Create async SQLAlchemy engine."""
    engine = create_async_engine(POSTGRES_ASYNC_DSN, echo=False)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def async_session(async_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create async SQLAlchemy session."""
    async_session_maker = async_sessionmaker(async_engine, expire_on_commit=False)
    async with async_session_maker() as session:
        yield session


@fixture
def sync_engine():
    """Create sync SQLAlchemy engine."""
    return create_engine(POSTGRES_DSN.replace("postgresql://", "postgresql+psycopg2://"))


@fixture
def sync_session(sync_engine) -> Generator[Session, None, None]:
    """Create sync SQLAlchemy session."""
    SessionLocal = sessionmaker(bind=sync_engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest_asyncio.fixture
async def setup_tortoise():
    """Initialize Tortoise ORM."""
    await Tortoise.init(
        db_url="postgres://test:test@localhost:5432/test_db",
        modules={"models": [__name__]},
    )
    yield
    await Tortoise.close_connections()


@fixture
def sqlalchemy_hook() -> SqlalchemyOrmHook:
    """Create SQLAlchemy hook."""
    return SqlalchemyOrmHook()


@fixture
def django_hook() -> DjangoOrmHook:
    """Create Django hook."""
    return DjangoOrmHook()


@fixture
def tortoise_hook() -> TortoiseOrmHook:
    """Create Tortoise hook."""
    return TortoiseOrmHook()


@fixture
def registry_with_orm_hooks() -> HookRegistry:
    """Create registry with all ORM hooks registered."""
    registry = HookRegistry()
    register_orm_hooks(registry)
    return registry


@fixture
def pipeline_with_orm(registry_with_orm_hooks: HookRegistry) -> SerializationPipeline:
    """Create pipeline with ORM hooks."""
    return SerializationPipeline(registry_with_orm_hooks)


# =============================================================================
# SQLAlchemy Integration Tests
# =============================================================================


@mark.integration
class TestSqlalchemyHookIntegration:
    """Integration tests for SQLAlchemy ORM hook."""

    @mark.asyncio
    async def test_can_encode_real_sqlalchemy_model(
        self,
        sqlalchemy_hook: SqlalchemyOrmHook,
        async_session: AsyncSession,
        postgres_conn: asyncpg.Connection,
    ) -> None:
        """Test can_encode with real SQLAlchemy model."""
        # Create test data
        await postgres_conn.execute(
            """
            INSERT INTO sqlalchemy_test_users (id, username, email, created_at)
            VALUES (9001, 'encode_test', 'encode@test.com', NOW())
            ON CONFLICT (id) DO NOTHING
            """
        )

        try:
            user = await async_session.get(SQLAlchemyUser, 9001)
            assert user is not None
            assert sqlalchemy_hook.can_encode(user) is True
        finally:
            await postgres_conn.execute("DELETE FROM sqlalchemy_test_users WHERE id = 9001")

    @mark.asyncio
    async def test_encode_real_sqlalchemy_model(
        self,
        sqlalchemy_hook: SqlalchemyOrmHook,
        async_session: AsyncSession,
        postgres_conn: asyncpg.Connection,
    ) -> None:
        """Test encoding a real SQLAlchemy model."""
        await postgres_conn.execute(
            """
            INSERT INTO sqlalchemy_test_users (id, username, email, created_at)
            VALUES (9002, 'encode_real', 'real@test.com', NOW())
            ON CONFLICT (id) DO NOTHING
            """
        )

        try:
            user = await async_session.get(SQLAlchemyUser, 9002)
            assert user is not None

            result = sqlalchemy_hook.encode(user)
            assert result["__orm:sqlalchemy__"] == 9002
            assert "SQLAlchemyUser" in result["__orm_class__"]
        finally:
            await postgres_conn.execute("DELETE FROM sqlalchemy_test_users WHERE id = 9002")

    @mark.asyncio
    async def test_round_trip_sqlalchemy_model(
        self,
        sqlalchemy_hook: SqlalchemyOrmHook,
        async_session: AsyncSession,
        postgres_conn: asyncpg.Connection,
    ) -> None:
        """Test full round-trip encode/decode for SQLAlchemy model."""
        await postgres_conn.execute(
            """
            INSERT INTO sqlalchemy_test_users (id, username, email, created_at)
            VALUES (9003, 'roundtrip', 'roundtrip@test.com', NOW())
            ON CONFLICT (id) DO NOTHING
            """
        )

        try:
            # Get original model
            user = await async_session.get(SQLAlchemyUser, 9003)
            assert user is not None

            # Encode
            encoded = sqlalchemy_hook.encode(user)

            # Set up session for decode
            session_var: contextvars.ContextVar = contextvars.ContextVar("session")
            session_var.set(async_session)
            SQLAlchemyUser._asynctasq_session_var = session_var

            # Decode
            decoded = await sqlalchemy_hook.decode_async(encoded)

            assert decoded.id == user.id
            assert decoded.username == user.username
            assert decoded.email == user.email
        finally:
            await postgres_conn.execute("DELETE FROM sqlalchemy_test_users WHERE id = 9003")
            if hasattr(SQLAlchemyUser, "_asynctasq_session_var"):
                delattr(SQLAlchemyUser, "_asynctasq_session_var")

    @mark.asyncio
    async def test_composite_primary_key(
        self,
        sqlalchemy_hook: SqlalchemyOrmHook,
        async_session: AsyncSession,
        postgres_conn: asyncpg.Connection,
    ) -> None:
        """Test encoding model with composite primary key."""
        await postgres_conn.execute(
            """
            INSERT INTO sqlalchemy_test_user_sessions (user_id, session_id, created_at)
            VALUES (1, 'session-abc', NOW())
            ON CONFLICT DO NOTHING
            """
        )

        try:
            session_model = await async_session.get(SQLAlchemyUserSession, (1, "session-abc"))
            assert session_model is not None

            encoded = sqlalchemy_hook.encode(session_model)
            # Composite PK should be a tuple
            assert encoded["__orm:sqlalchemy__"] == (1, "session-abc")
        finally:
            await postgres_conn.execute(
                "DELETE FROM sqlalchemy_test_user_sessions WHERE user_id = 1 AND session_id = 'session-abc'"
            )


# =============================================================================
# Tortoise Integration Tests
# =============================================================================


@mark.integration
class TestTortoiseHookIntegration:
    """Integration tests for Tortoise ORM hook."""

    @mark.asyncio
    async def test_can_encode_real_tortoise_model(
        self,
        tortoise_hook: TortoiseOrmHook,
        postgres_conn: asyncpg.Connection,
        setup_tortoise,
    ) -> None:
        """Test can_encode with real Tortoise model."""
        await postgres_conn.execute(
            """
            INSERT INTO tortoise_test_users (id, username, email, created_at)
            VALUES (9001, 'tortoise_test', 'tortoise@test.com', NOW())
            ON CONFLICT (id) DO NOTHING
            """
        )

        try:
            user = await TortoiseUser.get(id=9001)
            assert tortoise_hook.can_encode(user) is True
        finally:
            await postgres_conn.execute("DELETE FROM tortoise_test_users WHERE id = 9001")

    @mark.asyncio
    async def test_encode_real_tortoise_model(
        self,
        tortoise_hook: TortoiseOrmHook,
        postgres_conn: asyncpg.Connection,
        setup_tortoise,
    ) -> None:
        """Test encoding a real Tortoise model."""
        await postgres_conn.execute(
            """
            INSERT INTO tortoise_test_users (id, username, email, created_at)
            VALUES (9002, 'tortoise_encode', 'encode@test.com', NOW())
            ON CONFLICT (id) DO NOTHING
            """
        )

        try:
            user = await TortoiseUser.get(id=9002)
            result = tortoise_hook.encode(user)

            assert result["__orm:tortoise__"] == 9002
            assert "TortoiseUser" in result["__orm_class__"]
        finally:
            await postgres_conn.execute("DELETE FROM tortoise_test_users WHERE id = 9002")

    @mark.asyncio
    async def test_round_trip_tortoise_model(
        self,
        tortoise_hook: TortoiseOrmHook,
        postgres_conn: asyncpg.Connection,
        setup_tortoise,
    ) -> None:
        """Test full round-trip encode/decode for Tortoise model."""
        await postgres_conn.execute(
            """
            INSERT INTO tortoise_test_users (id, username, email, created_at)
            VALUES (9003, 'tortoise_rt', 'rt@test.com', NOW())
            ON CONFLICT (id) DO NOTHING
            """
        )

        try:
            user = await TortoiseUser.get(id=9003)
            encoded = tortoise_hook.encode(user)
            decoded = await tortoise_hook.decode_async(encoded)

            assert decoded.id == user.id
            assert decoded.username == user.username
            assert decoded.email == user.email
        finally:
            await postgres_conn.execute("DELETE FROM tortoise_test_users WHERE id = 9003")


# =============================================================================
# Pipeline Integration Tests
# =============================================================================


@mark.integration
class TestPipelineWithOrmHooks:
    """Integration tests for SerializationPipeline with ORM hooks."""

    @mark.asyncio
    async def test_pipeline_encodes_sqlalchemy_model(
        self,
        pipeline_with_orm: SerializationPipeline,
        async_session: AsyncSession,
        postgres_conn: asyncpg.Connection,
    ) -> None:
        """Test pipeline encodes SQLAlchemy models in nested structures."""
        await postgres_conn.execute(
            """
            INSERT INTO sqlalchemy_test_users (id, username, email, created_at)
            VALUES (9010, 'pipeline_test', 'pipeline@test.com', NOW())
            ON CONFLICT (id) DO NOTHING
            """
        )

        try:
            user = await async_session.get(SQLAlchemyUser, 9010)
            assert user is not None

            data = {
                "user": user,
                "metadata": {"action": "test"},
            }

            encoded = pipeline_with_orm.encode(data)

            assert "__orm:sqlalchemy__" in encoded["user"]
            assert encoded["metadata"] == {"action": "test"}
        finally:
            await postgres_conn.execute("DELETE FROM sqlalchemy_test_users WHERE id = 9010")

    @mark.asyncio
    async def test_pipeline_decodes_sqlalchemy_model(
        self,
        pipeline_with_orm: SerializationPipeline,
        async_session: AsyncSession,
        postgres_conn: asyncpg.Connection,
    ) -> None:
        """Test pipeline decodes ORM references back to models."""
        await postgres_conn.execute(
            """
            INSERT INTO sqlalchemy_test_users (id, username, email, created_at)
            VALUES (9011, 'decode_test', 'decode@test.com', NOW())
            ON CONFLICT (id) DO NOTHING
            """
        )

        try:
            # Set up session context
            session_var: contextvars.ContextVar = contextvars.ContextVar("session")
            session_var.set(async_session)
            SQLAlchemyUser._asynctasq_session_var = session_var

            encoded_data = {
                "user": {
                    "__orm:sqlalchemy__": 9011,
                    "__orm_class__": f"{__name__}.SQLAlchemyUser",
                },
                "action": "test",
            }

            decoded = await pipeline_with_orm.decode_async(encoded_data)

            assert isinstance(decoded["user"], SQLAlchemyUser)
            assert decoded["user"].id == 9011
            assert decoded["user"].username == "decode_test"
            assert decoded["action"] == "test"
        finally:
            await postgres_conn.execute("DELETE FROM sqlalchemy_test_users WHERE id = 9011")
            if hasattr(SQLAlchemyUser, "_asynctasq_session_var"):
                delattr(SQLAlchemyUser, "_asynctasq_session_var")

    @mark.asyncio
    async def test_pipeline_handles_list_of_models(
        self,
        pipeline_with_orm: SerializationPipeline,
        async_session: AsyncSession,
        postgres_conn: asyncpg.Connection,
    ) -> None:
        """Test pipeline handles lists containing ORM models."""
        await postgres_conn.execute(
            """
            INSERT INTO sqlalchemy_test_users (id, username, email, created_at)
            VALUES 
                (9020, 'list_user1', 'list1@test.com', NOW()),
                (9021, 'list_user2', 'list2@test.com', NOW())
            ON CONFLICT (id) DO NOTHING
            """
        )

        try:
            user1 = await async_session.get(SQLAlchemyUser, 9020)
            user2 = await async_session.get(SQLAlchemyUser, 9021)

            data = {"users": [user1, user2]}
            encoded = pipeline_with_orm.encode(data)

            assert len(encoded["users"]) == 2
            assert "__orm:sqlalchemy__" in encoded["users"][0]
            assert "__orm:sqlalchemy__" in encoded["users"][1]
        finally:
            await postgres_conn.execute(
                "DELETE FROM sqlalchemy_test_users WHERE id IN (9020, 9021)"
            )
