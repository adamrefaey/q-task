# Async Task

[![Python Version](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A robust, async-first task queue system for Python with multi-driver support (Memory/Redis/PostgreSQL/AWS SQS), inspired by Laravel's elegant queue API.

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
uv add "async-task[all]"        # All drivers

# With ORM support
uv add "async-task[sqlalchemy]" # SQLAlchemy
uv add "async-task[django]"     # Django
uv add "async-task[tortoise]"   # Tortoise ORM
```

### Using pip

```bash
# Basic installation
pip install async-task

# With specific drivers
pip install "async-task[redis]"
pip install "async-task[postgres]"
pip install "async-task[sqs]"
pip install "async-task[all]"
```

---

## Quick Start

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

#### Environment Variables

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

```python
from async_task.config import set_global_config

# Configure from environment with overrides
set_global_config(
    driver='redis',
    redis_url='redis://localhost:6379',
    default_queue='default',
    default_max_retries=3
)
```

### 4. Run Workers

#### Using CLI

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

```python
import asyncio
from async_task.config import Config
from async_task.core.driver_factory import DriverFactory
from async_task.core.worker import Worker

async def main():
    # Create configuration
    config = Config.from_env(driver='redis')

    # Create driver
    driver = DriverFactory.create_from_config(config)

    # Create and start worker
    worker = Worker(
        queue_driver=driver,
        queues=['high-priority', 'default', 'low-priority'],
        concurrency=10
    )

    await worker.start()  # Blocks until shutdown signal

if __name__ == "__main__":
    asyncio.run(main())
```

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

1. Stop accepting new tasks
2. Wait for currently processing tasks to complete
3. Disconnect from driver
4. Exit cleanly

```bash
# Send SIGTERM for graceful shutdown
kill -TERM <worker_pid>

# Or Ctrl+C for SIGINT
```

---

## Configuration Reference

### General Configuration

| Variable                   | Default   | Description                                        |
| -------------------------- | --------- | -------------------------------------------------- |
| `ASYNC_TASK_DRIVER`        | `memory`  | Queue driver: `memory`, `redis`, `postgres`, `sqs` |
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

| Variable                                         | Default                                   | Description                  |
| ------------------------------------------------ | ----------------------------------------- | ---------------------------- |
| `ASYNC_TASK_POSTGRES_DSN`                        | `postgresql://user:pass@localhost/dbname` | PostgreSQL connection string |
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

### Worker Command

Start a worker to process tasks from queues.

```bash
python -m async_task worker [OPTIONS]
```

**Options:**

- `--driver` – Queue driver: `redis`, `postgres`, `sqs`, `memory`
- `--queues` – Comma-separated queue names (priority order)
- `--concurrency` – Max concurrent tasks (default: 10)
- `--redis-url` – Redis connection URL
- `--redis-password` – Redis password
- `--redis-db` – Redis database number
- `--postgres-dsn` – PostgreSQL connection string
- `--sqs-region` – AWS region
- `--sqs-queue-url-prefix` – SQS queue URL prefix

**Examples:**

```bash
# Basic usage
python -m async_task worker

# Multiple queues with priority
python -m async_task worker --queues high,default,low --concurrency 20

# Redis with authentication
python -m async_task worker \
    --driver redis \
    --redis-url redis://localhost:6379 \
    --redis-password secret \
    --redis-db 1

# PostgreSQL
python -m async_task worker \
    --driver postgres \
    --postgres-dsn postgresql://user:pass@localhost/dbname \
    --concurrency 15
```

### Migrate Command

Initialize PostgreSQL database schema.

```bash
python -m async_task migrate [OPTIONS]
```

**Options:**

- `--driver` – Must be `postgres`
- `--postgres-dsn` – PostgreSQL connection string
- `--postgres-queue-table` – Queue table name
- `--postgres-dead-letter-table` – Dead letter table name

**Example:**

```bash
python -m async_task migrate \
    --driver postgres \
    --postgres-dsn postgresql://user:pass@localhost/dbname
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

- **Polling Loop** – Continuously checks queues for tasks
- **Concurrency Control** – Uses asyncio for concurrent task execution
- **Round-Robin** – Processes queues in priority order
- **Graceful Shutdown** – Handles signals for clean shutdown
- **Error Handling** – Automatic retry with configurable backoff
- **Sleep on Empty** – Prevents CPU spinning when queues are empty (0.1s sleep)

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

- Use Redis or PostgreSQL for production (not Memory driver)
- Configure proper retry delays
- Set up monitoring and alerting
- Use environment variables for configuration
- Deploy multiple workers for high availability
- Use process managers (systemd, supervisor, kubernetes)

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

- **Python**: 3.11+
- **Core Dependencies**: pydantic ≥2.12.4, msgpack ≥1.1.0
- **Redis Driver**: redis[hiredis] ≥7.1.0, Redis server 6.2+
- **PostgreSQL Driver**: asyncpg ≥0.30.0, PostgreSQL server 12+
- **SQS Driver**: aioboto3 ≥15.5.0
- **ORMs** (optional): SQLAlchemy ≥2.0.44, Django ≥5.2.8, Tortoise ORM ≥0.25.1

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
