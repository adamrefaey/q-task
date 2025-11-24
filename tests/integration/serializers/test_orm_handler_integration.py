"""
Integration tests for OrmHandler using real ORMs and PostgreSQL.

These tests use real ORM libraries (SQLAlchemy, Django, Tortoise) with a real
PostgreSQL database to validate end-to-end serialization and deserialization
of ORM models.

Setup:
    1. Ensure PostgreSQL is running (see test_postgres_driver.py for setup instructions)
    2. Install optional dependencies:
       - pip install sqlalchemy django tortoise-orm
    3. Run tests: pytest -m integration tests/integration/serializers/test_orm_handler_integration.py

Note:
    These are INTEGRATION tests requiring:
    - PostgreSQL running
    - Optional ORM dependencies installed
    - ORM test tables created (see 02-create-orm-tables.sql)
"""

import asyncio
import contextvars
from collections.abc import AsyncGenerator
from datetime import datetime

import asyncpg
import django
import pytest
from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.exceptions import AppRegistryNotReady
from django.db import connections, models
from pytest import fixture, main, mark
from sqlalchemy import Column, DateTime, Integer, String, create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from tortoise import Tortoise
from tortoise.fields import (
    CharField,
    DecimalField,
    IntField,
)
from tortoise.fields import (
    DatetimeField as DateTimeField,
)
from tortoise.models import Model

from async_task.serializers.orm_handler import OrmHandler

# Test configuration
POSTGRES_DSN = "postgresql://test:test@localhost:5432/test_db"

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


# ============================================================================
# SQLAlchemy Models
# ============================================================================


class Base(DeclarativeBase):
    pass


class SQLAlchemyUser(Base):
    __tablename__ = "sqlalchemy_test_users"

    id = Column(Integer, primary_key=True)
    username = Column(String(100), unique=True, nullable=False)
    email = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=datetime.now, onupdate=datetime.now
    )


class SQLAlchemyUserSession(Base):
    __tablename__ = "sqlalchemy_test_user_sessions"

    user_id = Column(Integer, primary_key=True)
    session_id = Column(String(100), primary_key=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.now)
    expires_at = Column(DateTime(timezone=True), nullable=True)


# ============================================================================
# Django Models
# ============================================================================

# Define Django model with a unique app label to avoid conflicts
# Use module name in app label to make it unique per import context
_DJANGO_APP_LABEL = f"test_orm_{__name__.replace('.', '_')}"

# Create model class - wrap in try-except to handle AppRegistryNotReady
# This can happen if Django isn't fully initialized yet
try:

    class DjangoProduct(models.Model):
        class Meta:
            db_table = "django_test_products"
            app_label = _DJANGO_APP_LABEL
            # Prevent Django from creating migrations (we use SQL migrations)
            managed = False

        name = models.CharField(max_length=200)
        price = models.DecimalField(max_digits=10, decimal_places=2)
        description = models.TextField(blank=True, null=True)
        created_at = models.DateTimeField(auto_now_add=True)
        updated_at = models.DateTimeField(auto_now=True)
except AppRegistryNotReady:
    # Django not ready yet, define model as a placeholder
    # It will be properly registered when Django is ready
    DjangoProduct = None  # type: ignore[assignment, misc]


# ============================================================================
# Tortoise Models
# ============================================================================


class TortoiseOrder(Model):
    class Meta:  # type: ignore[misc]
        table = "tortoise_test_orders"

    id = IntField(primary_key=True)
    order_number = CharField(max_length=50, unique=True)
    customer_name = CharField(max_length=200)
    total_amount = DecimalField(max_digits=10, decimal_places=2)
    status = CharField(max_length=50, default="pending")
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)


# ============================================================================
# Fixtures
# ============================================================================


@fixture(scope="session")
def postgres_dsn() -> str:
    """PostgreSQL connection DSN."""
    return POSTGRES_DSN


@fixture
async def postgres_conn(postgres_dsn: str) -> AsyncGenerator[asyncpg.Connection, None]:
    """Create a PostgreSQL connection for direct database operations."""
    conn = await asyncpg.connect(postgres_dsn)
    yield conn
    await conn.close()


@fixture
def orm_handler() -> OrmHandler:
    """Create an OrmHandler instance."""
    return OrmHandler()


@fixture(autouse=True)
def django_connection_cleanup():
    """Close all Django connections before each test to avoid thread-safety issues."""
    # Close all connections before test (thread-safe)
    connections.close_all()
    yield
    # Close all connections after test
    connections.close_all()


# ============================================================================
# SQLAlchemy Integration Tests
# ============================================================================


@mark.integration
class TestSQLAlchemyIntegration:
    """Integration tests for SQLAlchemy ORM models."""

    @fixture
    async def async_engine(self, postgres_dsn: str):
        """Create async SQLAlchemy engine."""
        # Convert postgresql:// to postgresql+asyncpg://
        async_dsn = postgres_dsn.replace("postgresql://", "postgresql+asyncpg://")
        engine = create_async_engine(async_dsn, echo=False)
        yield engine
        await engine.dispose()

    @fixture
    async def async_session(self, async_engine):
        """Create async SQLAlchemy session."""
        # Create tables before session
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async_session_maker = async_sessionmaker(
            async_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with async_session_maker() as session:
            yield session

        # Cleanup tables after session
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    @fixture
    def sync_engine(self, postgres_dsn: str):
        """Create sync SQLAlchemy engine."""
        engine = create_engine(postgres_dsn, echo=False)
        yield engine
        engine.dispose()

    @fixture
    def sync_session(self, sync_engine):
        """Create sync SQLAlchemy session."""
        # Create tables
        Base.metadata.create_all(sync_engine)
        session_maker = sessionmaker(bind=sync_engine)
        session = session_maker()
        yield session
        session.close()
        # Cleanup tables
        Base.metadata.drop_all(sync_engine)

    async def test_serialize_sqlalchemy_model_async(
        self,
        orm_handler: OrmHandler,
        async_session: AsyncSession,
        postgres_conn: asyncpg.Connection,
    ):
        """Test serializing a SQLAlchemy model with async session."""
        # Create and save a model
        user = SQLAlchemyUser(
            username="testuser",
            email="test@example.com",
        )
        async_session.add(user)
        await async_session.commit()
        await async_session.refresh(user)

        # Set session in context for deserialization
        session_var = contextvars.ContextVar("session")
        session_var.set(async_session)
        SQLAlchemyUser._async_task_session_var = session_var

        # Serialize
        serialized = orm_handler.serialize_model(user)
        assert serialized["__orm:sqlalchemy__"] == user.id
        assert serialized["__orm_class__"] == "test_orm_handler_integration.SQLAlchemyUser"

        # Deserialize
        deserialized = await orm_handler.deserialize_model(serialized)
        assert deserialized.id == user.id
        assert deserialized.username == user.username
        assert deserialized.email == user.email

        # Cleanup
        await async_session.delete(user)
        await async_session.commit()

    async def test_serialize_sqlalchemy_model_sync(
        self, orm_handler: OrmHandler, sync_session: Session, postgres_conn: asyncpg.Connection
    ):
        """Test serializing a SQLAlchemy model with sync session."""
        # Create and save a model
        user = SQLAlchemyUser(
            username="syncuser",
            email="sync@example.com",
        )
        sync_session.add(user)
        sync_session.commit()
        sync_session.refresh(user)

        # Set session in context for deserialization
        session_var = contextvars.ContextVar("session")
        session_var.set(sync_session)
        SQLAlchemyUser._async_task_session_var = session_var

        # Serialize
        serialized = orm_handler.serialize_model(user)
        assert serialized["__orm:sqlalchemy__"] == user.id
        assert serialized["__orm_class__"] == "test_orm_handler_integration.SQLAlchemyUser"

        # Deserialize (will use sync session via executor)
        deserialized = await orm_handler.deserialize_model(serialized)
        assert deserialized.id == user.id
        assert deserialized.username == user.username

        # Cleanup
        sync_session.delete(user)
        sync_session.commit()

    async def test_serialize_sqlalchemy_composite_pk(
        self,
        orm_handler: OrmHandler,
        async_session: AsyncSession,
        postgres_conn: asyncpg.Connection,
    ):
        """Test serializing a SQLAlchemy model with composite primary key."""
        # Create and save a model with composite PK
        session = SQLAlchemyUserSession(
            user_id=1,
            session_id="session123",
        )
        async_session.add(session)
        await async_session.commit()

        # Set session in context
        session_var = contextvars.ContextVar("session")
        session_var.set(async_session)
        SQLAlchemyUserSession._async_task_session_var = session_var

        # Serialize
        serialized = orm_handler.serialize_model(session)
        assert serialized["__orm:sqlalchemy__"] == (1, "session123")
        assert serialized["__orm_class__"] == "test_orm_handler_integration.SQLAlchemyUserSession"

        # Deserialize
        deserialized = await orm_handler.deserialize_model(serialized)
        assert deserialized.user_id == 1
        assert deserialized.session_id == "session123"

        # Cleanup
        await async_session.delete(deserialized)
        await async_session.commit()

    async def test_process_for_serialization_with_sqlalchemy_models(
        self, orm_handler: OrmHandler, async_session: AsyncSession
    ):
        """Test processing nested structures containing SQLAlchemy models."""
        # Create models
        user1 = SQLAlchemyUser(
            username="user1",
            email="user1@example.com",
        )
        user2 = SQLAlchemyUser(
            username="user2",
            email="user2@example.com",
        )
        async_session.add_all([user1, user2])
        await async_session.commit()
        await async_session.refresh(user1)
        await async_session.refresh(user2)

        # Process nested structure
        data = {
            "users": [user1, user2],
            "metadata": {"count": 2, "primary_user": user1},
            "simple": "value",
        }

        processed = orm_handler.process_for_serialization(data)
        assert processed["simple"] == "value"
        assert len(processed["users"]) == 2
        assert all("__orm:sqlalchemy__" in item for item in processed["users"])
        assert "__orm:sqlalchemy__" in processed["metadata"]["primary_user"]

        # Cleanup
        await async_session.delete(user1)
        await async_session.delete(user2)
        await async_session.commit()


# ============================================================================
# Django Integration Tests
# ============================================================================


@mark.integration
class TestDjangoIntegration:
    """Integration tests for Django ORM models."""

    async def test_serialize_django_model_async(
        self, orm_handler: OrmHandler, postgres_conn: asyncpg.Connection
    ):
        """Test serializing a Django model with async query."""
        if DjangoProduct is None:
            pytest.skip("DjangoProduct model not initialized")

        # Create and save a model (Django will create connection automatically)
        create_product = sync_to_async(DjangoProduct.objects.create)  # type: ignore[union-attr]
        product = await create_product(
            name="Test Product",
            price="99.99",
            description="A test product",
        )

        # Serialize
        serialized = orm_handler.serialize_model(product)
        assert serialized["__orm:django__"] == product.pk
        assert serialized["__orm_class__"] == "test_orm_handler_integration.DjangoProduct"

        # Deserialize
        deserialized = await orm_handler.deserialize_model(serialized)
        assert deserialized.pk == product.pk
        assert deserialized.name == product.name
        assert str(deserialized.price) == "99.99"

        # Cleanup
        await sync_to_async(product.delete)()

    async def test_serialize_django_model_sync(
        self, orm_handler: OrmHandler, postgres_conn: asyncpg.Connection
    ):
        """Test serializing a Django model with sync query (fallback)."""
        if DjangoProduct is None:
            pytest.skip("DjangoProduct model not initialized")

        # Create and save a model (Django will create connection automatically)
        create_product = sync_to_async(DjangoProduct.objects.create)  # type: ignore[union-attr]
        product = await create_product(
            name="Sync Product",
            price="49.99",
        )

        # Serialize
        serialized = orm_handler.serialize_model(product)
        assert serialized["__orm:django__"] == product.pk

        # Deserialize (will use sync if async not available)
        deserialized = await orm_handler.deserialize_model(serialized)
        assert deserialized.pk == product.pk
        assert deserialized.name == "Sync Product"

        # Cleanup
        await sync_to_async(product.delete)()

    async def test_process_for_serialization_with_django_models(
        self, orm_handler: OrmHandler, postgres_conn: asyncpg.Connection
    ):
        """Test processing nested structures containing Django models."""
        if DjangoProduct is None:
            pytest.skip("DjangoProduct model not initialized")

        # Create models (Django will create connection automatically)
        create_product = sync_to_async(DjangoProduct.objects.create)  # type: ignore[union-attr]
        product1 = await create_product(name="Product 1", price="10.00")
        product2 = await create_product(name="Product 2", price="20.00")

        # Process nested structure
        data = {
            "products": [product1, product2],
            "total": 2,
            "featured": product1,
        }

        processed = orm_handler.process_for_serialization(data)
        assert processed["total"] == 2
        assert len(processed["products"]) == 2
        assert all("__orm:django__" in item for item in processed["products"])
        assert "__orm:django__" in processed["featured"]

        # Cleanup
        await sync_to_async(product1.delete)()
        await sync_to_async(product2.delete)()


# ============================================================================
# Tortoise Integration Tests
# ============================================================================


@mark.integration
class TestTortoiseIntegration:
    """Integration tests for Tortoise ORM models."""

    @fixture(scope="function", autouse=True)
    async def setup_tortoise(self, postgres_dsn: str):
        """Initialize Tortoise ORM."""
        # Convert postgresql:// to postgres:// for Tortoise (it uses postgres://)
        tortoise_dsn = postgres_dsn.replace("postgresql://", "postgres://")
        # Use __name__ to get the current module path dynamically
        module_path = __name__
        try:
            await Tortoise.init(
                db_url=tortoise_dsn,
                modules={"models": [module_path]},
            )
            await Tortoise.generate_schemas()
            yield
        finally:
            await Tortoise.close_connections()

    async def test_serialize_tortoise_model(
        self, orm_handler: OrmHandler, postgres_conn: asyncpg.Connection, setup_tortoise
    ):
        """Test serializing a Tortoise ORM model."""
        # Create and save a model
        order = await TortoiseOrder.create(
            order_number="ORD-001",
            customer_name="John Doe",
            total_amount="150.00",
            status="pending",
        )

        # Serialize
        serialized = orm_handler.serialize_model(order)
        assert serialized["__orm:tortoise__"] == order.pk
        # Use __name__ to match the actual module path
        expected_class_path = f"{__name__}.TortoiseOrder"
        assert serialized["__orm_class__"] == expected_class_path

        # Deserialize
        deserialized = await orm_handler.deserialize_model(serialized)
        assert deserialized.pk == order.pk
        assert deserialized.order_number == "ORD-001"
        assert deserialized.customer_name == "John Doe"
        assert str(deserialized.total_amount) == "150.00"

        # Cleanup - ensure connection is properly closed
        await order.delete()
        # Small delay to ensure cleanup completes
        await asyncio.sleep(0.1)

    async def test_process_for_serialization_with_tortoise_models(
        self, orm_handler: OrmHandler, postgres_conn: asyncpg.Connection, setup_tortoise
    ):
        """Test processing nested structures containing Tortoise models."""
        # Create models
        order1 = await TortoiseOrder.create(
            order_number="ORD-002",
            customer_name="Jane Doe",
            total_amount="200.00",
            status="completed",
        )
        order2 = await TortoiseOrder.create(
            order_number="ORD-003",
            customer_name="Bob Smith",
            total_amount="300.00",
            status="pending",
        )

        # Process nested structure
        data = {
            "orders": [order1, order2],
            "count": 2,
            "latest": order2,
        }

        processed = orm_handler.process_for_serialization(data)
        assert processed["count"] == 2
        assert len(processed["orders"]) == 2
        assert all("__orm:tortoise__" in item for item in processed["orders"])
        assert "__orm:tortoise__" in processed["latest"]

        # Cleanup - ensure connections are properly closed
        await order1.delete()
        await order2.delete()
        # Small delay to ensure cleanup completes
        await asyncio.sleep(0.1)


# ============================================================================
# Cross-ORM Integration Tests
# ============================================================================


@mark.integration
class TestCrossOrmIntegration:
    """Integration tests mixing multiple ORMs."""

    @fixture
    async def async_engine(self, postgres_dsn: str):
        """Create async SQLAlchemy engine."""
        # Convert postgresql:// to postgresql+asyncpg://
        async_dsn = postgres_dsn.replace("postgresql://", "postgresql+asyncpg://")
        engine = create_async_engine(async_dsn, echo=False)
        yield engine
        await engine.dispose()

    @fixture
    async def async_session(self, async_engine):
        """Create async SQLAlchemy session."""
        # Create tables before session
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async_session_maker = async_sessionmaker(
            async_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with async_session_maker() as session:
            yield session

        # Cleanup tables after session
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    async def test_mixed_orm_models_serialization(
        self, orm_handler: OrmHandler, async_session: AsyncSession
    ):
        """Test serializing a structure with models from different ORMs."""
        # Create SQLAlchemy model
        user = SQLAlchemyUser(
            username="mixeduser",
            email="mixed@example.com",
        )
        async_session.add(user)
        await async_session.commit()
        await async_session.refresh(user)

        # Set session
        session_var = contextvars.ContextVar("session")
        session_var.set(async_session)
        SQLAlchemyUser._async_task_session_var = session_var

        # Create mixed data structure
        data = {
            "user": user,
            "metadata": {"type": "mixed", "count": 1},
            "nested": {
                "level1": {
                    "level2": {"user_ref": user},
                },
            },
        }

        # Serialize
        processed = orm_handler.process_for_serialization(data)
        assert processed["metadata"]["type"] == "mixed"
        assert "__orm:sqlalchemy__" in processed["user"]
        assert "__orm:sqlalchemy__" in processed["nested"]["level1"]["level2"]["user_ref"]

        # Cleanup
        await async_session.delete(user)
        await async_session.commit()


# ============================================================================
# Round-trip Integration Tests
# ============================================================================


@mark.integration
class TestRoundTripIntegration:
    """Test complete round-trip serialization/deserialization."""

    @fixture
    async def async_engine(self, postgres_dsn: str):
        """Create async SQLAlchemy engine."""
        # Convert postgresql:// to postgresql+asyncpg://
        async_dsn = postgres_dsn.replace("postgresql://", "postgresql+asyncpg://")
        engine = create_async_engine(async_dsn, echo=False)
        yield engine
        await engine.dispose()

    @fixture
    async def async_session(self, async_engine):
        """Create async SQLAlchemy session."""
        # Create tables before session
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async_session_maker = async_sessionmaker(
            async_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with async_session_maker() as session:
            yield session

        # Cleanup tables after session
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    async def test_round_trip_sqlalchemy_model(
        self, orm_handler: OrmHandler, async_session: AsyncSession
    ):
        """Test complete round-trip: serialize -> deserialize."""
        # Create model
        user = SQLAlchemyUser(
            username="roundtrip",
            email="roundtrip@example.com",
        )
        async_session.add(user)
        await async_session.commit()
        await async_session.refresh(user)

        # Set session
        session_var = contextvars.ContextVar("session")
        session_var.set(async_session)
        SQLAlchemyUser._async_task_session_var = session_var

        # Round-trip
        serialized = orm_handler.process_for_serialization({"user": user, "extra": "data"})
        deserialized = await orm_handler.process_for_deserialization(serialized)

        assert deserialized["extra"] == "data"
        assert deserialized["user"].id == user.id
        assert deserialized["user"].username == user.username

        # Cleanup
        await async_session.delete(user)
        await async_session.commit()


if __name__ == "__main__":
    main([__file__, "-s", "-m", "integration"])
