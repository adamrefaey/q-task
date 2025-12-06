# Class-Based Tasks: Complete Examples Guide

This guide provides concrete, ready-to-use code examples demonstrating all scenarios, options, and capabilities of class-based tasks in Async TasQ.

Class-based tasks use the `Task` base class to create reusable, testable tasks with lifecycle hooks, custom retry logic, and advanced configuration options.

**Key Features:**

- **Lifecycle hooks** - `handle()`, `failed()`, `should_retry()` for complete control
- **Reusable and testable** - Class-based design for better organization
- **Flexible configuration** - Queue, retries, timeout, driver via class attributes or method chaining
- **Method chaining** - Override configuration at dispatch time with fluent API
- **ORM model serialization** - Automatic lightweight references for SQLAlchemy, Django, Tortoise
- **Type-safe** - Full type hints and Generic support
- **Sync task support** - `SyncTask` base class for blocking operations
- **Task metadata** - Access task ID, attempts, dispatched time

---

## Table of Contents

- [Basic Usage](#basic-usage)
- [Class Definition Syntax](#class-definition-syntax)
- [Configuration Options](#configuration-options)
- [Lifecycle Hooks](#lifecycle-hooks)
- [Dispatching Tasks](#dispatching-tasks)
- [Async vs Sync Tasks](#async-vs-sync-tasks)
- [Driver Overrides](#driver-overrides)
- [ORM Integration](#orm-integration)
- [Method Chaining](#method-chaining)
- [Task Metadata](#task-metadata)
- [Real-World Examples](#real-world-examples)
- [Complete Working Example](#complete-working-example)
- [Common Patterns and Best Practices](#common-patterns-and-best-practices)

---

## Basic Usage

### Simple Async TasQ

The simplest class-based task extends `Task` and implements the `handle()` method. All parameters passed to the constructor are automatically available as instance attributes:

```python
import asyncio
from asynctasq.core.task import Task
from asynctasq.config import set_global_config

# Configure the queue driver
# Note: Use 'redis', 'postgres', 'mysql', or 'sqs' for production
set_global_config(driver='redis')

# Define a simple task class
class SendNotification(Task[str]):
    """Send a notification message."""

    def __init__(self, message: str, **kwargs):
        super().__init__(**kwargs)
        self.message = message

    async def handle(self) -> str:
        print(f"Notification: {self.message}")
        await asyncio.sleep(0.1)  # Simulate async work
        return f"Sent: {self.message}"

# Dispatch the task
async def main():
    task_id = await SendNotification(message="Hello, World!").dispatch()
    print(f"Task dispatched with ID: {task_id}")
    # Note: Task will be executed by a worker process

if __name__ == "__main__":
    asyncio.run(main())
```

**Important:** After dispatching tasks, you must run a worker process to execute them. See [Running Workers](https://github.com/adamrefaey/asynctasq/blob/main/docs/running-workers.md) for details.

### Task with Parameters

Tasks accept parameters via `__init__`, which are automatically stored as instance attributes. All parameters passed to `__init__` (except `**kwargs`) should be explicitly assigned to instance attributes:

```python
from asynctasq.core.task import Task
from asynctasq.config import set_global_config

set_global_config(driver='redis')

class ProcessData(Task[int]):
    """Process data and return sum."""

    def __init__(self, data: list[int], **kwargs):
        super().__init__(**kwargs)
        self.data = data

    async def handle(self) -> int:
        """Process the data."""
        return sum(self.data)

# Dispatch
async def main():
    task_id = await ProcessData(data=[1, 2, 3, 4, 5]).dispatch()
    print(f"Task dispatched: {task_id}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

**Important:** Always call `super().__init__(**kwargs)` in your `__init__` to ensure proper task initialization. This allows the framework to properly set up task metadata and configuration.

---

## Class Definition Syntax

### Minimal Task (Uses Defaults)

```python
from asynctasq.core.task import Task

class SimpleTask(Task[None]):
    """Task with default configuration."""

    async def handle(self) -> None:
        print("Executing simple task")
```

### Task with Class-Level Configuration

```python
from asynctasq.core.task import Task

class SendEmail(Task[bool]):
    """Send email with custom configuration."""

    # Class-level configuration
    queue = "emails"
    max_retries = 5
    retry_delay = 120  # seconds
    timeout = 30  # seconds

    def __init__(self, to: str, subject: str, body: str, **kwargs):
        super().__init__(**kwargs)
        self.to = to
        self.subject = subject
        self.body = body

    async def handle(self) -> bool:
        print(f"Sending email to {self.to}: {self.subject}")
        # Email sending logic here
        return True
```

### Task with Type Hints

```python
from asynctasq.core.task import Task
from typing import Dict, Any

class ProcessOrder(Task[Dict[str, Any]]):
    """Process an order and return status."""

    queue = "orders"

    def __init__(self, order_id: int, user_id: int, **kwargs):
        super().__init__(**kwargs)
        self.order_id = order_id
        self.user_id = user_id

    async def handle(self) -> Dict[str, Any]:
        """Process the order."""
        # Order processing logic
        return {
            "order_id": self.order_id,
            "status": "processed",
            "user_id": self.user_id
        }
```

---

## Configuration Options

All configuration options can be set as class attributes. These settings apply to all instances of the task unless overridden at dispatch time using method chaining.

**Available Options:**

| Option             | Type                        | Default     | Description                                                      |
| ------------------ | --------------------------- | ----------- | ---------------------------------------------------------------- |
| `queue`            | `str`                       | `"default"` | Queue name for task execution                                    |
| `max_retries`      | `int`                       | `3`         | Maximum retry attempts on failure                                |
| `retry_delay`      | `int`                       | `60`        | Seconds to wait between retry attempts                           |
| `timeout`          | `int \| None`               | `None`      | Task timeout in seconds (`None` = no timeout)                    |
| `_driver_override` | `str \| BaseDriver \| None` | `None`      | Driver override (string or instance, `None` = use global config) |

### Queue Configuration

Use different queues to organize tasks by priority, type, or processing requirements:

```python
from asynctasq.core.task import Task

# Different queues for different task types
class SendEmail(Task[None]):
    queue = "emails"

    async def handle(self) -> None:
        pass

class ProcessPayment(Task[None]):
    queue = "payments"

    async def handle(self) -> None:
        pass

class SendPushNotification(Task[None]):
    queue = "notifications"

    async def handle(self) -> None:
        pass
```

**Tips:**

- Run separate workers for different queues to control resource allocation and priority
- Use descriptive queue names that indicate the task type or priority level
- Consider queue naming conventions: `high-priority`, `low-priority`, `critical`, `background`

### Retry Configuration

```python
from asynctasq.core.task import Task

# High retry count for critical operations
class ChargeCreditCard(Task[bool]):
    queue = "payments"
    max_retries = 10
    retry_delay = 30

    async def handle(self) -> bool:
        # Payment processing logic
        return True

# No retries for validation tasks
class ValidateData(Task[bool]):
    queue = "validation"
    max_retries = 0

    async def handle(self) -> bool:
        # Validation logic
        return True

# Custom retry delay
class CallExternalAPI(Task[dict]):
    queue = "api-calls"
    max_retries = 5
    retry_delay = 300  # 5 minutes (for rate-limited APIs)

    async def handle(self) -> dict:
        # API call logic
        return {}
```

### Timeout Configuration

```python
from asynctasq.core.task import Task

# Short timeout for quick operations
class QuickOperation(Task[None]):
    queue = "quick"
    timeout = 5

    async def handle(self) -> None:
        # Fast operation
        pass

# Long timeout for heavy operations
class GenerateReport(Task[str]):
    queue = "reports"
    timeout = 3600  # 1 hour

    async def handle(self) -> str:
        # Report generation logic
        return "report.pdf"

# No timeout (default)
class BackgroundCleanup(Task[None]):
    queue = "background"
    timeout = None

    async def handle(self) -> None:
        # Cleanup logic
        pass
```

### Combined Configuration

```python
from asynctasq.core.task import Task

class CriticalOperation(Task[dict]):
    """Fully configured critical task."""

    queue = "critical"
    max_retries = 10
    retry_delay = 60
    timeout = 300

    def __init__(self, data: dict, **kwargs):
        super().__init__(**kwargs)
        self.data = data

    async def handle(self) -> dict:
        # Critical operation logic
        return {"status": "completed"}
```

---

## Lifecycle Hooks

Class-based tasks provide three lifecycle hooks for complete control over task execution:

1. **`handle()`** - Main task logic (required)
2. **`failed()`** - Called when task fails after all retries (optional)
3. **`should_retry()`** - Custom retry logic (optional)

### The `handle()` Method

The `handle()` method is where your main task logic goes. It's the only required method:

```python
from asynctasq.core.task import Task

class ProcessOrder(Task[bool]):
    queue = "orders"

    def __init__(self, order_id: int, **kwargs):
        super().__init__(**kwargs)
        self.order_id = order_id

    async def handle(self) -> bool:
        """Main task execution logic."""
        print(f"Processing order {self.order_id}")
        # Your business logic here
        await self._validate_order()
        await self._charge_payment()
        await self._fulfill_order()
        return True

    async def _validate_order(self):
        """Private helper method."""
        pass

    async def _charge_payment(self):
        """Private helper method."""
        pass

    async def _fulfill_order(self):
        """Private helper method."""
        pass
```

### The `failed()` Hook

The `failed()` method is called when a task fails after exhausting all retry attempts. Use it for cleanup, logging, alerting, or compensation:

```python
from asynctasq.core.task import Task
import logging

logger = logging.getLogger(__name__)

class ProcessPayment(Task[bool]):
    queue = "payments"
    max_retries = 3

    def __init__(self, user_id: int, amount: float, **kwargs):
        super().__init__(**kwargs)
        self.user_id = user_id
        self.amount = amount

    async def handle(self) -> bool:
        """Process payment."""
        # Payment processing logic
        if self.amount < 0:
            raise ValueError("Amount cannot be negative")
        return True

    async def failed(self, exception: Exception) -> None:
        """Handle permanent failure after all retries."""
        logger.error(
            f"Payment failed permanently for user {self.user_id}: {exception}",
            exc_info=True
        )

        # Compensation: Refund if already charged
        await self._refund_if_charged()

        # Alerting: Notify administrators
        await self._notify_admins(exception)

        # Cleanup: Update order status
        await self._mark_order_failed()

    async def _refund_if_charged(self):
        """Refund user if payment was already charged."""
        pass

    async def _notify_admins(self, exception: Exception):
        """Notify administrators of failure."""
        pass

    async def _mark_order_failed(self):
        """Mark order as failed in database."""
        pass
```

**Common Use Cases for `failed()`:**

- Logging errors to external systems
- Sending alerts to monitoring services
- Compensating for partial operations (refunds, rollbacks)
- Updating database records to reflect failure
- Notifying users of permanent failures

### The `should_retry()` Hook

The `should_retry()` method allows you to implement custom retry logic based on the exception type. Return `True` to retry, `False` to fail immediately:

```python
from asynctasq.core.task import Task
import httpx

class CallExternalAPI(Task[dict]):
    queue = "api"
    max_retries = 5

    def __init__(self, url: str, **kwargs):
        super().__init__(**kwargs)
        self.url = url

    async def handle(self) -> dict:
        """Call external API."""
        async with httpx.AsyncClient() as client:
            response = await client.get(self.url, timeout=10.0)
            response.raise_for_status()
            return response.json()

    def should_retry(self, exception: Exception) -> bool:
        """Custom retry logic based on exception type."""
        # Don't retry validation errors (4xx)
        if isinstance(exception, httpx.HTTPStatusError):
            if 400 <= exception.response.status_code < 500:
                return False  # Client errors - don't retry

        # Always retry network errors (5xx, timeouts, connection errors)
        if isinstance(exception, (httpx.TimeoutException, httpx.ConnectError)):
            return True

        # Retry server errors (5xx)
        if isinstance(exception, httpx.HTTPStatusError):
            if exception.response.status_code >= 500:
                return True

        # Default: retry
        return True
```

**Common Retry Patterns:**

```python
from asynctasq.core.task import Task

class SmartRetryTask(Task[None]):
    """Example of various retry patterns."""

    def should_retry(self, exception: Exception) -> bool:
        # Pattern 1: Don't retry validation errors
        if isinstance(exception, ValueError):
            return False

        # Pattern 2: Always retry network errors
        if isinstance(exception, (ConnectionError, TimeoutError)):
            return True

        # Pattern 3: Retry based on exception message
        if "temporary" in str(exception).lower():
            return True

        # Pattern 4: Retry based on attempt count (0-indexed)
        # _attempts is 0 for first attempt, 1 for first retry, etc.
        if self._attempts < 2:  # Only retry first 2 attempts (attempts 0 and 1)
            return True

        # Pattern 5: Retry based on custom attribute
        if hasattr(exception, 'retryable') and exception.retryable:
            return True

        # Default: retry
        return True
```

### Complete Lifecycle Example

```python
from asynctasq.core.task import Task
import logging

logger = logging.getLogger(__name__)

class ProcessOrder(Task[dict]):
    """Complete example with all lifecycle hooks."""

    queue = "orders"
    max_retries = 3
    retry_delay = 60

    def __init__(self, order_id: int, user_id: int, **kwargs):
        super().__init__(**kwargs)
        self.order_id = order_id
        self.user_id = user_id

    async def handle(self) -> dict:
        """Main task logic."""
        logger.info(f"Processing order {self.order_id} for user {self.user_id}")

        # Step 1: Validate
        await self._validate_order()

        # Step 2: Charge payment
        await self._charge_payment()

        # Step 3: Fulfill order
        await self._fulfill_order()

        return {
            "order_id": self.order_id,
            "status": "completed"
        }

    def should_retry(self, exception: Exception) -> bool:
        """Custom retry logic."""
        # Don't retry validation errors
        if isinstance(exception, ValueError):
            logger.warning(f"Validation error - not retrying: {exception}")
            return False

        # Always retry network/connection errors
        if isinstance(exception, (ConnectionError, TimeoutError)):
            logger.info(f"Network error - will retry: {exception}")
            return True

        # Default: retry
        return True

    async def failed(self, exception: Exception) -> None:
        """Handle permanent failure."""
        logger.error(
            f"Order {self.order_id} failed permanently: {exception}",
            exc_info=True
        )

        # Compensation
        await self._refund_payment()

        # Update status
        await self._mark_order_failed()

        # Notify user
        await self._notify_user_failure()

    # Helper methods
    async def _validate_order(self):
        """Validate order."""
        pass

    async def _charge_payment(self):
        """Charge payment."""
        pass

    async def _fulfill_order(self):
        """Fulfill order."""
        pass

    async def _refund_payment(self):
        """Refund payment."""
        pass

    async def _mark_order_failed(self):
        """Mark order as failed."""
        pass

    async def _notify_user_failure(self):
        """Notify user of failure."""
        pass
```

---

## Dispatching Tasks

Tasks are dispatched by creating an instance and calling `.dispatch()`. The method returns a unique task ID (UUID string) for tracking.

**Important Notes:**

- Tasks are dispatched asynchronously and return immediately
- The task ID is generated before the task is queued
- Tasks will not execute until a worker process is running
- Use the task ID to track task status in your monitoring system

### Direct Dispatch (Recommended)

The simplest way to dispatch a task:

```python
from asynctasq.core.task import Task

class SendEmail(Task[bool]):
    queue = "emails"

    def __init__(self, to: str, subject: str, body: str, **kwargs):
        super().__init__(**kwargs)
        self.to = to
        self.subject = subject
        self.body = body

    async def handle(self) -> bool:
        print(f"Sending email to {self.to}")
        return True

# Dispatch immediately
async def main():
    task_id = await SendEmail(
        to="user@example.com",
        subject="Welcome",
        body="Welcome to our platform!"
    ).dispatch()
    print(f"Task ID: {task_id}")
```

### Dispatch with Delay

You can delay task execution using method chaining:

```python
from asynctasq.core.task import Task

class SendReminder(Task[None]):
    queue = "reminders"

    def __init__(self, user_id: int, message: str, **kwargs):
        super().__init__(**kwargs)
        self.user_id = user_id
        self.message = message

    async def handle(self) -> None:
        print(f"Sending reminder to user {self.user_id}: {self.message}")

# Dispatch with 60 second delay
async def main():
    task_id = await SendReminder(
        user_id=123,
        message="Don't forget to complete your profile!"
    ).delay(60).dispatch()
    print(f"Task will execute after 60 seconds: {task_id}")
```

**Note:** The `delay()` method specifies seconds until execution (must be greater than 0). For more complex scheduling, consider using a separate scheduling system.

---

## Async vs Sync Tasks

Async TasQ supports both async and synchronous class-based tasks. The framework automatically handles the execution differences:

- **Async tasks** (`Task`): Run directly in the event loop (recommended for I/O-bound tasks)
- **Sync tasks** (`SyncTask`): Automatically run in a thread pool (useful for CPU-bound or blocking operations)

**When to use each:**

| Use Case                              | Task Type    | Reason                                |
| ------------------------------------- | ------------ | ------------------------------------- |
| API calls, database queries, file I/O | **Task**     | Better performance, non-blocking      |
| CPU-intensive computation             | **SyncTask** | Simpler code, automatic thread pool   |
| Using blocking libraries              | **SyncTask** | No need to convert to async           |
| Network requests, web scraping        | **Task**     | Can handle many concurrent operations |
| Image processing, data analysis       | **SyncTask** | Thread pool handles CPU work          |
| Async libraries available             | **Task**     | Native async support                  |
| Only sync libraries available         | **SyncTask** | Works with any blocking library       |

### Task (Recommended)

Use `Task` for I/O-bound operations (API calls, database queries, file operations):

```python
from asynctasq.core.task import Task
import asyncio

class FetchUserData(Task[dict]):
    """Async task - runs directly in event loop."""
    queue = "api"

    def __init__(self, user_id: int, **kwargs):
        super().__init__(**kwargs)
        self.user_id = user_id

    async def handle(self) -> dict:
        """Can use await here."""
        await asyncio.sleep(0.1)
        return {"id": self.user_id, "name": "John"}
```

**Benefits:**

- Better performance for I/O-bound operations
- Can use `await` for async libraries (httpx, aiohttp, async database drivers, etc.)
- More efficient resource usage (no thread overhead)
- Better scalability for concurrent operations

### Sync Task (Runs in Thread Pool)

Use `SyncTask` for CPU-bound operations or when using blocking libraries:

```python
from asynctasq.core.task import SyncTask
import time

class HeavyComputation(SyncTask[int]):
    """Sync task - automatically runs in thread pool."""
    queue = "processing"

    def __init__(self, numbers: list[int], **kwargs):
        super().__init__(**kwargs)
        self.numbers = numbers

    def handle_sync(self) -> int:
        """Synchronous handle method - blocking operations OK."""
        time.sleep(2)  # Blocking operation
        return sum(x * x for x in self.numbers)
```

**Important:** Sync tasks implement `handle_sync()` instead of `handle()`. The framework automatically wraps it in a thread pool executor. You cannot use `await` in `handle_sync()` - it must be a synchronous method that performs blocking operations.

**Benefits:**

- No need to convert blocking code to async
- Automatic thread pool execution (managed by the framework)
- Works with any synchronous library (requests, PIL, pandas, etc.)
- Simpler code for CPU-bound operations

### Mixed Async/Sync in Same Application

```python
from asynctasq.core.task import Task, SyncTask
import asyncio
import time

# Async task
class AsyncOperation(Task[str]):
    queue = "asynctasqs"

    def __init__(self, data: str, **kwargs):
        super().__init__(**kwargs)
        self.data = data

    async def handle(self) -> str:
        await asyncio.sleep(0.1)
        return f"Processed: {self.data}"

# Sync task
class SyncOperation(SyncTask[str]):
    queue = "sync-tasks"

    def __init__(self, data: str, **kwargs):
        super().__init__(**kwargs)
        self.data = data

    def handle_sync(self) -> str:
        time.sleep(1)
        return f"Computed: {self.data}"

# Both can be dispatched the same way
async def main():
    task1_id = await AsyncOperation(data="async").dispatch()
    task2_id = await SyncOperation(data="sync").dispatch()
```

---

## Driver Overrides

### Per-Task Driver Override (String)

```python
from asynctasq.core.task import Task
from asynctasq.config import set_global_config

# Global config uses redis driver
set_global_config(driver='redis')

# This task uses Redis regardless of global config
class CriticalTask(Task[None]):
    queue = "critical"
    _driver_override = "redis"

    async def handle(self) -> None:
        print("Processing critical task")

# This task uses SQS
class AWSTask(Task[None]):
    queue = "aws-tasks"
    _driver_override = "sqs"

    async def handle(self) -> None:
        print("Processing AWS task")

# This task uses global config (redis)
class NormalTask(Task[None]):
    queue = "normal"
    # No _driver_override - uses global config

    async def handle(self) -> None:
        print("Processing normal task")
```

### Per-Task Driver Override (Driver Instance)

You can also pass a driver instance directly for complete control over driver configuration:

```python
from asynctasq.core.task import Task
from asynctasq.drivers.redis_driver import RedisDriver

# Create a custom driver instance with specific configuration
custom_redis = RedisDriver(
    url='redis://custom-host:6379',
    password='secret',
    db=1,
    max_connections=20
)

# Use the custom driver instance
class CustomDriverTask(Task[dict]):
    queue = "custom"
    _driver_override = custom_redis

    def __init__(self, data: dict, **kwargs):
        super().__init__(**kwargs)
        self.data = data

    async def handle(self) -> dict:
        print(f"Using custom driver: {self.data}")
        return self.data

# Dispatch task
async def main():
    task_id = await CustomDriverTask(data={"key": "value"}).dispatch()
    print(f"Task dispatched: {task_id}")
```

**Important Notes:**

- **Shared driver:** When using a driver instance, the driver is shared across all tasks using it
- **Isolation:** For per-task isolation, use string-based driver selection instead
- **Efficiency:** Driver instances are cached and reused, so creating multiple instances with the same configuration is inefficient
- **Initialization:** Ensure driver instances are properly initialized before task dispatch
- **Configuration:** Driver instances use their own configuration and ignore global config settings

### Multiple Drivers in Same Application

```python
from asynctasq.core.task import Task
from asynctasq.config import set_global_config

# Default driver
set_global_config(driver='redis')

# Tasks using different drivers
class RedisTask(Task[None]):
    queue = "redis-queue"
    _driver_override = "redis"

    async def handle(self) -> None:
        pass

class PostgresTask(Task[None]):
    queue = "postgres-queue"
    _driver_override = "postgres"

    async def handle(self) -> None:
        pass

class SQSTask(Task[None]):
    queue = "sqs-queue"
    _driver_override = "sqs"

    async def handle(self) -> None:
        pass

class RedisTask(Task[None]):
    queue = "default-queue"
    # No _driver_override - uses global config (redis)

    async def handle(self) -> None:
        pass
```

---

## ORM Integration

### SQLAlchemy Integration

**How it works:** SQLAlchemy models are automatically detected and serialized as lightweight references. Only the primary key is stored in the queue, and models are fetched fresh from the database when the task executes. This ensures data consistency and reduces queue payload size significantly.

**Configuration:** You must set a context variable on your model class to provide the session for fetching models during task execution. This is required for SQLAlchemy integration to work properly.

```python
import contextvars
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from asynctasq.core.task import Task

# Define models
class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str]
    name: Mapped[str]

class Order(Base):
    __tablename__ = 'orders'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int]
    total: Mapped[float]

# Setup SQLAlchemy
engine = create_async_engine('postgresql+asyncpg://user:pass@localhost/db')
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Configure session context variable for ORM handler
# This allows tasks to fetch models from the database
session_var = contextvars.ContextVar('session')

# Set the context variable on model classes
User._asynctasq_session_var = session_var
Order._asynctasq_session_var = session_var

# Task with ORM model parameter
class SendWelcomeEmail(Task[None]):
    queue = "emails"

    def __init__(self, user: User, **kwargs):
        super().__init__(**kwargs)
        self.user = user

    async def handle(self) -> None:
        """User is automatically serialized as reference and fetched fresh."""
        print(f"Sending welcome email to {self.user.email} (ID: {self.user.id})")
        # User data is fresh from database when task executes

class ProcessOrder(Task[None]):
    queue = "orders"

    def __init__(self, order: Order, user: User, **kwargs):
        super().__init__(**kwargs)
        self.order = order
        self.user = user

    async def handle(self) -> None:
        """Multiple ORM models supported."""
        print(f"Processing order {self.order.id} for user {self.user.name}")
        # Both models are fetched fresh in parallel

# Dispatch tasks
async def main():
    async with async_session() as session:
        # Set session in context for task execution
        session_var.set(session)

        # Fetch user
        user = await session.get(User, 1)

        # Only user.id is serialized to queue (90%+ payload reduction)
        task_id = await SendWelcomeEmail(user=user).dispatch()

        # Multiple models
        order = await session.get(Order, 100)
        task_id = await ProcessOrder(order=order, user=user).dispatch()
```

**Important Notes:**

- **Session context variable is required:** You must set `_asynctasq_session_var` on each model class for SQLAlchemy integration to work
-- **Worker configuration:** For production, ensure the session context variable is set in your worker process (see [ORM Integrations](https://github.com/adamrefaey/asynctasq/blob/main/docs/orm-integrations.md))
- **Fresh data:** Models are fetched fresh from the database when the task executes, ensuring data consistency
- **Payload optimization:** Only the primary key is serialized, reducing queue payload size by 90%+ for large models
- **Parallel fetching:** Multiple models in the same task are fetched in parallel for efficiency
- See [ORM Integrations](https://github.com/adamrefaey/asynctasq/blob/main/docs/orm-integrations.md) for complete setup instructions and worker configuration

### Django ORM Integration

```python
from django.db import models
from asynctasq.core.task import Task

# Define Django model
class User(models.Model):
    email = models.EmailField()
    name = models.CharField(max_length=100)

class Product(models.Model):
    name = models.CharField(max_length=200)
    price = models.DecimalField(max_digits=10, decimal_places=2)

# Task with Django model
class SendWelcomeEmail(Task[None]):
    queue = "emails"

    def __init__(self, user: User, **kwargs):
        super().__init__(**kwargs)
        self.user = user

    async def handle(self) -> None:
        """Django model automatically serialized as reference."""
        print(f"Sending welcome email to {self.user.email}")

class UpdateProductPrice(Task[None]):
    queue = "products"

    def __init__(self, product: Product, new_price: float, **kwargs):
        super().__init__(**kwargs)
        self.product = product
        self.new_price = new_price

    async def handle(self) -> None:
        """Django model with additional parameters."""
        print(f"Updating {self.product.name} to ${self.new_price}")

# Dispatch tasks
async def main():
    # Django async methods (Django 3.1+)
    user = await User.objects.aget(id=1)
    await SendWelcomeEmail(user=user).dispatch()

    product = await Product.objects.aget(id=5)
    await UpdateProductPrice(product=product, new_price=99.99).dispatch()
```

### Tortoise ORM Integration

```python
from tortoise import fields
from tortoise.models import Model
from asynctasq.core.task import Task

# Define Tortoise model
class User(Model):
    id = fields.IntField(pk=True)
    email = fields.CharField(max_length=255)
    name = fields.CharField(max_length=100)

class Post(Model):
    id = fields.IntField(pk=True)
    title = fields.CharField(max_length=200)
    author = fields.ForeignKeyField('models.User', related_name='posts')

# Task with Tortoise model
class NotifyNewPost(Task[None]):
    queue = "notifications"

    def __init__(self, post: Post, author: User, **kwargs):
        super().__init__(**kwargs)
        self.post = post
        self.author = author

    async def handle(self) -> None:
        """Tortoise models automatically serialized as references."""
        print(f"New post '{self.post.title}' by {self.author.name}")

# Dispatch tasks
async def main():
    # Tortoise async methods
    user = await User.get(id=1)
    post = await Post.get(id=10)

    await NotifyNewPost(post=post, author=user).dispatch()
```

---

## Method Chaining

Method chaining allows you to override task configuration at dispatch time. This is useful when you need different settings for specific dispatches without creating separate task classes.

**Available Chain Methods:**

- `.on_queue(queue_name)`: Override the queue name
- `.delay(seconds)`: Add execution delay (in seconds, must be > 0)
- `.retry_after(seconds)`: Override retry delay (in seconds)
- `.dispatch()`: Final method that actually dispatches the task

**Note:** Method chaining methods return `self` for fluent API usage. The order of chaining doesn't matter, but `.dispatch()` must be called last.

**Syntax Pattern:**

```python
await TaskClass(param=value).on_queue("queue").delay(60).dispatch()
#     ^^^^^^^^^^^^^^^^^^^^^^^^  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
#     Instance creation          Chain methods
```

### Basic Method Chaining

```python
from asynctasq.core.task import Task

class ProcessData(Task[None]):
    queue = "default"

    def __init__(self, data: str, **kwargs):
        super().__init__(**kwargs)
        self.data = data

    async def handle(self) -> None:
        print(f"Processing: {self.data}")

# Chain delay and dispatch
async def main():
    # Call constructor, then chain methods
    task_id = await ProcessData(data="data").delay(60).dispatch()
    # Task will execute after 60 seconds
```

### Queue Override with Chaining

```python
from asynctasq.core.task import Task

class SendNotification(Task[None]):
    queue = "default"

    def __init__(self, message: str, **kwargs):
        super().__init__(**kwargs)
        self.message = message

    async def handle(self) -> None:
        print(f"Notification: {self.message}")

# Override queue at dispatch time
async def main():
    # Send to high-priority queue
    task_id = await SendNotification(message="urgent").on_queue("high-priority").dispatch()

    # Send to low-priority queue with delay
    task_id = await SendNotification(message="reminder").on_queue("low-priority").delay(300).dispatch()
```

### Retry Configuration with Chaining

Override the retry delay for specific dispatches:

```python
from asynctasq.core.task import Task

class CallAPI(Task[dict]):
    queue = "api"
    max_retries = 3
    retry_delay = 60

    def __init__(self, endpoint: str, **kwargs):
        super().__init__(**kwargs)
        self.endpoint = endpoint

    async def handle(self) -> dict:
        print(f"Calling {self.endpoint}")
        return {}

# Override retry delay at dispatch time
async def main():
    # Use custom retry delay for this specific dispatch
    # This only affects the delay between retries, not max_retries
    task_id = await CallAPI(endpoint="https://api.example.com/data") \
        .retry_after(120) \
        .dispatch()
    # Will retry with 120 second delays instead of default 60
    # Note: max_retries (3) is still from the class attribute
```

**Important:** Method chaining can only override `queue`, `delay`, and `retry_delay`. The `max_retries` and `timeout` values are set at class definition time and cannot be overridden via chaining. If you need different `max_retries` or `timeout` values, create separate task classes.

### Complex Chaining

```python
from asynctasq.core.task import Task

class ComplexTask(Task[None]):
    queue = "default"

    def __init__(self, data: dict, **kwargs):
        super().__init__(**kwargs)
        self.data = data

    async def handle(self) -> None:
        print(f"Processing: {self.data}")

# Chain multiple configuration methods
async def main():
    task_id = await ComplexTask(data={"key": "value"}) \
        .on_queue("critical") \
        .retry_after(180) \
        .delay(30) \
        .dispatch()
    # Queued on 'critical' queue, 30s delay, 180s retry delay
```

---

## Task Metadata

Tasks automatically track metadata that you can access in your task methods:

- `_task_id`: UUID string for task identification (set during dispatch)
- `_attempts`: Current retry attempt count (0-indexed: 0 = first attempt, 1 = first retry, etc.)
- `_dispatched_at`: Datetime when task was first queued (may be `None` in some edge cases)

**Note:** Metadata is set by the framework during task dispatch and execution. Access these attributes in your `handle()`, `failed()`, or `should_retry()` methods.

### Accessing Metadata

```python
from asynctasq.core.task import Task
from datetime import datetime

class MyTask(Task[None]):
    async def handle(self) -> None:
        print(f"Task ID: {self._task_id}")
        print(f"Attempt: {self._attempts}")  # 0-indexed (0 = first attempt)
        if self._dispatched_at:
            print(f"Dispatched at: {self._dispatched_at}")
        else:
            print("Dispatched at: Unknown")
```

### Using Metadata for Logging

```python
from asynctasq.core.task import Task
import logging

logger = logging.getLogger(__name__)

class LoggedTask(Task[dict]):
    queue = "default"

    async def handle(self) -> dict:
        logger.info(
            f"Task {self._task_id} executing (attempt {self._attempts + 1})",
            extra={
                "task_id": self._task_id,
                "attempt": self._attempts,
                "dispatched_at": self._dispatched_at.isoformat() if self._dispatched_at else None
            }
        )
        return {"status": "completed"}
```

### Using Metadata for Conditional Logic

```python
from asynctasq.core.task import Task

class SmartRetryTask(Task[None]):
    max_retries = 5

    async def handle(self) -> None:
        # Adjust behavior based on attempt count (0-indexed)
        if self._attempts == 0:
            # First attempt (attempt 0) - use fast method
            await self._fast_method()
        elif self._attempts < 3:
            # Retries 1-2 (attempts 1-2) - use standard method
            await self._standard_method()
        else:
            # Retries 3+ (attempts 3+) - use fallback method
            await self._fallback_method()

    async def _fast_method(self):
        pass

    async def _standard_method(self):
        pass

    async def _fallback_method(self):
        pass
```

---

## Real-World Examples

### Email Sending Service

```python
import asyncio
from asynctasq.core.task import Task
from typing import Optional

class SendEmail(Task[dict]):
    queue = "emails"
    max_retries = 5
    retry_delay = 60
    timeout = 30

    def __init__(
        self,
        to: str,
        subject: str,
        body: str,
        from_email: Optional[str] = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.to = to
        self.subject = subject
        self.body = body
        self.from_email = from_email

    async def handle(self) -> dict:
        """Send an email with retry logic."""
        print(f"Sending email to {self.to}: {self.subject}")
        # Email sending logic here
        await asyncio.sleep(0.5)
        return {"status": "sent", "to": self.to}

    async def failed(self, exception: Exception) -> None:
        """Handle email sending failure."""
        print(f"Failed to send email to {self.to}: {exception}")
        # Log to external system, notify admins, etc.

# Dispatch emails
async def main():
    # Immediate email
    await SendEmail(
        to="user@example.com",
        subject="Welcome!",
        body="Welcome to our platform"
    ).dispatch()

    # Delayed welcome email (send after 1 hour)
    await SendEmail(
        to="newuser@example.com",
        subject="Getting Started",
        body="Here's how to get started...",
    ).delay(3600).dispatch()

if __name__ == "__main__":
    asyncio.run(main())
```

### Payment Processing

```python
import asyncio
from asynctasq.core.task import Task
from decimal import Decimal

class ProcessPayment(Task[dict]):
    queue = "payments"
    max_retries = 10
    retry_delay = 30
    timeout = 60

    def __init__(
        self,
        user_id: int,
        amount: Decimal,
        payment_method: str,
        order_id: int,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.user_id = user_id
        self.amount = amount
        self.payment_method = payment_method
        self.order_id = order_id

    async def handle(self) -> dict:
        """Process payment with high retry count for reliability."""
        print(f"Processing payment: ${self.amount} for user {self.user_id}")
        # Payment processing logic
        # - Validate payment method
        # - Charge card
        # - Update order status
        # - Send confirmation
        return {"status": "completed", "order_id": self.order_id}

    def should_retry(self, exception: Exception) -> bool:
        """Don't retry validation errors."""
        if isinstance(exception, ValueError):
            return False
        return True

    async def failed(self, exception: Exception) -> None:
        """Handle payment failure."""
        print(f"Payment failed for order {self.order_id}: {exception}")
        # Refund if already charged, notify user, etc.

# Dispatch payment
async def main():
    task_id = await ProcessPayment(
        user_id=123,
        amount=Decimal("99.99"),
        payment_method="credit_card",
        order_id=456
    ).dispatch()
    print(f"Payment task dispatched: {task_id}")

if __name__ == "__main__":
    asyncio.run(main())
```

### Report Generation

```python
import asyncio
from asynctasq.core.task import SyncTask
from datetime import datetime, timedelta

class GenerateReport(SyncTask[dict]):
    queue = "reports"
    timeout = 3600  # 1 hour timeout

    def __init__(
        self,
        report_type: str,
        start_date: datetime,
        end_date: datetime,
        user_id: int,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.report_type = report_type
        self.start_date = start_date
        self.end_date = end_date
        self.user_id = user_id

    def handle_sync(self) -> dict:
        """Generate report synchronously (CPU-intensive)."""
        import time
        print(f"Generating {self.report_type} report for user {self.user_id}")
        # Heavy computation
        time.sleep(10)
        return {
            "report_type": self.report_type,
            "generated_at": datetime.now().isoformat(),
            "user_id": self.user_id
        }

# Schedule report generation
async def main():
    # Generate report for last month
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)

    task_id = await GenerateReport(
        report_type="monthly_sales",
        start_date=start_date,
        end_date=end_date,
        user_id=123
    ).dispatch()
    print(f"Report generation task dispatched: {task_id}")

if __name__ == "__main__":
    asyncio.run(main())
```

### Image Processing

```python
import asyncio
from asynctasq.core.task import Task
from pathlib import Path

class ProcessImage(Task[dict]):
    queue = "images"
    max_retries = 3
    timeout = 300

    def __init__(
        self,
        image_path: str,
        operations: list[str],
        output_path: str,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.image_path = image_path
        self.operations = operations
        self.output_path = output_path

    async def handle(self) -> dict:
        """Process image with various operations."""
        print(f"Processing image: {self.image_path}")
        # Image processing logic
        # - Resize
        # - Apply filters
        # - Optimize
        # - Save to output_path
        await asyncio.sleep(2)
        return {"output": self.output_path, "operations": self.operations}

# Dispatch image processing
async def main():
    task_id = await ProcessImage(
        image_path="/uploads/photo.jpg",
        operations=["resize", "optimize", "watermark"],
        output_path="/processed/photo.jpg"
    ).dispatch()
    print(f"Image processing task dispatched: {task_id}")

if __name__ == "__main__":
    asyncio.run(main())
```

### Webhook Delivery

```python
import asyncio
from asynctasq.core.task import Task
import httpx

class DeliverWebhook(Task[dict]):
    queue = "webhooks"
    max_retries = 5
    retry_delay = 120
    timeout = 10

    def __init__(
        self,
        url: str,
        payload: dict,
        headers: dict,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.url = url
        self.payload = payload
        self.headers = headers

    async def handle(self) -> dict:
        """Deliver webhook with retry logic."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.url,
                json=self.payload,
                headers=self.headers,
                timeout=10.0
            )
            response.raise_for_status()
            return {"status_code": response.status_code}

    def should_retry(self, exception: Exception) -> bool:
        """Retry on network errors, not client errors."""
        if isinstance(exception, httpx.HTTPStatusError):
            # Don't retry 4xx errors
            if 400 <= exception.response.status_code < 500:
                return False
        return True

# Dispatch webhook
async def main():
    task_id = await DeliverWebhook(
        url="https://example.com/webhook",
        payload={"event": "user.created", "user_id": 123},
        headers={"X-API-Key": "secret"}
    ).dispatch()
    print(f"Webhook task dispatched: {task_id}")

if __name__ == "__main__":
    asyncio.run(main())
```

### Data Synchronization

```python
import asyncio
from asynctasq.core.task import Task

class SyncUserData(Task[dict]):
    queue = "sync"
    max_retries = 3
    retry_delay = 300

    def __init__(
        self,
        user_id: int,
        source_system: str,
        target_system: str,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.user_id = user_id
        self.source_system = source_system
        self.target_system = target_system

    async def handle(self) -> dict:
        """Sync user data between systems."""
        print(f"Syncing user {self.user_id} from {self.source_system} to {self.target_system}")
        # Data synchronization logic
        # - Fetch from source
        # - Transform data
        # - Push to target
        return {"synced": True, "user_id": self.user_id}

# Schedule sync with delay
async def main():
    # Sync after 5 minutes
    task_id = await SyncUserData(
        user_id=123,
        source_system="crm",
        target_system="analytics",
    ).delay(300).dispatch()
    print(f"Sync task dispatched: {task_id}")

if __name__ == "__main__":
    asyncio.run(main())
```

### Batch Processing

Process multiple items in a single task:

```python
import asyncio
from asynctasq.core.task import Task
from typing import List

class ProcessBatch(Task[dict]):
    queue = "batch"
    timeout = 1800  # 30 minutes timeout

    def __init__(
        self,
        items: List[dict],
        batch_id: str,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.items = items
        self.batch_id = batch_id

    async def handle(self) -> dict:
        """Process a batch of items."""
        print(f"Processing batch {self.batch_id} with {len(self.items)} items")
        results = []
        for item in self.items:
            # Process each item
            result = await self._process_item(item)
            results.append(result)
        return {"batch_id": self.batch_id, "processed": len(results)}

    async def _process_item(self, item: dict) -> dict:
        """Helper function to process individual item."""
        await asyncio.sleep(0.1)
        return {"item_id": item.get("id"), "status": "processed"}

# Dispatch batch processing
async def main():
    items = [
        {"id": 1, "data": "value1"},
        {"id": 2, "data": "value2"},
        {"id": 3, "data": "value3"},
    ]

    task_id = await ProcessBatch(
        items=items,
        batch_id="batch-2024-01-15"
    ).dispatch()
    print(f"Batch processing task dispatched: {task_id}")

if __name__ == "__main__":
    asyncio.run(main())
```

**Best Practices for Batch Processing:**

- **Batch size:** Keep batches reasonably sized (typically 10-100 items) to balance throughput and error isolation
- **Large batches:** For very large batches, consider splitting into smaller batches or processing items individually as separate tasks for better parallelism and error isolation
- **Error handling:** If one item in a batch fails, the entire batch task fails. Consider processing items individually for critical operations
- **Timeout:** Set appropriate timeouts for batch tasks based on expected processing time

---

## Complete Working Example

Here's a complete, runnable example demonstrating multiple class-based task patterns. This example shows:

- Different task configurations (queue, retries, timeout)
- Async and sync tasks
- Direct dispatch and method chaining
- Driver overrides
- Delayed execution
- Lifecycle hooks

**Important:** This example uses the `redis` driver. For production, you can also use `postgres`, `mysql`, or `sqs`. Also, remember to run workers to process the dispatched tasks (see [Running Workers](https://github.com/adamrefaey/asynctasq/blob/main/docs/running-workers.md)).

```python
import asyncio
from asynctasq.core.task import Task, SyncTask
from asynctasq.config import set_global_config

# Configure (use 'redis' or 'postgres' for production)
set_global_config(driver='redis')

# Define tasks with different configurations
class SendEmail(Task[str]):
    queue = "emails"
    max_retries = 3
    retry_delay = 60

    def __init__(self, to: str, subject: str, body: str, **kwargs):
        super().__init__(**kwargs)
        self.to = to
        self.subject = subject
        self.body = body

    async def handle(self) -> str:
        """Send an email."""
        print(f"📧 Sending email to {self.to}: {self.subject}")
        await asyncio.sleep(0.1)
        return f"Email sent to {self.to}"

class ProcessPayment(Task[dict]):
    queue = "payments"
    max_retries = 10
    retry_delay = 30
    timeout = 60

    def __init__(self, user_id: int, amount: float, **kwargs):
        super().__init__(**kwargs)
        self.user_id = user_id
        self.amount = amount

    async def handle(self) -> dict:
        """Process a payment."""
        print(f"💳 Processing payment: ${self.amount} for user {self.user_id}")
        await asyncio.sleep(0.2)
        return {"status": "completed", "user_id": self.user_id}

    async def failed(self, exception: Exception) -> None:
        """Handle payment failure."""
        print(f"❌ Payment failed for user {self.user_id}: {exception}")

class GenerateReport(SyncTask[str]):
    queue = "reports"
    timeout = 300

    def __init__(self, report_id: int, **kwargs):
        super().__init__(**kwargs)
        self.report_id = report_id

    def handle_sync(self) -> str:
        """Generate a report (sync function)."""
        import time
        print(f"📊 Generating report {self.report_id}")
        time.sleep(1)
        return f"Report {self.report_id} generated"

class CriticalTask(Task[None]):
    queue = "critical"
    _driver_override = "redis"  # Override driver (requires Redis configured)

    def __init__(self, data: dict, **kwargs):
        super().__init__(**kwargs)
        self.data = data

    async def handle(self) -> None:
        """Critical task using Redis."""
        print(f"🚨 Critical task: {self.data}")
        await asyncio.sleep(0.1)

# Main function demonstrating all dispatch methods
async def main():
    print("=== Class-Based Tasks Examples ===\n")

    # 1. Direct dispatch
    print("1. Direct dispatch:")
    task_id = await SendEmail(
        to="user@example.com",
        subject="Welcome",
        body="Welcome!"
    ).dispatch()
    print(f"   Task ID: {task_id}\n")

    # 2. Dispatch with delay
    print("2. Dispatch with delay:")
    task_id = await SendEmail(
        to="user@example.com",
        subject="Reminder",
        body="Don't forget!",
    ).delay(60).dispatch()
    print(f"   Task ID: {task_id} (will execute in 60s)\n")

    # 3. Method chaining
    print("3. Method chaining:")
    task_id = await SendEmail(
        to="user@example.com",
        subject="Chained",
        body="Message"
    ).delay(30).dispatch()
    print(f"   Task ID: {task_id}\n")

    # 4. Payment processing
    print("4. Payment processing:")
    task_id = await ProcessPayment(user_id=123, amount=99.99).dispatch()
    print(f"   Task ID: {task_id}\n")

    # 5. Sync task
    print("5. Sync task:")
    task_id = await GenerateReport(report_id=1).dispatch()
    print(f"   Task ID: {task_id}\n")

    # 6. Driver override (commented out - requires Redis configuration)
    print("6. Driver override:")
    print("   (Skipped - requires Redis to be configured)")
    # Uncomment to test driver override:
    # task_id = await CriticalTask(data={"key": "value"}).dispatch()
    # print(f"   Task ID: {task_id}\n")

    print("=== All tasks dispatched! ===")
    print("Note: Run workers to process these tasks. See running-workers.md for details.")

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Summary

Class-based tasks in Async TasQ provide a powerful, flexible way to create reusable, testable background tasks with complete control over execution lifecycle.

### Key Features

✅ **Lifecycle hooks** - `handle()`, `failed()`, `should_retry()` for complete control
✅ **Reusable and testable** - Class-based design for better organization
✅ **Flexible configuration** - Queue, retries, timeout, driver via class attributes
✅ **Multiple dispatch methods** - Direct dispatch, delayed execution, method chaining
✅ **Async and sync support** - `Task` for async, `SyncTask` for blocking operations
✅ **ORM integration** - Automatic serialization for SQLAlchemy, Django, Tortoise
✅ **Driver overrides** - Per-task driver selection (string or instance)
✅ **Method chaining** - Fluent API for runtime configuration overrides
✅ **Type safety** - Full type hints and Generic support
✅ **Task metadata** - Access task ID, attempts, dispatched time
✅ **Payload optimization** - ORM models serialized as lightweight references

### Quick Start

1. **Configure your driver:**

   ```python
   from asynctasq.config import set_global_config
   set_global_config(driver='redis')  # or 'postgres', 'mysql', 'sqs'
   ```

2. **Define a task class:**

   ```python
   from asynctasq.core.task import Task

   class SendEmail(Task[bool]):
       queue = "emails"

       def __init__(self, to: str, subject: str, **kwargs):
           super().__init__(**kwargs)
           self.to = to
           self.subject = subject

       async def handle(self) -> bool:
           print(f"Sending email to {self.to}")
           return True
   ```

3. **Dispatch it:**

   ```python
   task_id = await SendEmail(to="user@example.com", subject="Hello").dispatch()
   print(f"Task ID: {task_id}")
   ```

4. **Run workers** to process tasks (see [Running Workers](https://github.com/adamrefaey/asynctasq/blob/main/docs/running-workers.md))

**Important:** Tasks will not execute until a worker process is running. The `dispatch()` call returns immediately after queuing the task - it does not wait for task execution. The returned task ID can be used to track task status in your monitoring system.

### Next Steps

- Learn about [function-based tasks](https://github.com/adamrefaey/asynctasq/blob/main/docs/examples/function-based-tasks.md) for simpler task definitions
- Explore [queue drivers](https://github.com/adamrefaey/asynctasq/blob/main/docs/queue-drivers.md) for production setup
- Check [ORM integrations](https://github.com/adamrefaey/asynctasq/blob/main/docs/orm-integrations.md) for database model support
- Review [best practices](https://github.com/adamrefaey/asynctasq/blob/main/docs/best-practices.md) for production usage

All examples above are ready to use - just configure your driver and start dispatching tasks!

---

## Common Patterns and Best Practices

### Error Handling

Tasks should handle their own errors gracefully. The framework will retry failed tasks according to the `max_retries` configuration and `should_retry()` logic:

```python
from asynctasq.core.task import Task
import httpx

class CallExternalAPI(Task[dict]):
    queue = "api"
    max_retries = 3
    retry_delay = 60

    def __init__(self, url: str, **kwargs):
        super().__init__(**kwargs)
        self.url = url

    async def handle(self) -> dict:
        """Call external API with automatic retry on failure."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(self.url, timeout=10.0)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as e:
            # Log error for debugging
            print(f"API call failed: {e}")
            # Re-raise to trigger retry mechanism
            raise

    def should_retry(self, exception: Exception) -> bool:
        """Retry on network errors, not client errors."""
        if isinstance(exception, httpx.HTTPStatusError):
            if 400 <= exception.response.status_code < 500:
                return False  # Don't retry client errors
        return True  # Retry server errors and network errors
```

### Task ID Tracking

Store task IDs for monitoring and debugging. Task IDs are UUID strings that uniquely identify each dispatched task:

```python
from asynctasq.core.task import Task

class SendWelcomeEmail(Task[None]):
    queue = "emails"

    def __init__(self, user_id: int, **kwargs):
        super().__init__(**kwargs)
        self.user_id = user_id

    async def handle(self) -> None:
        # Email sending logic
        pass

class CreateUserAccount:
    """Service class that dispatches tasks."""

    async def create_user(self, email: str, name: str):
        # Create user in database
        user = await self._create_user(email, name)

        # Dispatch welcome email and store task ID
        email_task_id = await SendWelcomeEmail(user_id=user.id).dispatch()

        # Store task ID in database for tracking
        await self._store_task_reference(user.id, "welcome_email", email_task_id)

        return user
```

### Configuration Best Practices

- **Use descriptive queue names:** `'emails'`, `'payments'`, `'notifications'` instead of `'queue1'`, `'queue2'`
- **Set appropriate timeouts:** Prevent tasks from running indefinitely
- **Configure retries based on task type:** Critical tasks need more retries than validation tasks
- **Use driver overrides sparingly:** Only when necessary for specific requirements
- **Group related tasks:** Use consistent naming and queue organization

### Lifecycle Hook Best Practices

- **Keep `handle()` focused:** Main business logic only, delegate to helper methods
- **Use `failed()` for cleanup:** Compensation, logging, alerting
- **Implement `should_retry()` for smart retries:** Don't retry validation errors, always retry network errors
- **Log in lifecycle hooks:** Use task metadata (`_task_id`, `_attempts`) for better debugging

### Performance Tips

- **Prefer async tasks** (`Task`) for I/O-bound operations
- **Use sync tasks** (`SyncTask`) only when necessary (blocking libraries, CPU-bound work)
- **Keep task payloads small:** For supported ORMs (SQLAlchemy, Django, Tortoise), the framework automatically converts model instances to lightweight references (class + primary key) during serialization, so you don't need to manually extract IDs. Pass model instances directly - the framework handles serialization automatically
- **Batch related operations** when appropriate, but avoid overly large batches
- **Monitor queue sizes** and adjust worker concurrency accordingly
- **Use method chaining** for runtime overrides instead of creating multiple task classes

### Testing Class-Based Tasks

Class-based tasks are easier to test than function-based tasks because you can instantiate them directly and call methods:

```python
import pytest
from asynctasq.core.task import Task

class SendEmail(Task[bool]):
    queue = "emails"

    def __init__(self, to: str, subject: str, **kwargs):
        super().__init__(**kwargs)
        self.to = to
        self.subject = subject

    async def handle(self) -> bool:
        # Email sending logic
        return True

# Test the task directly
@pytest.mark.asyncio
async def test_send_email():
    task = SendEmail(to="test@example.com", subject="Test")
    result = await task.handle()
    assert result is True
    assert task.to == "test@example.com"
    assert task.subject == "Test"

# Test lifecycle hooks
@pytest.mark.asyncio
async def test_send_email_failed():
    task = SendEmail(to="test@example.com", subject="Test")
    # Simulate failure
    await task.failed(ValueError("Email service unavailable"))
    # Verify cleanup logic executed
```

### Organizing Task Classes

- **Group by domain:** `tasks/emails.py`, `tasks/payments.py`, `tasks/notifications.py`
- **Use consistent naming:** `SendEmail`, `ProcessPayment`, `GenerateReport`
- **Document task purpose:** Use docstrings to explain what each task does
- **Share common logic:** Use base classes or mixins for shared functionality

All examples above are ready to use - just configure your driver and start dispatching tasks!
