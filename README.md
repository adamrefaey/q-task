# Async Task

[![Python Version](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A robust, async-first task queue system for Python with built-in FastAPI support. Seamlessly switch between Memory, Redis, PostgreSQL, and AWS SQS drivers with a Laravel-inspired API that's both powerful and elegant.

---

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Queue Drivers](#queue-drivers)
- [Advanced Usage](#advanced-usage)
- [Configuration Reference](#configuration-reference)
- [CLI Reference](#cli-reference)
- [Architecture](#architecture)
- [Best Practices](#best-practices)
- [Development](#development)
- [Requirements](#requirements)

---

## Features

### Core Features

- **Async-First Design** – Built from the ground up with asyncio for high-performance concurrent task processing
- **Multiple Queue Drivers** – Seamlessly switch between Memory, Redis, PostgreSQL, and AWS SQS
- **Laravel-Inspired API** – Familiar, elegant API for developers coming from Laravel
- **Type-Safe** – Full type hints with mypy/pyright support
- **ORM Integration** – Automatic serialization/deserialization of SQLAlchemy, Django, and Tortoise ORM models
- **Task Scheduling** – Support for delayed task execution
- **Retry Logic** – Configurable retry attempts with customizable delay
- **Graceful Shutdown** – Workers handle SIGTERM/SIGINT signals for clean shutdown

### Advanced Features

- **FastAPI Integration** – First-class FastAPI support with automatic lifecycle management and dependency injection
- **Function and Class-Based Tasks** – Define tasks as decorated functions or classes
- **Custom Serialization** – Extensible serializer system with msgpack by default
- **Queue Priority** – Process multiple queues with configurable priority
- **Concurrent Processing** – Configure worker concurrency for parallel task execution
- **Dead Letter Queues** – PostgreSQL driver includes automatic DLQ for failed tasks
- **Visibility Timeout** – PostgreSQL driver supports visibility timeout for crash recovery
- **CLI Interface** – Built-in CLI for running workers and migrations

---

## Installation

### Using uv (Recommended)

[uv](https://github.com/astral-sh/uv) is a fast Python package installer and resolver.

```bash
# Basic installation
uv add async-task

# With specific drivers
uv add "async-task[redis]"      # Redis support
uv add "async-task[postgres]"   # PostgreSQL support
uv add "async-task[sqs]"        # AWS SQS support

# With ORM support
uv add "async-task[sqlalchemy]" # SQLAlchemy
uv add "async-task[django]"     # Django
uv add "async-task[tortoise]"   # Tortoise ORM

# With framework integrations
uv add "async-task[fastapi]"    # FastAPI integration

# With all optional dependencies
uv add "async-task[all]"
```

### Using pip

```bash
# Basic installation
pip install async-task

# With specific drivers
pip install "async-task[redis]"      # Redis support
pip install "async-task[postgres]"   # PostgreSQL support
pip install "async-task[sqs]"        # AWS SQS support

# With ORM support
pip install "async-task[sqlalchemy]" # SQLAlchemy
pip install "async-task[django]"     # Django
pip install "async-task[tortoise]"   # Tortoise ORM

# With framework integrations
pip install "async-task[fastapi]"    # FastAPI integration

# With all optional dependencies
pip install "async-task[all]"
```

---

## Quick Start

Get started with Async Task in minutes. Here's a complete example:

```python
import asyncio
from async_task.core.task import task
from async_task.config import set_global_config

# 1. Configure (or use environment variables)
set_global_config(driver='memory')  # Use 'redis' for production

# 2. Define a task
@task(queue='emails')
async def send_email(email: str, subject: str, body: str):
    print(f"Sending email to {email}: {subject}")
    await asyncio.sleep(1)  # Simulate email sending
    return f"Email sent to {email}"

# 3. Dispatch the task
async def main():
    task_id = await send_email.dispatch(
        email="user@example.com",
        subject="Welcome",
        body="Welcome to our platform!"
    )
    print(f"Task dispatched with ID: {task_id}")

# 4. Run a worker to process tasks
# In terminal: python -m async_task worker

if __name__ == "__main__":
    asyncio.run(main())
```

**That's it!** Now let's explore the details:

### 1. Define Tasks

#### Function-Based Tasks

```python
import asyncio
from async_task.core.task import task

# Simple task with default configuration
@task
async def send_email(email: str, subject: str, body: str):
    # Your email sending logic here
    print(f"Sending email to {email}")
    await asyncio.sleep(1)  # Simulate email sending
    print(f"Email sent to {email}")

# Task with custom configuration
@task(queue='emails', max_retries=5, retry_delay=120)
async def send_welcome_email(user_id: int):
    # Your logic here
    pass

# Synchronous tasks (run in thread pool)
@task(queue='reports')
def generate_report(report_id: int):
    # CPU-intensive or blocking I/O work
    import time
    time.sleep(5)
    return f"Report {report_id} generated"
```

#### Class-Based Tasks

```python
import asyncio
from async_task.core.task import Task

class ProcessPayment(Task[bool]):
    queue = "payments"
    max_retries = 3
    retry_delay = 60
    timeout = 30  # Task timeout in seconds

    def __init__(self, user_id: int, amount: float, **kwargs):
        super().__init__(**kwargs)
        self.user_id = user_id
        self.amount = amount

    async def handle(self) -> bool:
        # Your payment processing logic
        print(f"Processing payment: ${self.amount} for user {self.user_id}")
        await asyncio.sleep(2)
        return True

    async def failed(self, exception: Exception) -> None:
        # Called when task fails after all retries
        print(f"Payment failed for user {self.user_id}: {exception}")
        # Send alert, log to monitoring system, etc.

    def should_retry(self, exception: Exception) -> bool:
        # Custom retry logic
        if isinstance(exception, ConnectionError):
            return True
        return False
```

### 2. Dispatch Tasks

```python
# Function-based tasks
# Method 1: Direct dispatch
task_id = await send_email.dispatch(
    email="user@example.com",
    subject="Welcome",
    body="Welcome to our platform!"
)

# Method 2: With delay (in seconds)
task_id = await send_email.dispatch(
    email="user@example.com",
    subject="Welcome",
    body="Welcome!",
    delay=300  # Execute after 5 minutes
)

# Method 3: Configuration chaining
task_id = await send_email(
    email="user@example.com",
    subject="Welcome",
    body="Welcome!"
).delay(300).dispatch()

# Class-based tasks
# Method 1: Immediate dispatch
task_id = await ProcessPayment(user_id=123, amount=99.99).dispatch()

# Method 2: With delay
task_id = await ProcessPayment(user_id=123, amount=99.99).delay(60).dispatch()

# Method 3: Custom queue
task_id = await ProcessPayment(user_id=123, amount=99.99).on_queue("high-priority").dispatch()
```

### 3. Configure the Queue Driver

Configuration can be done via environment variables (recommended for production) or programmatically (useful for development and testing).

#### Environment Variables (Recommended)

```bash
# Driver selection
export ASYNC_TASK_DRIVER=redis  # Options: memory, redis, postgres, sqs

# Redis configuration
export ASYNC_TASK_REDIS_URL=redis://localhost:6379
export ASYNC_TASK_REDIS_PASSWORD=secret
export ASYNC_TASK_REDIS_DB=0

# PostgreSQL configuration
export ASYNC_TASK_POSTGRES_DSN=postgresql://user:pass@localhost/dbname
export ASYNC_TASK_POSTGRES_QUEUE_TABLE=task_queue
export ASYNC_TASK_POSTGRES_DEAD_LETTER_TABLE=dead_letter_queue

# AWS SQS configuration
export ASYNC_TASK_SQS_REGION=us-east-1
export ASYNC_TASK_SQS_QUEUE_PREFIX=https://sqs.us-east-1.amazonaws.com/123456789/
export AWS_ACCESS_KEY_ID=your_access_key
export AWS_SECRET_ACCESS_KEY=your_secret_key
```

#### Programmatic Configuration

You can configure Async Task programmatically using `set_global_config()` or `Config.from_env()`. All configuration options can be passed as keyword arguments, and they override environment variables and defaults.

**Configuration Precedence (highest to lowest):**
1. Keyword arguments to `set_global_config()` or `Config.from_env()`
2. Environment variables
3. Default values

**Using `set_global_config()`:**

```python
from async_task.config import set_global_config

# Basic Redis configuration
set_global_config(
    driver='redis',
    redis_url='redis://localhost:6379',
    default_queue='default',
    default_max_retries=3
)

# PostgreSQL with custom settings
set_global_config(
    driver='postgres',
    postgres_dsn='postgresql://user:pass@localhost:5432/mydb',
    postgres_queue_table='my_queue',
    postgres_max_attempts=5,
    postgres_min_pool_size=5,
    postgres_max_pool_size=20
)

# SQS configuration
set_global_config(
    driver='sqs',
    sqs_region='us-west-2',
    sqs_queue_url_prefix='https://sqs.us-west-2.amazonaws.com/123456789/',
    aws_access_key_id='your_key',
    aws_secret_access_key='your_secret'
)
```

**Using `Config.from_env()`:**

```python
from async_task.config import Config

# Create config with overrides
config = Config.from_env(
    driver='redis',
    redis_url='redis://localhost:6379'
)
```

**Complete Configuration Options:**

All options available for `set_global_config()` and `Config.from_env()`:

**General Options:**
- `driver` (str): Queue driver. Choices: `"redis"`, `"sqs"`, `"memory"`, `"postgres"`
  - Env var: `ASYNC_TASK_DRIVER`
  - Default: `"redis"`
- `default_queue` (str): Default queue name for tasks
  - Env var: `ASYNC_TASK_DEFAULT_QUEUE`
  - Default: `"default"`
- `default_max_retries` (int): Default maximum retry attempts for tasks
  - Env var: `ASYNC_TASK_MAX_RETRIES`
  - Default: `3`
- `default_retry_delay` (int): Default retry delay in seconds
  - Env var: `ASYNC_TASK_RETRY_DELAY`
  - Default: `60`
- `default_timeout` (int | None): Default task timeout in seconds (None = no timeout)
  - Env var: `ASYNC_TASK_TIMEOUT`
  - Default: `None`

**Redis Options:**
- `redis_url` (str): Redis connection URL
  - Env var: `ASYNC_TASK_REDIS_URL`
  - Default: `"redis://localhost:6379"`
- `redis_password` (str | None): Redis password
  - Env var: `ASYNC_TASK_REDIS_PASSWORD`
  - Default: `None`
- `redis_db` (int): Redis database number (0-15)
  - Env var: `ASYNC_TASK_REDIS_DB`
  - Default: `0`
- `redis_max_connections` (int): Maximum number of connections in Redis pool
  - Env var: `ASYNC_TASK_REDIS_MAX_CONNECTIONS`
  - Default: `10`

**PostgreSQL Options:**
- `postgres_dsn` (str): PostgreSQL connection DSN
  - Env var: `ASYNC_TASK_POSTGRES_DSN`
  - Default: `"postgresql://test:test@localhost:5432/test_db"`
- `postgres_queue_table` (str): PostgreSQL queue table name
  - Env var: `ASYNC_TASK_POSTGRES_QUEUE_TABLE`
  - Default: `"task_queue"`
- `postgres_dead_letter_table` (str): PostgreSQL dead letter table name
  - Env var: `ASYNC_TASK_POSTGRES_DEAD_LETTER_TABLE`
  - Default: `"dead_letter_queue"`
- `postgres_max_attempts` (int): Maximum attempts before moving to dead letter queue
  - Env var: `ASYNC_TASK_POSTGRES_MAX_ATTEMPTS`
  - Default: `3`
- `postgres_retry_delay_seconds` (int): Retry delay in seconds for PostgreSQL driver
  - Env var: `ASYNC_TASK_POSTGRES_RETRY_DELAY_SECONDS`
  - Default: `60`
- `postgres_visibility_timeout_seconds` (int): Visibility timeout in seconds
  - Env var: `ASYNC_TASK_POSTGRES_VISIBILITY_TIMEOUT_SECONDS`
  - Default: `300`
- `postgres_min_pool_size` (int): Minimum connection pool size
  - Env var: `ASYNC_TASK_POSTGRES_MIN_POOL_SIZE`
  - Default: `10`
- `postgres_max_pool_size` (int): Maximum connection pool size
  - Env var: `ASYNC_TASK_POSTGRES_MAX_POOL_SIZE`
  - Default: `10`

**SQS Options:**
- `sqs_region` (str): AWS SQS region
  - Env var: `ASYNC_TASK_SQS_REGION`
  - Default: `"us-east-1"`
- `sqs_queue_url_prefix` (str | None): SQS queue URL prefix
  - Env var: `ASYNC_TASK_SQS_QUEUE_PREFIX`
  - Default: `None`
- `aws_access_key_id` (str | None): AWS access key ID
  - Env var: `AWS_ACCESS_KEY_ID`
  - Default: `None` (uses AWS credential chain)
- `aws_secret_access_key` (str | None): AWS secret access key
  - Env var: `AWS_SECRET_ACCESS_KEY`
  - Default: `None` (uses AWS credential chain)

**Examples:**

```python
from async_task.config import set_global_config

# Complete Redis setup
set_global_config(
    driver='redis',
    redis_url='redis://localhost:6379',
    redis_password='secret',
    redis_db=1,
    redis_max_connections=20,
    default_queue='high-priority',
    default_max_retries=5,
    default_retry_delay=120,
    default_timeout=300
)

# Complete PostgreSQL setup
set_global_config(
    driver='postgres',
    postgres_dsn='postgresql://user:pass@localhost:5432/mydb',
    postgres_queue_table='my_task_queue',
    postgres_dead_letter_table='my_dlq',
    postgres_max_attempts=5,
    postgres_retry_delay_seconds=120,
    postgres_visibility_timeout_seconds=600,
    postgres_min_pool_size=5,
    postgres_max_pool_size=25
)

# Complete SQS setup
set_global_config(
    driver='sqs',
    sqs_region='us-west-2',
    sqs_queue_url_prefix='https://sqs.us-west-2.amazonaws.com/123456789/',
    aws_access_key_id='AKIAIOSFODNN7EXAMPLE',
    aws_secret_access_key='wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'
)

# Memory driver (for development/testing)
set_global_config(
    driver='memory',
    default_queue='default',
    default_max_retries=3
)
```

### 4. Run Workers

Workers process tasks from queues. You can run them via CLI (recommended) or programmatically.

#### Using CLI (Recommended)

```bash
# Start worker with default settings
python -m async_task worker

# Or with uv
uv run python -m async_task worker

# Process specific queues (priority order)
python -m async_task worker --queues high-priority,default,low-priority

# Configure concurrency
python -m async_task worker --concurrency 20

# Use specific driver
python -m async_task worker --driver redis --redis-url redis://localhost:6379

# PostgreSQL with custom configuration
python -m async_task worker \
    --driver postgres \
    --postgres-dsn postgresql://user:pass@localhost/dbname \
    --queues default,emails \
    --concurrency 10
```

#### Programmatic Worker

For custom worker implementations or embedding workers in your application:

```python
import asyncio
from async_task.config import Config
from async_task.core.driver_factory import DriverFactory
from async_task.core.worker import Worker

async def main():
    # Create configuration
    config = Config.from_env(driver='redis')

    # Create driver and connect
    driver = DriverFactory.create_from_config(config)
    await driver.connect()

    try:
        # Create and start worker
        worker = Worker(
            queue_driver=driver,
            queues=['high-priority', 'default', 'low-priority'],
            concurrency=10
        )

        await worker.start()  # Blocks until shutdown signal (SIGTERM/SIGINT)
    finally:
        # Cleanup
        await driver.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
```

**Note:** The CLI automatically handles connection management. When using programmatic workers, ensure you connect/disconnect the driver properly.

---

## Queue Drivers

### Memory Driver

Perfect for development, testing, and single-process applications.

```python
from async_task.drivers.memory_driver import MemoryDriver

driver = MemoryDriver()
```

**Features:**

- In-memory storage (no external dependencies)
- Delayed task support
- Fast and simple
- Data lost on process restart

**Use Cases:**

- Local development
- Unit testing
- Single-process applications
- Prototyping

---

### Redis Driver

Production-ready driver with reliable queue pattern.

```python
from async_task.drivers.redis_driver import RedisDriver

driver = RedisDriver(
    url='redis://localhost:6379',
    password='secret',  # Optional
    db=0,
    max_connections=10
)
```

**Features:**

- Reliable Queue Pattern using `LMOVE`
- Delayed tasks using Sorted Sets
- Processing list for crash recovery
- Atomic operations with pipelines
- RESP3 protocol support
- Requires Redis 6.2+

**Architecture:**

- Immediate tasks: Redis List at `queue:{name}`
- Processing tasks: Redis List at `queue:{name}:processing`
- Delayed tasks: Sorted Set at `queue:{name}:delayed`

**Use Cases:**

- Production applications
- Distributed systems
- High-throughput scenarios
- Microservices

---

### PostgreSQL Driver

Enterprise-grade driver with transactional dequeue and dead-letter queue.

```python
from async_task.drivers.postgres_driver import PostgresDriver

driver = PostgresDriver(
    dsn='postgresql://user:pass@localhost/dbname',
    queue_table='task_queue',
    dead_letter_table='dead_letter_queue',
    max_attempts=3,
    retry_delay_seconds=60,
    visibility_timeout_seconds=300,
    min_pool_size=10,
    max_pool_size=10
)
```

**Features:**

- Transactional dequeue using `SELECT ... FOR UPDATE SKIP LOCKED`
- Dead-letter queue for permanently failed tasks
- Visibility timeout for crash recovery
- Connection pooling with asyncpg
- ACID guarantees
- Requires PostgreSQL 12+

**Setup:**

```bash
# Initialize schema
python -m async_task migrate --driver postgres --postgres-dsn postgresql://user:pass@localhost/dbname

# Or with uv
uv run python -m async_task migrate --driver postgres --postgres-dsn postgresql://user:pass@localhost/dbname
```

**Use Cases:**

- Enterprise applications
- Existing PostgreSQL infrastructure
- Need for ACID guarantees
- Complex failure handling

---

### AWS SQS Driver

Cloud-native driver for distributed systems.

```python
from async_task.drivers.sqs_driver import SQSDriver

driver = SQSDriver(
    region_name='us-east-1',
    queue_url_prefix='https://sqs.us-east-1.amazonaws.com/123456789/',
    aws_access_key_id='your_access_key',      # Optional (uses AWS credentials chain)
    aws_secret_access_key='your_secret_key'   # Optional
)
```

**Features:**

- Managed service (no infrastructure)
- Automatic scaling
- Native delayed messages (up to 15 minutes)
- Message visibility timeout
- Dead-letter queue support

**Note:** Queue URLs are constructed as `{queue_url_prefix}{queue_name}`

**Use Cases:**

- AWS-based applications
- Serverless architectures
- Multi-region deployments
- Zero infrastructure management

---

## Advanced Usage

### FastAPI Integration

Async Task provides seamless integration with FastAPI applications through automatic lifecycle management and dependency injection.

#### Basic Usage

```python
from fastapi import FastAPI
from async_task.integrations.fastapi import AsyncTaskIntegration
from async_task.core.task import task

# Auto-configure from environment variables
# ASYNC_TASK_DRIVER=redis
# ASYNC_TASK_REDIS_URL=redis://localhost:6379
async_task = AsyncTaskIntegration()
app = FastAPI(lifespan=async_task.lifespan)

# Define a task
@task(queue='emails')
async def send_email(email: str, message: str):
    # Your email logic here
    return f"Email sent to {email}"

# Use in endpoint
@app.post("/send-email")
async def send_email_route(email: str, message: str):
    task_id = await send_email.dispatch(email=email, message=message)
    return {"task_id": task_id, "status": "queued"}
```

#### Key Features

- **Automatic Lifecycle Management** – Driver connection on startup, graceful disconnection on shutdown
- **Zero-Configuration Mode** – Works with environment variables out of the box
- **Dependency Injection** – Access dispatcher and driver via FastAPI's `Depends()`
- **Works with All Drivers** – Redis, PostgreSQL, SQS, and Memory drivers supported

#### Explicit Configuration

```python
from fastapi import FastAPI
from async_task.integrations.fastapi import AsyncTaskIntegration
from async_task.config import Config

config = Config(
    driver="redis",
    redis_url="redis://localhost:6379"
)
async_task = AsyncTaskIntegration(config=config)
app = FastAPI(lifespan=async_task.lifespan)
```

#### Dependency Injection

```python
from fastapi import Depends, FastAPI
from async_task.integrations.fastapi import AsyncTaskIntegration
from async_task.core.dispatcher import Dispatcher
from async_task.drivers.base_driver import BaseDriver

async_task = AsyncTaskIntegration()
app = FastAPI(lifespan=async_task.lifespan)

@app.post("/dispatch")
async def dispatch_task(
    dispatcher: Dispatcher = Depends(async_task.get_dispatcher)
):
    # Use dispatcher directly
    task_id = await dispatcher.dispatch(my_task)
    return {"task_id": task_id}

@app.get("/queue-stats")
async def get_stats(
    driver: BaseDriver = Depends(async_task.get_driver)
):
    size = await driver.get_queue_size("default")
    return {"queue_size": size}
```

**Important:** FastAPI integration handles task dispatching only. You still need to run workers separately to process tasks:

```bash
# Terminal 1: FastAPI app (dispatch tasks)
uvicorn app:app --host 0.0.0.0 --port 8000

# Terminal 2: Worker (process tasks)
python -m async_task worker \
    --driver redis \
    --redis-url redis://localhost:6379 \
    --queues default,emails \
    --concurrency 10
```

---

### ORM Model Serialization

Async Task automatically handles ORM models in task parameters:

```python
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import DeclarativeBase
from async_task.core.task import task

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    email = Column(String)

@task
async def send_notification(user: User, message: str):
    # User model is automatically serialized as a reference
    # and fetched from DB when the task runs
    print(f"Sending to {user.email}: {message}")

# Dispatch with ORM model
user = await session.get(User, 123)
await send_notification.dispatch(user=user, message="Hello!")
```

**Supported ORMs:**

- SQLAlchemy (async and sync)
- Django ORM (async and sync)
- Tortoise ORM (async)

**How it works:**

1. Models are serialized as lightweight references (class + primary key)
2. During deserialization, models are automatically fetched from the database
3. Reduces queue payload size and ensures fresh data

---

### Custom Task Configuration

```python
from async_task.core.task import Task

class SendEmail(Task[None]):
    queue = "emails"
    max_retries = 5
    retry_delay = 120  # 2 minutes
    timeout = 30       # 30 seconds

    async def handle(self) -> None:
        # Implementation
        pass

    def should_retry(self, exception: Exception) -> bool:
        # Only retry on specific exceptions
        return isinstance(exception, (ConnectionError, TimeoutError))

    async def failed(self, exception: Exception) -> None:
        # Custom failure handling
        await self.log_to_sentry(exception)
        await self.notify_admin(exception)
```

---

### Driver Override per Task

```python
# Task always uses Redis, regardless of global config
@task(queue='critical', driver='redis')
async def critical_task(data: dict):
    pass

# Task uses a custom driver instance
from async_task.drivers.redis_driver import RedisDriver

custom_driver = RedisDriver(url='redis://cache-server:6379')

@task(driver=custom_driver)
async def cache_task(key: str, value: str):
    pass
```

---

### Multiple Workers for Different Queues

```bash
# Worker 1: High-priority queue with high concurrency
python -m async_task worker --queues high-priority --concurrency 20

# Worker 2: Default queue with moderate concurrency
python -m async_task worker --queues default --concurrency 10

# Worker 3: Low-priority and batch jobs with low concurrency
python -m async_task worker --queues low-priority,batch --concurrency 5
```

---

### Graceful Shutdown

Workers handle `SIGTERM` and `SIGINT` signals for graceful shutdown:

1. **Stop accepting new tasks** – No new tasks are dequeued
2. **Wait for completion** – Currently processing tasks finish naturally
3. **Disconnect** – Driver connections are closed cleanly
4. **Exit** – Process terminates gracefully

```bash
# Send SIGTERM for graceful shutdown
kill -TERM <worker_pid>

# Or use Ctrl+C for SIGINT (same behavior)
```

**Best Practice:** Use process managers (systemd, supervisor, Kubernetes) that send SIGTERM for clean shutdowns in production.

---

## Choosing a Driver

| Driver         | Best For                    | Pros                                     | Cons                           |
| -------------- | --------------------------- | ---------------------------------------- | ------------------------------ |
| **Memory**     | Development, testing        | No setup, fast                           | Data lost on restart           |
| **Redis**      | Production, high-throughput | Fast, reliable, distributed              | Requires Redis server          |
| **PostgreSQL** | Enterprise, existing DB     | ACID guarantees, DLQ, visibility timeout | Requires PostgreSQL 12+        |
| **SQS**        | AWS, serverless             | Managed, auto-scaling, zero ops          | AWS-specific, cost per message |

**Recommendation:**

- **Development:** Use `memory` driver
- **Production:** Use `redis` for most cases, `postgres` if you need ACID guarantees
- **AWS/Serverless:** Use `sqs` for managed infrastructure

---

## Configuration Reference

### General Configuration

| Variable                   | Default   | Description                                        |
| -------------------------- | --------- | -------------------------------------------------- |
| `ASYNC_TASK_DRIVER`        | `redis`   | Queue driver: `memory`, `redis`, `postgres`, `sqs` |
| `ASYNC_TASK_DEFAULT_QUEUE` | `default` | Default queue name                                 |
| `ASYNC_TASK_MAX_RETRIES`   | `3`       | Default max retry attempts                         |
| `ASYNC_TASK_RETRY_DELAY`   | `60`      | Default retry delay (seconds)                      |
| `ASYNC_TASK_TIMEOUT`       | `None`    | Default task timeout (seconds)                     |

### Redis Configuration

| Variable                           | Default                  | Description                  |
| ---------------------------------- | ------------------------ | ---------------------------- |
| `ASYNC_TASK_REDIS_URL`             | `redis://localhost:6379` | Redis connection URL         |
| `ASYNC_TASK_REDIS_PASSWORD`        | `None`                   | Redis password               |
| `ASYNC_TASK_REDIS_DB`              | `0`                      | Redis database number (0-15) |
| `ASYNC_TASK_REDIS_MAX_CONNECTIONS` | `10`                     | Redis connection pool size   |

### PostgreSQL Configuration

| Variable                                         | Default                                          | Description                  |
| ------------------------------------------------ | ------------------------------------------------ | ---------------------------- |
| `ASYNC_TASK_POSTGRES_DSN`                        | `postgresql://test:test@localhost:5432/test_db` | PostgreSQL connection string |
| `ASYNC_TASK_POSTGRES_QUEUE_TABLE`                | `task_queue`                              | Queue table name             |
| `ASYNC_TASK_POSTGRES_DEAD_LETTER_TABLE`          | `dead_letter_queue`                       | Dead letter table name       |
| `ASYNC_TASK_POSTGRES_MAX_ATTEMPTS`               | `3`                                       | Max attempts before DLQ      |
| `ASYNC_TASK_POSTGRES_RETRY_DELAY_SECONDS`        | `60`                                      | Retry delay (seconds)        |
| `ASYNC_TASK_POSTGRES_VISIBILITY_TIMEOUT_SECONDS` | `300`                                     | Visibility timeout (seconds) |
| `ASYNC_TASK_POSTGRES_MIN_POOL_SIZE`              | `10`                                      | Min connection pool size     |
| `ASYNC_TASK_POSTGRES_MAX_POOL_SIZE`              | `10`                                      | Max connection pool size     |

### AWS SQS Configuration

| Variable                      | Default     | Description                                          |
| ----------------------------- | ----------- | ---------------------------------------------------- |
| `ASYNC_TASK_SQS_REGION`       | `us-east-1` | AWS region                                           |
| `ASYNC_TASK_SQS_QUEUE_PREFIX` | `None`      | SQS queue URL prefix                                 |
| `AWS_ACCESS_KEY_ID`           | `None`      | AWS access key (optional, uses AWS credential chain) |
| `AWS_SECRET_ACCESS_KEY`       | `None`      | AWS secret key (optional, uses AWS credential chain) |

---

## CLI Reference

The Async Task CLI provides commands for managing task queues and workers. All configuration options can be set via environment variables or CLI arguments, with CLI arguments taking precedence.

### Worker Command

Start a worker to process tasks from queues.

```bash
python -m async_task worker [OPTIONS]
```

**General Options:**

- `--driver DRIVER` – Queue driver to use. Choices: `redis`, `sqs`, `memory`, `postgres`
  - Default: from `ASYNC_TASK_DRIVER` env var or `redis`
- `--queues QUEUES` – Comma-separated list of queue names to process in priority order (first queue has highest priority)
  - Default: `default`
- `--concurrency N` – Maximum number of concurrent tasks to process
  - Default: `10`

**Redis Options:**

- `--redis-url URL` – Redis connection URL
  - Default: from `ASYNC_TASK_REDIS_URL` env var or `redis://localhost:6379`
- `--redis-password PASSWORD` – Redis password
  - Default: from `ASYNC_TASK_REDIS_PASSWORD` env var
- `--redis-db N` – Redis database number (0-15)
  - Default: from `ASYNC_TASK_REDIS_DB` env var or `0`
- `--redis-max-connections N` – Redis max connections in pool
  - Default: from `ASYNC_TASK_REDIS_MAX_CONNECTIONS` env var or `10`

**PostgreSQL Options:**

- `--postgres-dsn DSN` – PostgreSQL connection DSN
  - Default: from `ASYNC_TASK_POSTGRES_DSN` env var or `postgresql://test:test@localhost:5432/test_db`
- `--postgres-queue-table TABLE` – PostgreSQL queue table name
  - Default: from `ASYNC_TASK_POSTGRES_QUEUE_TABLE` env var or `task_queue`
- `--postgres-dead-letter-table TABLE` – PostgreSQL dead letter table name
  - Default: from `ASYNC_TASK_POSTGRES_DEAD_LETTER_TABLE` env var or `dead_letter_queue`

**SQS Options:**

- `--sqs-region REGION` – AWS SQS region
  - Default: from `ASYNC_TASK_SQS_REGION` env var or `us-east-1`
- `--sqs-queue-url-prefix PREFIX` – SQS queue URL prefix
  - Default: from `ASYNC_TASK_SQS_QUEUE_PREFIX` env var
- `--aws-access-key-id KEY` – AWS access key ID
  - Default: from `AWS_ACCESS_KEY_ID` env var
- `--aws-secret-access-key SECRET` – AWS secret access key
  - Default: from `AWS_SECRET_ACCESS_KEY` env var

**Examples:**

```bash
# Basic usage with default settings
python -m async_task worker

# Multiple queues with priority order
python -m async_task worker --queues high,default,low --concurrency 20

# Redis with authentication
python -m async_task worker \
    --driver redis \
    --redis-url redis://localhost:6379 \
    --redis-password secret \
    --redis-db 1

# PostgreSQL with custom configuration
python -m async_task worker \
    --driver postgres \
    --postgres-dsn postgresql://user:pass@localhost/dbname \
    --postgres-queue-table my_queue \
    --queues default,emails \
    --concurrency 15

# SQS with custom region
python -m async_task worker \
    --driver sqs \
    --sqs-region us-west-2 \
    --sqs-queue-url-prefix https://sqs.us-west-2.amazonaws.com/123456789/ \
    --queues default \
    --concurrency 10

# Memory driver (for development/testing)
python -m async_task worker --driver memory --queues default --concurrency 5
```

### Migrate Command

Initialize database schema for PostgreSQL driver. This command creates the necessary tables and indexes in PostgreSQL for the task queue system. It only works with the PostgreSQL driver.

```bash
python -m async_task migrate [OPTIONS]
```

**Options:**

- `--driver DRIVER` – Queue driver (must be `postgres` for migrate command)
  - Default: `postgres` (automatically set for migrate command)
- `--postgres-dsn DSN` – PostgreSQL connection DSN
  - Default: from `ASYNC_TASK_POSTGRES_DSN` env var or `postgresql://test:test@localhost:5432/test_db`
- `--postgres-queue-table TABLE` – PostgreSQL queue table name
  - Default: from `ASYNC_TASK_POSTGRES_QUEUE_TABLE` env var or `task_queue`
- `--postgres-dead-letter-table TABLE` – PostgreSQL dead letter table name
  - Default: from `ASYNC_TASK_POSTGRES_DEAD_LETTER_TABLE` env var or `dead_letter_queue`

**Examples:**

```bash
# Basic migration with default settings (driver defaults to postgres)
python -m async_task migrate

# Migration with custom DSN
python -m async_task migrate \
    --postgres-dsn postgresql://user:pass@localhost:5432/mydb

# Migration with custom table names
python -m async_task migrate \
    --postgres-dsn postgresql://user:pass@localhost:5432/mydb \
    --postgres-queue-table my_task_queue \
    --postgres-dead-letter-table my_dlq

# Using environment variables
export ASYNC_TASK_POSTGRES_DSN=postgresql://user:pass@localhost:5432/mydb
python -m async_task migrate
```

**What it does:**

The migrate command creates:

- Queue table (`task_queue` by default) with columns for task storage
- Lookup index (`idx_{queue_table}_lookup`) for efficient task retrieval
- Dead letter table (`dead_letter_queue` by default) for failed tasks

### Environment Variables

All configuration options can be set via environment variables. CLI arguments take precedence over environment variables.

**General:**

- `ASYNC_TASK_DRIVER` – Queue driver (`memory`, `redis`, `postgres`, `sqs`)
- `ASYNC_TASK_DEFAULT_QUEUE` – Default queue name

**Redis:**

- `ASYNC_TASK_REDIS_URL` – Redis connection URL
- `ASYNC_TASK_REDIS_PASSWORD` – Redis password
- `ASYNC_TASK_REDIS_DB` – Redis database number
- `ASYNC_TASK_REDIS_MAX_CONNECTIONS` – Redis max connections

**PostgreSQL:**

- `ASYNC_TASK_POSTGRES_DSN` – PostgreSQL connection DSN
- `ASYNC_TASK_POSTGRES_QUEUE_TABLE` – Queue table name
- `ASYNC_TASK_POSTGRES_DEAD_LETTER_TABLE` – Dead letter table name

**SQS:**

- `ASYNC_TASK_SQS_REGION` – AWS region
- `ASYNC_TASK_SQS_QUEUE_PREFIX` – SQS queue URL prefix
- `AWS_ACCESS_KEY_ID` – AWS access key ID
- `AWS_SECRET_ACCESS_KEY` – AWS secret access key

### Exit Codes

- `0` – Success
- `1` – Error (command failed, migration error, etc.)

### Getting Help

For help on any command, use the `--help` flag:

```bash
# General help
python -m async_task --help

# Command-specific help
python -m async_task worker --help
python -m async_task migrate --help
```

---

## Architecture

### Task Lifecycle

```text
1. Definition   → Task defined as function or class
2. Dispatch     → Task serialized and enqueued to driver
3. Storage      → Driver stores task in queue backend
4. Dequeue      → Worker fetches task from queue
5. Execution    → Worker deserializes and executes task
6. Completion   → Task succeeds or retries on failure
7. Cleanup      → Task removed from queue or moved to DLQ
```

### Task Serialization

Tasks are serialized using msgpack with custom type handling:

- **Supported types**: `str`, `int`, `float`, `bool`, `bytes`, `list`, `dict`, `None`
- **Custom types**: `datetime`, `date`, `Decimal`, `UUID`, `set`
- **ORM models**: SQLAlchemy, Django, Tortoise (auto-serialized as references)
- **Binary data**: Efficient msgpack binary encoding

### Worker Architecture

- **Polling Loop** – Continuously checks queues for tasks with configurable intervals
- **Concurrency Control** – Uses asyncio for concurrent task execution (configurable per worker)
- **Round-Robin** – Processes queues in priority order (first queue in list has highest priority)
- **Graceful Shutdown** – Handles SIGTERM/SIGINT signals for clean shutdown
- **Error Handling** – Automatic retry with configurable backoff and custom retry logic
- **Sleep on Empty** – Prevents CPU spinning when queues are empty (0.1s default sleep)
- **Task Isolation** – Each task runs in its own context, failures don't affect other tasks

---

## Common Patterns

### Task with Database Session

```python
from async_task.core.task import Task
from sqlalchemy.ext.asyncio import AsyncSession

class ProcessOrder(Task[None]):
    async def handle(self) -> None:
        # Create a new database session for the task
        async with get_async_session() as session:
            order = await session.get(Order, self.order_id)
            # Process order...
            await session.commit()
```

### Task with Retry Logic

```python
from async_task.core.task import Task

class SendNotification(Task[None]):
    max_retries = 5
    retry_delay = 30

    def should_retry(self, exception: Exception) -> bool:
        # Only retry on network errors, not validation errors
        return isinstance(exception, (ConnectionError, TimeoutError))

    async def failed(self, exception: Exception) -> None:
        # Log to monitoring system
        logger.error(f"Notification failed after {self.max_retries} retries", exc_info=exception)
```

### Chained Task Configuration

```python
# Configure task at dispatch time
task_id = await send_email(
    email="user@example.com",
    subject="Welcome"
).on_queue("high-priority").delay(300).dispatch()
```

---

## Best Practices

### 1. Task Design

✅ **Do:**

- Keep tasks small and focused
- Make tasks idempotent when possible
- Use timeouts for long-running tasks
- Implement custom `failed()` handlers for cleanup
- Use `should_retry()` for intelligent retry logic

❌ **Don't:**

- Include blocking I/O in async tasks (use sync tasks instead)
- Share mutable state between tasks
- Perform network calls without timeouts

### 2. Queue Organization

✅ **Do:**

- Use separate queues for different priorities
- Isolate slow tasks in dedicated queues
- Group related tasks by queue
- Consider worker capacity when designing queues

### 3. Error Handling

✅ **Do:**

- Log errors comprehensively in `failed()` method
- Use retry limits to prevent infinite loops
- Monitor dead-letter queues
- Implement alerting for critical failures

### 4. Performance

✅ **Do:**

- Tune worker concurrency based on task characteristics
- Use connection pooling for database drivers
- Monitor queue sizes and adjust worker count
- Consider task batching for high-volume operations

### 5. Production Deployment

✅ **Do:**

- **Use Redis or PostgreSQL** for production (Memory driver loses data on restart)
- **Configure proper retry delays** to avoid overwhelming systems during outages
- **Set up monitoring and alerting** for queue sizes, worker health, and failed tasks
- **Use environment variables** for configuration (never hardcode credentials)
- **Deploy multiple workers** for high availability and load distribution
- **Use process managers** (systemd, supervisor, Kubernetes) for automatic restarts
- **Monitor dead-letter queues** to catch permanently failed tasks
- **Set appropriate timeouts** to prevent tasks from hanging indefinitely
- **Use connection pooling** for database drivers (configured automatically)

---

## Development

### Setup Development Environment

```bash
# Clone repository
git clone https://github.com/adamrefaey/async-task.git
cd async-task

# Install uv if you haven't already
curl -LsSf https://astral.sh/uv/install.sh | sh

# Sync dependencies
uv sync

# Install pre-commit hooks
uv run pre-commit install
```

### Running Tests

```bash
# Run all tests
uv run pytest

# Run unit tests only
uv run pytest -m unit

# Run integration tests only
uv run pytest -m integration

# Run with coverage
uv run pytest --cov=async_task --cov-branch --cov-report=term-missing --cov-report=html
```

Or use the provided justfile:

```bash
# Run all tests
just test

# Run unit tests
just test-unit

# Run integration tests (requires Docker)
just test-integration

# Run with coverage
just test-cov
```

### Code Quality

```bash
# Format code
uv run ruff format .

# Lint code
uv run ruff check .

# Type checking
uv run pyright
```

### Docker Services for Integration Tests

```bash
# Start services (Redis, PostgreSQL, LocalStack for SQS)
just docker-up

# Run integration tests
just test-integration

# Stop services
just docker-down
```

---

## Requirements

### Core Requirements

- **Python**: 3.11 or higher
- **Core Dependencies**:
  - `pydantic` ≥2.12.4
  - `msgpack` ≥1.1.0

### Driver Requirements

- **Redis Driver**:

  - `redis[hiredis]` ≥7.1.0
  - Redis server 6.2+ (for `LMOVE` support)

- **PostgreSQL Driver**:

  - `asyncpg` ≥0.30.0
  - PostgreSQL server 12+ (for `SKIP LOCKED` support)

- **SQS Driver**:
  - `aioboto3` ≥15.5.0
  - AWS account with SQS access

### Optional Dependencies

- **ORMs**:

  - SQLAlchemy ≥2.0.44
  - Django ≥5.2.8
  - Tortoise ORM ≥0.25.1

- **Framework Integrations**:
  - FastAPI ≥0.115.0

---

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## License

MIT License – see [LICENSE](LICENSE) file for details.

---

## Credits

Inspired by [Laravel's queue system](https://laravel.com/docs/queues). Built with ❤️ by [Adam Refaey](https://github.com/adamrefaey).

---

## Support

- **Issues**: [GitHub Issues](https://github.com/adamrefaey/async-task/issues)
- **Discussions**: [GitHub Discussions](https://github.com/adamrefaey/async-task/discussions)

---

## Roadmap

- [ ] MySQL driver support
- [ ] SQLite driver support
- [ ] Oracle driver support
- [ ] Task batching support
- [ ] Task chaining and workflows
- [ ] Rate limiting
- [ ] Task priority within queues
- [ ] Web UI for monitoring
- [ ] Prometheus metrics exporter
- [ ] Additional ORM support
