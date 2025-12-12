# Function-Based Tasks: Complete Examples Guide

This guide provides concrete, ready-to-use code examples demonstrating all scenarios, options, and capabilities of function-based tasks in AsyncTasQ.

Function-based tasks allow you to convert any Python function (async or sync) into a background task by simply adding the `@task` decorator. Tasks are automatically serialized, queued, and executed by workers.

## Four Execution Modes

The `@task` decorator provides **all 4 execution modes** through a combination of function type and the `process` parameter:

| Mode | Function Type | `process=` | Execution | Best For |
|------|---------------|-----------|-----------|----------|
| **AsyncTask** | `async def` | `False` (default) | Event loop | Async I/O-bound (API calls, async DB queries) |
| **SyncTask** | `def` | `False` (default) | Thread pool | Sync/blocking I/O (`requests`, sync DB drivers) |
| **AsyncProcessTask** | `async def` | `True` | Process pool (async) | Async CPU-intensive work |
| **SyncProcessTask** | `def` | `True` | Process pool (sync) | Sync CPU-intensive work (>80% CPU) |

**Examples:**

```python
from asynctasq.tasks import task

# Mode 1: AsyncTask (async I/O-bound) - DEFAULT for async functions
@task
async def fetch_data(url: str):
    async with httpx.AsyncClient() as client:
        return await client.get(url)

# Mode 2: SyncTask (sync I/O-bound) - DEFAULT for sync functions
@task
def fetch_web_page(url: str):
    import requests
    return requests.get(url).text

# Mode 3: AsyncProcessTask (async CPU-intensive)
@task(process=True)
async def process_video_async(path: str):
    async with aiofiles.open(path, 'rb') as f:
        data = await f.read()
    # CPU-intensive processing
    return process_frames(data)

# Mode 4: SyncProcessTask (sync CPU-intensive)
@task(process=True)
def heavy_computation(data: list[float]):
    import numpy as np
    return np.fft.fft(data)  # CPU-intensive
```

**Key Features:**

- **Simple decorator syntax** - Just add `@task` to any function
- **Automatic execution routing** - Framework selects appropriate executor based on function type and `process` flag
- **Full mode coverage** - Access to all 4 execution modes (same as class-based tasks)
- **Flexible configuration** - Queue, retries, timeout, driver, process via decorator or method chaining
- **Method chaining** - Override configuration at dispatch time with fluent API
- **ORM model serialization** - Automatic lightweight references for SQLAlchemy, Django, Tortoise
- **Type-safe** - Full type hints and Generic support
- **Multiple dispatch methods** - Direct dispatch, delayed execution, or method chaining

---

## Table of Contents

- [Basic Usage](#basic-usage)
- [Decorator Syntax](#decorator-syntax)
- [Configuration Options](#configuration-options)
- [Dispatching Tasks](#dispatching-tasks)
- [Async vs Sync Functions](#async-vs-sync-functions)
- [Driver Overrides](#driver-overrides)
- [ORM Integration](#orm-integration)
- [Method Chaining](#method-chaining)
- [Real-World Examples](#real-world-examples)
- [Complete Working Example](#complete-working-example)
- [Common Patterns and Best Practices](#common-patterns-and-best-practices)

---

## Basic Usage

### Simple AsyncTasQ

The simplest way to create a task is to add the `@task` decorator to an async function:

```python
import asyncio
from asynctasq.tasks import task
from asynctasq.config import set_global_config

# Configure the queue driver
# Note: Use 'redis', 'postgres', 'mysql', or 'sqs' for production
set_global_config(driver='redis')

# Define a simple task
@task
async def send_notification(message: str):
    """Send a notification message."""
    print(f"Notification: {message}")
    await asyncio.sleep(0.1)  # Simulate async work
    return f"Sent: {message}"

# Dispatch the task
async def main():
    task_id = await send_notification.dispatch(message="Hello, World!")
    print(f"Task dispatched with ID: {task_id}")
    # Note: Task will be executed by a worker process

if __name__ == "__main__":
    asyncio.run(main())
```

**Important:** After dispatching tasks, you must run a worker process to execute them. See [Running Workers](https://github.com/adamrefaey/asynctasq/blob/main/docs/running-workers.md) for details.

### Simple Sync Task

Synchronous functions are automatically executed in a thread pool, so you can use blocking operations without converting to async:

```python
from asynctasq.tasks import task
from asynctasq.config import set_global_config

set_global_config(driver='redis')

# Synchronous function (automatically runs in thread pool)
@task
def process_data(data: list[int]) -> int:
    """Process data synchronously."""
    import time
    time.sleep(1)  # Blocking operation is OK in sync tasks
    return sum(data)

# Dispatch
async def main():
    task_id = await process_data.dispatch(data=[1, 2, 3, 4, 5])
    print(f"Task dispatched: {task_id}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

**Note:** For CPU-intensive work (>80% CPU utilization), add `process=True` to run in process pool:

```python
@task(process=True)  # Runs in ProcessPoolExecutor
def heavy_computation(data: list[float]):
    import numpy as np
    return np.fft.fft(data)  # CPU-intensive work
```

---

## Decorator Syntax

### Without Parentheses (Default Configuration)

```python
from asynctasq.tasks import task

@task  # Uses all defaults: queue='default', max_retries=3, etc.
async def simple_task():
    """Task with default configuration."""
    print("Executing simple task")
```

### With Parentheses (Custom Configuration)

```python
from asynctasq.tasks import task

@task(queue='emails', max_retries=5, retry_delay=120, timeout=30)
async def send_email(to: str, subject: str, body: str):
    """Send an email with custom retry configuration."""
    print(f"Sending email to {to}: {subject}")
    # Email sending logic here
```

---

## Configuration Options

All configuration options can be set via the `@task` decorator. These settings apply to all dispatches of the task unless overridden at dispatch time using method chaining.

**Available Options:**

| Option        | Type                        | Default     | Description                                                      |
| ------------- | --------------------------- | ----------- | ---------------------------------------------------------------- |
| `queue`       | `str`                       | `"default"` | Queue name for task execution                                    |
| `max_retries` | `int`                       | `3`         | Maximum retry attempts on failure                                |
| `retry_delay` | `int`                       | `60`        | Seconds to wait between retry attempts                           |
| `timeout`     | `int \| None`               | `None`      | Task timeout in seconds (`None` = no timeout)                    |
| `driver`      | `str \| BaseDriver \| None` | `None`      | Driver override (string or instance, `None` = use global config) |
| `process`     | `bool`                      | `False`     | Use process pool for CPU-intensive work (`True` = process pool, `False` = event loop/thread pool) |

### Queue Configuration

Use different queues to organize tasks by priority, type, or processing requirements:

```python
from asynctasq.tasks import task

# Different queues for different task types
@task(queue='emails')
async def send_email(to: str, subject: str):
    """Email tasks go to 'emails' queue."""
    pass

@task(queue='payments')
async def process_payment(amount: float, user_id: int):
    """Payment tasks go to 'payments' queue."""
    pass

@task(queue='notifications')
async def send_push_notification(user_id: int, message: str):
    """Notification tasks go to 'notifications' queue."""
    pass
```

**Tips:**

- Run separate workers for different queues to control resource allocation and priority
- Use descriptive queue names that indicate the task type or priority level
- Consider queue naming conventions: `high-priority`, `low-priority`, `critical`, `background`

### Retry Configuration

```python
from asynctasq.tasks import task

# High retry count for critical operations
@task(queue='payments', max_retries=10, retry_delay=30)
async def charge_credit_card(card_id: str, amount: float):
    """Retry up to 10 times with 30 second delays."""
    # Payment processing logic
    pass

# No retries for validation tasks
@task(queue='validation', max_retries=0)
async def validate_data(data: dict):
    """Don't retry validation failures."""
    # Validation logic
    pass

# Custom retry delay
@task(queue='api-calls', max_retries=5, retry_delay=300)
async def call_external_api(endpoint: str):
    """Retry with 5 minute delays (for rate-limited APIs)."""
    # API call logic
    pass
```

### Timeout Configuration

```python
from asynctasq.tasks import task

# Short timeout for quick operations
@task(queue='quick', timeout=5)
async def quick_operation():
    """Task must complete within 5 seconds."""
    # Fast operation
    pass

# Long timeout for heavy operations
@task(queue='reports', timeout=3600)
async def generate_report(report_id: int):
    """Task can take up to 1 hour."""
    # Report generation logic
    pass

# No timeout (default)
@task(queue='background', timeout=None)
async def background_cleanup():
    """No timeout limit."""
    # Cleanup logic
    pass
```

### Combined Configuration

```python
from asynctasq.tasks import task

@task(
    queue='critical',
    max_retries=10,
    retry_delay=60,
    timeout=300
)
async def critical_operation(data: dict):
    """Fully configured critical task."""
    # Critical operation logic
    pass
```

### Process Pool Configuration

Use `process=True` for CPU-intensive work that requires true multiprocessing (bypasses GIL):

```python
from asynctasq.tasks import task

# Async CPU-intensive work
@task(queue='ml-inference', process=True, timeout=300)
async def run_ml_inference(model_path: str, data: list[float]):
    """Async + process=True - runs in subprocess with async support."""
    import aiofiles
    
    # Async I/O
    async with aiofiles.open(model_path, 'rb') as f:
        model_data = await f.read()
    
    # CPU-intensive work (bypasses GIL)
    return run_model(model_data, data)

# Sync CPU-intensive work
@task(queue='data-processing', process=True, timeout=600)
def process_large_dataset(data: list[float]):
    """Sync + process=True - runs in subprocess."""
    import numpy as np
    
    # Heavy CPU computation (bypasses GIL)
    arr = np.array(data)
    result = np.fft.fft(arr)
    
    return {
        "mean": float(result.mean()),
        "std": float(result.std())
    }
```

**When to use `process=True`:**

✅ CPU utilization > 80% (verified with profiling)  
✅ Task duration > 100ms (amortizes process overhead)  
✅ All arguments and return values are serializable (msgpack-compatible)  
✅ Heavy computation: NumPy, Pandas, ML inference, video encoding, encryption  

❌ Don't use for I/O-bound tasks (use default `process=False`)  
❌ Don't use for short tasks < 100ms (overhead not worth it)  
❌ Don't use with unserializable objects (lambdas, file handles, sockets)

---

## Dispatching Tasks

Tasks are dispatched using the `.dispatch()` method on the decorated function. The method accepts all function parameters plus an optional `delay` parameter.

**Return Value:** `dispatch()` returns a unique task ID (UUID string) that can be used for tracking, monitoring, and debugging.

**Important Notes:**

- Tasks are dispatched asynchronously and return immediately
- The task ID is generated before the task is queued
- Tasks will not execute until a worker process is running
- Use the task ID to track task status in your monitoring system

### Direct Dispatch (Recommended)

The simplest way to dispatch a task is to call `.dispatch()` with the function's parameters:

```python
from asynctasq.tasks import task

@task(queue='emails')
async def send_email(to: str, subject: str, body: str):
    print(f"Sending email to {to}")

# Dispatch immediately
async def main():
    task_id = await send_email.dispatch(
        to="user@example.com",
        subject="Welcome",
        body="Welcome to our platform!"
    )
    print(f"Task ID: {task_id}")
```

### Dispatch with Delay

You can delay task execution using either the `delay` parameter or method chaining:

```python
from asynctasq.tasks import task

@task(queue='reminders')
async def send_reminder(user_id: int, message: str):
    print(f"Sending reminder to user {user_id}: {message}")

# Dispatch with 60 second delay
async def main():
    # Method 1: Using delay parameter (recommended for simple delays)
    task_id = await send_reminder.dispatch(
        user_id=123,
        message="Don't forget to complete your profile!",
        delay=60  # Execute after 60 seconds
    )

    # Method 2: Using method chaining (useful when combining with other overrides)
    task_id = await send_reminder(user_id=123, message="Reminder").delay(60).dispatch()
```

**Note:** The `delay` parameter specifies seconds until execution. For more complex scheduling, consider using a separate scheduling system.

### Dispatch with Positional Arguments

```python
from asynctasq.tasks import task

@task
async def process_items(item1: str, item2: str, item3: str):
    print(f"Processing: {item1}, {item2}, {item3}")

# Dispatch with positional arguments
async def main():
    task_id = await process_items.dispatch("apple", "banana", "cherry")
```

### Dispatch with Mixed Arguments

```python
from asynctasq.tasks import task

@task
async def update_user(user_id: int, name: str, email: str, active: bool = True):
    print(f"Updating user {user_id}: {name} ({email}), active={active}")

# Dispatch with mixed positional and keyword arguments
async def main():
    task_id = await update_user.dispatch(
        123,  # positional
        "John Doe",  # positional
        email="john@example.com",  # keyword
        active=False  # keyword
    )
```

---

## Async vs Sync Functions

The `@task` decorator provides **all 4 execution modes** through a combination of function type and the `process` parameter:

### Execution Mode Selection

```python
# Async + process=False (default) → AsyncTask (event loop)
@task
async def io_async(): ...

# Sync + process=False (default) → SyncTask (thread pool)
@task
def io_sync(): ...

# Async + process=True → AsyncProcessTask (process pool with async)
@task(process=True)
async def cpu_async(): ...

# Sync + process=True → SyncProcessTask (process pool)
@task(process=True)
def cpu_sync(): ...
```

### Mode Comparison Table

| Mode | Function Type | `process=` | Execution | Best For | Concurrency |
|------|--------------|-----------|-----------|----------|-------------|
| **AsyncTask** | `async def` | `False` (default) | Event loop | Async I/O-bound (API calls, async DB queries) | 1000s concurrent |
| **SyncTask** | `def` | `False` (default) | Thread pool | Sync/blocking I/O (`requests`, sync DB drivers) | 100s concurrent |
| **AsyncProcessTask** | `async def` | `True` | Process pool (async) | Async CPU-intensive work | CPU cores |
| **SyncProcessTask** | `def` | `True` | Process pool (sync) | Sync CPU-intensive work (>80% CPU) | CPU cores |

**When to use each:**

| Use Case | Function Type | `process=` | Reason |
|----------|--------------|-----------|--------|
| API calls with httpx, aiohttp | `async def` | `False` | Native async support, non-blocking |
| Database queries with asyncpg | `async def` | `False` | Better performance for I/O-bound |
| Web scraping with `requests` | `def` | `False` | Blocking library, runs in thread pool |
| File I/O with blocking libraries | `def` | `False` | No async conversion needed |
| NumPy/Pandas computation | `def` | `True` | CPU-intensive, bypasses GIL |
| ML inference, video encoding | `def` or `async def` | `True` | Heavy CPU work in subprocess |
| ML inference with async I/O | `async def` | `True` | Async preprocessing + CPU work |

### Mode 1: AsyncTask (Default for async functions)

Use async functions for async I/O-bound operations (API calls, async database queries, async file operations):

```python
from asynctasq.tasks import task
import httpx

@task(queue='api')  # process=False is default
async def fetch_user_data(user_id: int):
    """Async function - runs in event loop via AsyncTask."""
    # Can use await for async I/O
    async with httpx.AsyncClient() as client:
        response = await client.get(f"https://api.example.com/users/{user_id}")
        return response.json()
```

**Benefits:**

- Best performance for I/O-bound operations
- Can use `await` for async libraries (httpx, aiohttp, asyncpg, aiofiles)
- More efficient resource usage (no thread overhead)
- Higher concurrency (1000s of tasks)

### Mode 2: SyncTask (Default for sync functions)

Use sync functions for sync/blocking I/O operations:

```python
from asynctasq.tasks import task
import requests

@task(queue='web-scraping')  # process=False is default
def fetch_web_page(url: str) -> str:
    """Sync function - automatically runs in thread pool via SyncTask."""
    # Blocking operations OK - runs in thread pool
    response = requests.get(url)
    return response.text
```

**Benefits:**

- No need to convert blocking code to async
- Automatic thread pool execution (managed by framework)
- Works with any synchronous library (`requests`, `psycopg2`, etc.)

### Mode 3: AsyncProcessTask (Async + `process=True`)

Use async functions with `process=True` for CPU-intensive work that also needs async I/O:

```python
from asynctasq.tasks import task
import aiofiles

@task(queue='video-processing', process=True)  # AsyncProcessTask
async def process_video_async(video_path: str) -> dict:
    """Async + process=True - runs in subprocess with asyncio.run()."""
    # Async I/O
    async with aiofiles.open(video_path, 'rb') as f:
        data = await f.read()
    
    # CPU-intensive work (bypasses GIL in subprocess)
    frames_processed = await process_frames(data)
    
    return {"frames": frames_processed}
```

**Benefits:**

- True multi-core parallelism (bypasses GIL)
- Async I/O support within subprocess
- Best for ML inference with async preprocessing

**Important:** All arguments and return values must be serializable (msgpack-compatible).

### Mode 4: SyncProcessTask (Sync + `process=True`)

Use sync functions with `process=True` for heavy CPU-intensive work:

```python
from asynctasq.tasks import task
import numpy as np

@task(queue='data-processing', process=True, timeout=600)  # SyncProcessTask
def process_large_dataset(data: list[float]) -> dict:
    """Sync + process=True - runs in subprocess via ProcessPoolExecutor."""
    # Heavy CPU computation (bypasses GIL)
    arr = np.array(data)
    result = np.fft.fft(arr)
    
    return {
        "mean": float(result.mean()),
        "std": float(result.std())
    }
```

**Benefits:**

- True multi-core parallelism (bypasses GIL)
- Best performance for CPU-intensive workloads (>80% CPU)
- Each process has independent interpreter and memory

**Limitations:**

- All arguments and return values must be serializable (no lambdas, file handles, sockets)
- Higher memory footprint (~50MB+ per process)
- Higher startup overhead (~50ms per task)

### Choosing the Right Mode

**Decision Flow:**

1. **Is your work CPU-intensive (>80% CPU)?**
   - Yes → Use `process=True` (Mode 3 or 4)
   - No → Use `process=False` (Mode 1 or 2)

2. **Do you need async I/O?**
   - Yes → Use `async def` (Mode 1 or 3)
   - No → Use `def` (Mode 2 or 4)

**Examples:**

```python
from asynctasq.tasks import task

# ✅ Mode 1: Async I/O-bound (default)
@task
async def fetch_data(url: str):
    async with httpx.AsyncClient() as client:
        return await client.get(url)

# ✅ Mode 2: Sync I/O-bound (default)
@task
def scrape_page(url: str):
    import requests
    return requests.get(url).text

# ✅ Mode 3: Async CPU-intensive
@task(process=True)
async def ml_inference_async(data: list[float]):
    # Async preprocessing
    async with aiofiles.open('model.pkl', 'rb') as f:
        model_data = await f.read()
    # CPU-intensive work
    return run_model(model_data, data)

# ✅ Mode 4: Sync CPU-intensive
@task(process=True)
def heavy_math(matrix: list[list[float]]):
    import numpy as np
    return np.linalg.inv(np.array(matrix)).tolist()
```

### Mixed Async/Sync in Same Application

```python
from asynctasq.tasks import task
import asyncio
import time

# Async task
@task(queue='asynctasqs')
async def async_operation(data: str):
    await asyncio.sleep(0.1)
    return f"Processed: {data}"

# Sync task
@task(queue='sync-tasks')
def sync_operation(data: str):
    time.sleep(1)
    return f"Computed: {data}"

# Both can be dispatched the same way
async def main():
    task1_id = await async_operation.dispatch(data="async")
    task2_id = await sync_operation.dispatch(data="sync")
```

---

## Driver Overrides

### Per-Task Driver Override (String)

```python
from asynctasq.tasks import task
from asynctasq.config import set_global_config

# Global config uses redis driver
set_global_config(driver='redis')

# This task uses Redis regardless of global config
@task(queue='critical', driver='redis')
async def critical_task(data: dict):
    """Always uses Redis driver."""
    print(f"Processing critical task: {data}")

# This task uses SQS
@task(queue='aws-tasks', driver='sqs')
async def aws_task(region: str):
    """Always uses SQS driver."""
    print(f"Processing AWS task in {region}")

# This task uses global config (redis)
@task(queue='normal')
async def normal_task(data: str):
    """Uses global config driver."""
    print(f"Processing normal task: {data}")
```

### Per-Task Driver Override (Driver Instance)

You can also pass a driver instance directly for complete control over driver configuration:

```python
from asynctasq.tasks import task
from asynctasq.drivers.redis_driver import RedisDriver

# Create a custom driver instance with specific configuration
custom_redis = RedisDriver(
    url='redis://custom-host:6379',
    password='secret',
    db=1,
    max_connections=20
)

# Use the custom driver instance
@task(queue='custom', driver=custom_redis)
async def custom_driver_task(data: dict):
    """Uses the custom Redis driver instance."""
    print(f"Using custom driver: {data}")

# Dispatch task
async def main():
    task_id = await custom_driver_task.dispatch(data={"key": "value"})
    print(f"Task dispatched: {task_id}")
```

**Important Notes:**

- When using a driver instance, the driver is shared across all tasks using it
- For per-task isolation, use string-based driver selection instead
- Driver instances are cached and reused, so creating multiple instances with the same configuration is inefficient
- Ensure driver instances are properly initialized before task dispatch

### Multiple Drivers in Same Application

```python
from asynctasq.tasks import task
from asynctasq.config import set_global_config

# Default driver
set_global_config(driver='redis')

# Tasks using different drivers
@task(queue='redis-queue', driver='redis')
async def redis_task(data: str):
    pass

@task(queue='postgres-queue', driver='postgres')
async def postgres_task(data: str):
    pass

@task(queue='sqs-queue', driver='sqs')
async def sqs_task(data: str):
    pass

@task(queue='default-queue')  # Uses global config (redis)
async def redis_task(data: str):
    pass
```

---

## ORM Integration

### SQLAlchemy Integration

**Important:** SQLAlchemy models are automatically detected and serialized as lightweight references. Only the primary key is stored in the queue, and models are fetched fresh from the database when the task executes.

**Configuration:** Set a context variable on your model class to provide the session for fetching models during task execution.

```python
import contextvars
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from asynctasq.tasks import task

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
@task(queue='emails')
async def send_welcome_email(user: User):
    """User is automatically serialized as reference and fetched fresh."""
    print(f"Sending welcome email to {user.email} (ID: {user.id})")
    # User data is fresh from database when task executes

@task(queue='orders')
async def process_order(order: Order, user: User):
    """Multiple ORM models supported."""
    print(f"Processing order {order.id} for user {user.name}")
    # Both models are fetched fresh in parallel

# Dispatch tasks
async def main():
    async with async_session() as session:
        # Set session in context for task execution
        session_var.set(session)

        # Fetch user
        user = await session.get(User, 1)

        # Only user.id is serialized to queue (90%+ payload reduction)
        task_id = await send_welcome_email.dispatch(user=user)

        # Multiple models
        order = await session.get(Order, 100)
        task_id = await process_order.dispatch(order=order, user=user)
```

**Important Notes:**

- For production, ensure the session context variable is set in your worker process
- Models are fetched fresh from the database when the task executes, ensuring data consistency
- Only the primary key is serialized, reducing queue payload size by 90%+ for large models
- Multiple models in the same task are fetched in parallel for efficiency
- See [ORM Integrations](https://github.com/adamrefaey/asynctasq/blob/main/docs/orm-integrations.md) for complete setup instructions and worker configuration

### Django ORM Integration

```python
from django.db import models
from asynctasq.tasks import task

# Define Django model
class User(models.Model):
    email = models.EmailField()
    name = models.CharField(max_length=100)

class Product(models.Model):
    name = models.CharField(max_length=200)
    price = models.DecimalField(max_digits=10, decimal_places=2)

# Task with Django model
@task(queue='emails')
async def send_welcome_email(user: User):
    """Django model automatically serialized as reference."""
    print(f"Sending welcome email to {user.email}")

@task(queue='products')
async def update_product_price(product: Product, new_price: float):
    """Django model with additional parameters."""
    print(f"Updating {product.name} to ${new_price}")

# Dispatch tasks
async def main():
    # Django async methods (Django 3.1+)
    user = await User.objects.aget(id=1)
    await send_welcome_email.dispatch(user=user)

    product = await Product.objects.aget(id=5)
    await update_product_price.dispatch(product=product, new_price=99.99)
```

### Tortoise ORM Integration

```python
from tortoise import fields
from tortoise.models import Model
from asynctasq.tasks import task

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
@task(queue='notifications')
async def notify_new_post(post: Post, author: User):
    """Tortoise models automatically serialized as references."""
    print(f"New post '{post.title}' by {author.name}")

# Dispatch tasks
async def main():
    # Tortoise async methods
    user = await User.get(id=1)
    post = await Post.get(id=10)

    await notify_new_post.dispatch(post=post, author=user)
```

---

## Method Chaining

Method chaining allows you to override task configuration at dispatch time. This is useful when you need different settings for specific dispatches without creating separate task functions.

**Available Chain Methods:**

- `.on_queue(queue_name)`: Override the queue name
- `.delay(seconds)`: Add execution delay (in seconds)
- `.retry_after(seconds)`: Override retry delay (in seconds)
- `.dispatch()`: Final method that actually dispatches the task

**Important:** Method chaining requires calling the function first (with arguments) to create a task instance, then chaining configuration methods. The function call returns a task instance that supports chaining.

**Syntax Pattern:**

```python
await task_function(arg1, arg2).on_queue("queue").delay(60).dispatch()
#      ^^^^^^^^^^^^^^^^^^^^^^^^  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
#      Function call (creates instance)  Chain methods
```

### Basic Method Chaining

```python
from asynctasq.tasks import task

@task(queue='default')
async def process_data(data: str):
    print(f"Processing: {data}")

# Chain delay and dispatch
async def main():
    # Call function with args, then chain methods
    task_id = await process_data("data").delay(60).dispatch()
    # Task will execute after 60 seconds
```

### Queue Override with Chaining

```python
from asynctasq.tasks import task

@task(queue='default')
async def send_notification(message: str):
    print(f"Notification: {message}")

# Override queue at dispatch time
async def main():
    # Send to high-priority queue
    task_id = await send_notification("urgent").on_queue("high-priority").dispatch()

    # Send to low-priority queue with delay
    task_id = await send_notification("reminder").on_queue("low-priority").delay(300).dispatch()
```

### Retry Configuration with Chaining

Override the retry delay for specific dispatches:

```python
from asynctasq.tasks import task

@task(queue='api', max_retries=3, retry_delay=60)
async def call_api(endpoint: str):
    print(f"Calling {endpoint}")

# Override retry delay at dispatch time
async def main():
    # Use custom retry delay for this specific dispatch
    # This only affects the delay between retries, not max_retries
    task_id = await call_api("https://api.example.com/data") \
        .retry_after(120) \
        .dispatch()
    # Will retry with 120 second delays instead of default 60
    # Note: max_retries (3) is still from the decorator
```

**Note:** Method chaining can only override `queue`, `delay`, and `retry_delay`. The `max_retries` and `timeout` values are set at decoration time and cannot be overridden via chaining.

### Complex Chaining

```python
from asynctasq.tasks import task

@task(queue='default')
async def complex_task(data: dict):
    print(f"Processing: {data}")

# Chain multiple configuration methods
async def main():
    task_id = await complex_task({"key": "value"}) \
        .on_queue("critical") \
        .retry_after(180) \
        .delay(30) \
        .dispatch()
    # Queued on 'critical' queue, 30s delay, 180s retry delay
```

---

## Real-World Examples

### Email Sending Service

```python
import asyncio
from asynctasq.tasks import task
from typing import Optional

@task(queue='emails', max_retries=5, retry_delay=60, timeout=30)
async def send_email(
    to: str,
    subject: str,
    body: str,
    from_email: Optional[str] = None
):
    """Send an email with retry logic."""
    # Email sending logic here
    print(f"Sending email to {to}: {subject}")
    # Simulate email sending
    await asyncio.sleep(0.5)
    return {"status": "sent", "to": to}

# Dispatch emails
async def main():
    # Immediate email
    await send_email.dispatch(
        to="user@example.com",
        subject="Welcome!",
        body="Welcome to our platform"
    )

    # Delayed welcome email (send after 1 hour)
    await send_email.dispatch(
        to="newuser@example.com",
        subject="Getting Started",
        body="Here's how to get started...",
        delay=3600
    )

if __name__ == "__main__":
    asyncio.run(main())
```

### Payment Processing

```python
import asyncio
from asynctasq.tasks import task
from decimal import Decimal

@task(
    queue='payments',
    max_retries=10,
    retry_delay=30,
    timeout=60
)
async def process_payment(
    user_id: int,
    amount: Decimal,
    payment_method: str,
    order_id: int
):
    """Process payment with high retry count for reliability."""
    print(f"Processing payment: ${amount} for user {user_id}")
    # Payment processing logic
    # - Validate payment method
    # - Charge card
    # - Update order status
    # - Send confirmation
    return {"status": "completed", "order_id": order_id}

# Dispatch payment
async def main():
    task_id = await process_payment.dispatch(
        user_id=123,
        amount=Decimal("99.99"),
        payment_method="credit_card",
        order_id=456
    )
    print(f"Payment task dispatched: {task_id}")

if __name__ == "__main__":
    asyncio.run(main())
```

### Report Generation

```python
import asyncio
from asynctasq.tasks import task
from datetime import datetime, timedelta

@task(queue='reports', timeout=3600)  # 1 hour timeout
def generate_report(
    report_type: str,
    start_date: datetime,
    end_date: datetime,
    user_id: int
):
    """Generate report synchronously (CPU-intensive)."""
    import time
    print(f"Generating {report_type} report for user {user_id}")
    # Heavy computation
    time.sleep(10)
    return {
        "report_type": report_type,
        "generated_at": datetime.now().isoformat(),
        "user_id": user_id
    }

# Schedule report generation
async def main():
    # Generate report for last month
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)

    task_id = await generate_report.dispatch(
        report_type="monthly_sales",
        start_date=start_date,
        end_date=end_date,
        user_id=123
    )
    print(f"Report generation task dispatched: {task_id}")

if __name__ == "__main__":
    asyncio.run(main())
```

### Image Processing

```python
import asyncio
from asynctasq.tasks import task
from pathlib import Path

@task(queue='images', max_retries=3, timeout=300)
async def process_image(
    image_path: str,
    operations: list[str],
    output_path: str
):
    """Process image with various operations."""
    print(f"Processing image: {image_path}")
    # Image processing logic
    # - Resize
    # - Apply filters
    # - Optimize
    # - Save to output_path
    await asyncio.sleep(2)
    return {"output": output_path, "operations": operations}

# Dispatch image processing
async def main():
    task_id = await process_image.dispatch(
        image_path="/uploads/photo.jpg",
        operations=["resize", "optimize", "watermark"],
        output_path="/processed/photo.jpg"
    )
    print(f"Image processing task dispatched: {task_id}")

if __name__ == "__main__":
    asyncio.run(main())
```

### Webhook Delivery

```python
import asyncio
from asynctasq.tasks import task
import httpx

@task(
    queue='webhooks',
    max_retries=5,
    retry_delay=120,
    timeout=10
)
async def deliver_webhook(
    url: str,
    payload: dict,
    headers: dict
):
    """Deliver webhook with retry logic."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            json=payload,
            headers=headers,
            timeout=10.0
        )
        response.raise_for_status()
        return {"status_code": response.status_code}

# Dispatch webhook
async def main():
    task_id = await deliver_webhook.dispatch(
        url="https://example.com/webhook",
        payload={"event": "user.created", "user_id": 123},
        headers={"X-API-Key": "secret"}
    )
    print(f"Webhook task dispatched: {task_id}")

if __name__ == "__main__":
    asyncio.run(main())
```

### Data Synchronization

```python
import asyncio
from asynctasq.tasks import task

@task(queue='sync', max_retries=3, retry_delay=300)
async def sync_user_data(
    user_id: int,
    source_system: str,
    target_system: str
):
    """Sync user data between systems."""
    print(f"Syncing user {user_id} from {source_system} to {target_system}")
    # Data synchronization logic
    # - Fetch from source
    # - Transform data
    # - Push to target
    return {"synced": True, "user_id": user_id}

# Schedule sync with delay
async def main():
    # Sync after 5 minutes
    task_id = await sync_user_data.dispatch(
        user_id=123,
        source_system="crm",
        target_system="analytics",
        delay=300
    )
    print(f"Sync task dispatched: {task_id}")

if __name__ == "__main__":
    asyncio.run(main())
```

### Batch Processing

Process multiple items in a single task:

```python
import asyncio
from asynctasq.tasks import task
from typing import List

@task(queue='batch', timeout=1800)  # 30 minutes timeout
async def process_batch(
    items: List[dict],
    batch_id: str
):
    """Process a batch of items."""
    print(f"Processing batch {batch_id} with {len(items)} items")
    results = []
    for item in items:
        # Process each item
        result = await process_item(item)
        results.append(result)
    return {"batch_id": batch_id, "processed": len(results)}

async def process_item(item: dict):
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

    task_id = await process_batch.dispatch(
        items=items,
        batch_id="batch-2024-01-15"
    )
    print(f"Batch processing task dispatched: {task_id}")

if __name__ == "__main__":
    asyncio.run(main())
```

**Tip:** For very large batches, consider splitting into smaller batches or processing items individually as separate tasks for better parallelism and error isolation.

---

## Complete Working Example

Here's a complete, runnable example demonstrating multiple function-based task patterns. This example shows:

- Different task configurations (queue, retries, timeout)
- Async and sync functions
- Direct dispatch and method chaining
- Driver overrides
- Delayed execution

**Important:** This example uses the `redis` driver. For production, you can also use `postgres`, `mysql`, or `sqs`. Also, remember to run workers to process the dispatched tasks (see [Running Workers](https://github.com/adamrefaey/asynctasq/blob/main/docs/running-workers.md)).

```python
import asyncio
from asynctasq.tasks import task
from asynctasq.config import set_global_config

# Configure (use 'redis' or 'postgres' for production)
set_global_config(driver='redis')

# Define tasks with different configurations
@task(queue='emails', max_retries=3, retry_delay=60)
async def send_email(to: str, subject: str, body: str):
    """Send an email."""
    print(f"📧 Sending email to {to}: {subject}")
    await asyncio.sleep(0.1)
    return f"Email sent to {to}"

@task(queue='payments', max_retries=10, retry_delay=30, timeout=60)
async def process_payment(user_id: int, amount: float):
    """Process a payment."""
    print(f"💳 Processing payment: ${amount} for user {user_id}")
    await asyncio.sleep(0.2)
    return {"status": "completed", "user_id": user_id}

@task(queue='reports', timeout=300)
def generate_report(report_id: int):
    """Generate a report (sync function)."""
    import time
    print(f"📊 Generating report {report_id}")
    time.sleep(1)
    return f"Report {report_id} generated"

@task(driver='redis')  # Override driver (requires Redis configured)
async def critical_task(data: dict):
    """Critical task using Redis."""
    print(f"🚨 Critical task: {data}")
    await asyncio.sleep(0.1)

# Main function demonstrating all dispatch methods
async def main():
    print("=== Function-Based Tasks Examples ===\n")

    # 1. Direct dispatch
    print("1. Direct dispatch:")
    task_id = await send_email.dispatch(
        to="user@example.com",
        subject="Welcome",
        body="Welcome!"
    )
    print(f"   Task ID: {task_id}\n")

    # 2. Dispatch with delay
    print("2. Dispatch with delay:")
    task_id = await send_email.dispatch(
        to="user@example.com",
        subject="Reminder",
        body="Don't forget!",
        delay=60
    )
    print(f"   Task ID: {task_id} (will execute in 60s)\n")

    # 3. Method chaining
    print("3. Method chaining:")
    task_id = await send_email("user@example.com", "Chained", "Message") \
        .delay(30) \
        .dispatch()
    print(f"   Task ID: {task_id}\n")

    # 4. Payment processing
    print("4. Payment processing:")
    task_id = await process_payment.dispatch(user_id=123, amount=99.99)
    print(f"   Task ID: {task_id}\n")

    # 5. Sync task
    print("5. Sync task:")
    task_id = await generate_report.dispatch(report_id=1)
    print(f"   Task ID: {task_id}\n")

    # 6. Driver override
    print("6. Driver override:")
    # Note: This requires Redis to be configured
    # task_id = await critical_task.dispatch(data={"key": "value"})
    # print(f"   Task ID: {task_id}\n")

    print("=== All tasks dispatched! ===")
    print("Note: Run workers to process these tasks. See running-workers.md for details.")

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Summary

Function-based tasks in AsyncTasQ provide a simple, powerful way to convert any Python function into a background task.

### Key Features

✅ **Simple syntax** - Just add `@task` decorator to any function
✅ **Flexible configuration** - Queue, retries, timeout, driver via decorator
✅ **Multiple dispatch methods** - Direct dispatch, delayed execution, method chaining
✅ **Async and sync support** - Automatic thread pool for sync functions
✅ **ORM integration** - Automatic serialization for SQLAlchemy, Django, Tortoise
✅ **Driver overrides** - Per-task driver selection (string or instance)
✅ **Method chaining** - Fluent API for runtime configuration overrides
✅ **Type safety** - Full type hints and Generic support
✅ **Payload optimization** - ORM models serialized as lightweight references

### Quick Start

1. **Configure your driver:**

   ```python
   from asynctasq.config import set_global_config
   set_global_config(driver='redis')  # or 'postgres', 'mysql', 'sqs'
   ```

2. **Define a task:**

   ```python
   from asynctasq.tasks import task

   @task(queue='emails')
   async def send_email(to: str, subject: str):
       print(f"Sending email to {to}")
   ```

3. **Dispatch it:**

   ```python
   task_id = await send_email.dispatch(to="user@example.com", subject="Hello")
   print(f"Task ID: {task_id}")
   ```

4. **Run workers** to process tasks (see [Running Workers](https://github.com/adamrefaey/asynctasq/blob/main/docs/running-workers.md))

**Note:** Tasks will not execute until a worker process is running. The `dispatch()` call returns immediately after queuing the task.

### Next Steps

- Learn about [task definitions](https://github.com/adamrefaey/asynctasq/blob/main/docs/task-definitions.md) for class-based tasks
- Explore [queue drivers](https://github.com/adamrefaey/asynctasq/blob/main/docs/queue-drivers.md) for production setup
- Check [ORM integrations](https://github.com/adamrefaey/asynctasq/blob/main/docs/orm-integrations.md) for database model support
- Review [best practices](https://github.com/adamrefaey/asynctasq/blob/main/docs/best-practices.md) for production usage

All examples above are ready to use - just configure your driver and start dispatching tasks!

---

## Common Patterns and Best Practices

### Error Handling

Tasks should handle their own errors gracefully. The framework will retry failed tasks according to the `max_retries` configuration:

```python
@task(queue='api', max_retries=3, retry_delay=60)
async def call_external_api(url: str):
    """Call external API with automatic retry on failure."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10.0)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        # Log error for debugging
        print(f"API call failed: {e}")
        # Re-raise to trigger retry mechanism
        raise
```

### Task ID Tracking

Store task IDs for monitoring and debugging:

```python
async def create_user_account(email: str, name: str):
    # Create user in database
    user = await create_user(email, name)

    # Dispatch welcome email and store task ID
    email_task_id = await send_welcome_email.dispatch(user=user)

    # Store task ID in database for tracking
    await store_task_reference(user.id, "welcome_email", email_task_id)

    return user
```

### Configuration Best Practices

- **Use descriptive queue names:** `'emails'`, `'payments'`, `'notifications'` instead of `'queue1'`, `'queue2'`
- **Set appropriate timeouts:** Prevent tasks from running indefinitely
- **Configure retries based on task type:** Critical tasks need more retries than validation tasks
- **Use driver overrides sparingly:** Only when necessary for specific requirements

### Performance Tips

- **Prefer async functions** for I/O-bound operations
- **Use sync functions** only when necessary (blocking libraries, CPU-bound work)
- **Keep task payloads small:** For supported ORMs (SQLAlchemy, Django, Tortoise), the framework automatically converts model instances to lightweight references (class + primary key) during serialization, so you don't need to manually extract IDs
- **Batch related operations** when appropriate, but avoid overly large batches
- **Monitor queue sizes** and adjust worker concurrency accordingly
