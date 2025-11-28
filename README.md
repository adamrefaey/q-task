# Async Task

[![Tests](.github/tests.svg)](https://github.com/adamrefaey/async-task/actions/workflows/ci.yml)
[![Coverage](.github/coverage.svg)](.github/coverage.svg)
[![Python Version](.github/python-version.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A modern, async-first, type-safe task queue Python package inspired by Laravel. Native FastAPI integration. Switch between multiple queue backends (Redis, PostgreSQL, MySQL, RabbitMQ, AWS SQS) with one config line. Automatic ORM serialization (SQLAlchemy, Django, Tortoise) using msgpack reduces payloads by 90%+. Features ACID guarantees, dead-letter queues, crash recovery.

---

## Table of Contents

- [Async Task](#async-task)
  - [Table of Contents](#table-of-contents)
  - [Why Async Task?](#why-async-task)
    - [Async-First Architecture](#async-first-architecture)
    - [High-Performance Serialization](#high-performance-serialization)
    - [Production-Ready Features](#production-ready-features)
    - [Developer Experience](#developer-experience)
    - [Multi-Driver Flexibility](#multi-driver-flexibility)
  - [Key Features](#key-features)
    - [Core Capabilities](#core-capabilities)
    - [Enterprise Features](#enterprise-features)
    - [Integrations](#integrations)
    - [Developer Tools](#developer-tools)
  - [Quick Start](#quick-start)
  - [Quick Reference](#quick-reference)
  - [CI \& Contributing (short)](#ci--contributing-short)
  - [Comparison with Alternatives](#comparison-with-alternatives)
    - [Async Task vs. Celery](#async-task-vs-celery)
    - [Async Task vs. Dramatiq](#async-task-vs-dramatiq)
    - [Async Task vs. RQ (Redis Queue)](#async-task-vs-rq-redis-queue)
    - [Async Task vs. Huey](#async-task-vs-huey)
    - [Key Differentiators](#key-differentiators)
  - [Documentation](#documentation)
  - [Examples](#examples)
  - [Contributing](#contributing)
  - [License](#license)
  - [Support](#support)
  - [Roadmap](#roadmap)
  - [Credits](#credits)

---

## Why Async Task?

### Async-First Architecture

- **Built with asyncio from the ground up** – No threading, no blocking operations on critical paths
- **Native async/await support** – Seamless integration with modern Python async code
- **High concurrency** – Process thousands of tasks concurrently with minimal resource usage
- **Efficient I/O** – Connection pooling for all database drivers

### High-Performance Serialization

- **msgpack encoding** – Binary serialization that's faster and more compact than JSON
- **Efficient binary handling** – Native `use_bin_type=True` for optimal bytes processing
- **Automatic ORM model handling** – Pass SQLAlchemy, Django, or Tortoise models directly as task parameters. They're automatically serialized as lightweight references (PK only), reducing payload size by 90%+, then re-fetched with fresh data when the task executes
- **Custom type support** – Native handling of datetime, Decimal, UUID, sets without manual conversion

### Production-Ready Features

- **Enterprise ACID guarantees** – PostgreSQL/MySQL drivers with transactional dequeue
- **Dead-letter queues** – Automatic handling of permanently failed tasks
- **Crash recovery** – Visibility timeouts ensure tasks are never lost
- **Graceful shutdown** – SIGTERM/SIGINT handlers wait for in-flight tasks to complete
- **Configurable retries** – Per-task retry logic with custom `should_retry()` hooks
- **Task timeouts** – Prevent runaway tasks with per-task timeout configuration

### Developer Experience

- **Elegant, intuitive API** – Clean, expressive syntax inspired by Laravel's queue system
- **Type-safe** – Full type hints with mypy/pyright support, Generic Task[T] for return types
- **Zero configuration** – Works with environment variables out of the box
- **Multiple task styles** – Function-based decorators or class-based tasks with lifecycle hooks
- **Method chaining** – Fluent API for task configuration: `.delay(60).on_queue("high").dispatch()`
- **First-class FastAPI integration** – Automatic lifecycle management and dependency injection

### Multi-Driver Flexibility

- **Switch drivers instantly** – Change one config line to swap between Redis, PostgreSQL, MySQL, RabbitMQ, or AWS SQS
- **Same API everywhere** – Write once, run on any driver without code changes
- **Per-task driver override** – Different tasks can use different drivers in the same application
- **Production-ready options** – From Redis to enterprise databases to managed cloud queues

---

## Key Features

### Core Capabilities

✅ **Async-first design** with asyncio throughout the stack

✅ **Multiple queue drivers**: Redis, PostgreSQL, MySQL, RabbitMQ, AWS SQS

✅ **High-performance msgpack serialization** with binary support

✅ **Automatic ORM model handling** for SQLAlchemy, Django, Tortoise

✅ **Type-safe** with full type hints and Generic support

✅ **Configurable retries** with custom retry logic hooks

✅ **Task timeouts** to prevent runaway tasks

✅ **Delayed task execution** with precision timing

✅ **Queue priority** with multiple queues per worker

✅ **Graceful shutdown** with signal handlers

### Enterprise Features

✅ **ACID guarantees** (PostgreSQL/MySQL drivers)

✅ **Dead-letter queues** for failed task inspection

✅ **Visibility timeouts** for crash recovery

✅ **Connection pooling** for optimal resource usage

✅ **Transactional dequeue** with `SELECT FOR UPDATE SKIP LOCKED`

✅ **Task metadata tracking** (attempts, timestamps, task IDs)

✅ **Concurrent processing** with configurable worker concurrency

### Integrations

✅ **FastAPI** – Automatic lifecycle management, dependency injection

✅ **SQLAlchemy** – Async and sync model serialization

✅ **Django ORM** – Native async support (Django 3.1+)

✅ **Tortoise ORM** – Full async ORM integration

### Developer Tools

✅ **Comprehensive CLI** – Worker management and database migrations

✅ **Function-based tasks** with `@task` decorator

✅ **Class-based tasks** with lifecycle hooks (`handle`, `failed`, `should_retry`)

✅ **Method chaining** for fluent task configuration

✅ **Environment variable configuration** for 12-factor apps

---

## Quick Start

Get started in 60 seconds:

```bash
# Install Async Task
uv add async-task[redis]
```

```python
import asyncio

from async_task.config import set_global_config
from async_task.core.task import task

# 1. Configure (or use environment variables)
set_global_config(driver="redis", redis_url="redis://localhost:6379", redis_password=None)


# 2. Define a task
@task
async def send_email(to: str, subject: str, body: str):
    print(f"Sending email to {to}: {subject}")
    await asyncio.sleep(1)  # Simulate email sending
    return f"Email sent to {to}"


# 3. Dispatch the task
async def main():
    for i in range(10):
        task_id = await send_email.dispatch(
            to=f"user{i}@example.com", subject=f"Welcome {i}!", body="Welcome to our platform!"
        )
        print(f"Task dispatched: {task_id}")


if __name__ == "__main__":
    asyncio.run(main())

```

```bash
# Run the worker
python -m async_task worker
```

**That's it!** Your first async task queue is ready. Now let's explore the powerful features.

---

## Quick Reference

- **One-line setup:** `just init` — install deps and pre-commit hooks
- **Start services:** `just services-up` — Redis, PostgreSQL, MySQL, RabbitMQ, LocalStack (SQS) for local integration tests
- **Run tests:** `just test` (or `pytest`) — use `just test-unit` / `just test-integration` to scope
- **Run with coverage:** `just test-cov` or `pytest --cov=src/async_task --cov-report=html`
- **Run the worker locally:** `python -m async_task worker`
- **Pre-commit hooks:** `./setup-pre-commit.sh` or `just setup-hooks`
- **Format / lint / typecheck:** `just format`, `just lint`, `just typecheck`

## CI & Contributing (short)

- **CI runs on PRs and pushes to `main`** and includes lint, type checks and tests across Python 3.11–3.14.
- **Pre-commit hooks** enforce formatting and static checks locally before commits (see `./setup-pre-commit.sh`).
- **Branch protection:** enable required status checks (CI success, lint, unit/integration jobs) for `main`.
- **Coverage badge:** the repository updates `.github/coverage.svg` automatically via `.github/workflows/coverage-badge.yml`.
- **Run full CI locally:** `just ci` (runs format/lint/typecheck/tests like the workflow).

## Comparison with Alternatives

### Async Task vs. Celery

| Feature                 | Async Task                                        | Celery                             |
| ----------------------- | ------------------------------------------------- | ---------------------------------- |
| **Async Support**       | ✅ Async-first, built with asyncio                 | ❌ No native asyncio support        |
| **Type Safety**         | ✅ Full type hints, Generic[T]                     | ⚠️ Third-party stubs (celery-types) |
| **Multi-Driver**        | ✅ 5 drivers (Redis/PostgreSQL/MySQL/RabbitMQ/SQS) | ⚠️ Redis/RabbitMQ/SQS brokers       |
| **ORM Integration**     | ✅ Auto-serialization (SQLAlchemy/Django/Tortoise) | ❌ Manual serialization             |
| **Serialization**       | ✅ msgpack (fast, binary)                          | ⚠️ JSON/pickle (slower)             |
| **FastAPI Integration** | ✅ First-class, lifespan management                | ⚠️ Manual setup                     |
| **Dead-Letter Queue**   | ✅ Built-in (PG/MySQL)                             | ⚠️ Manual setup (RabbitMQ DLX)      |
| **ACID Guarantees**     | ✅ PostgreSQL/MySQL drivers                        | ❌ Not available                    |
| **Setup Complexity**    | ✅ Zero-config with env vars                       | ⚠️ Complex configuration            |
| **Learning Curve**      | ✅ Simple, intuitive API                           | ⚠️ Steep learning curve             |

**When to use Async Task:**

- Modern async Python applications
- Need for type safety and IDE support
- Multiple driver options (dev → production)
- Automatic ORM model handling
- FastAPI applications
- Enterprise ACID requirements

**When to use Celery:**

- Mature ecosystem with many plugins
- Need for complex workflows (chains, chords)
- Large existing Celery codebase

---

### Async Task vs. Dramatiq

| Feature                 | Async Task             | Dramatiq                   |
| ----------------------- | ---------------------- | -------------------------- |
| **Async Support**       | ✅ Async-first          | ⚠️ Limited (via middleware) |
| **Type Safety**         | ✅ Full type hints      | ✅ Type hints (py.typed)    |
| **Multi-Driver**        | ✅ 5 drivers            | ⚠️ Redis/RabbitMQ           |
| **ORM Integration**     | ✅ Auto-serialization   | ❌ Manual serialization     |
| **Dead-Letter Queue**   | ✅ Built-in             | ✅ Built-in                 |
| **FastAPI Integration** | ✅ First-class          | ⚠️ Manual setup             |
| **Database Drivers**    | ✅ PostgreSQL/MySQL     | ❌ Not available            |
| **Simplicity**          | ✅ Clean, intuitive API | ✅ Simple, well-designed    |

**When to use Async Task:**

- Async applications (FastAPI, aiohttp)
- Type-safe codebase
- Database-backed queues (ACID)
- ORM model handling

**When to use Dramatiq:**

- Synchronous applications
- Need for mature, battle-tested library
- Complex middleware requirements

---

### Async Task vs. RQ (Redis Queue)

| Feature               | Async Task                       | RQ                     |
| --------------------- | -------------------------------- | ---------------------- |
| **Async Support**     | ✅ Async-first                    | ❌ Sync only            |
| **Multi-Driver**      | ✅ 5 drivers                      | ❌ Redis only           |
| **Type Safety**       | ✅ Full type hints                | ✅ Type hints added     |
| **Retries**           | ✅ Configurable with custom logic | ✅ Configurable retries |
| **Dead-Letter Queue** | ✅ Built-in                       | ❌ Not available        |
| **Database Drivers**  | ✅ PostgreSQL/MySQL               | ❌ Not available        |
| **Simplicity**        | ✅ Intuitive, clean API           | ✅ Very simple          |

**When to use Async Task:**

- Async applications
- Multiple driver options
- Enterprise features (DLQ, ACID)
- Type safety

**When to use RQ:**

- Simple use cases
- Synchronous applications
- Redis-only infrastructure

---

### Async Task vs. Huey

| Feature                 | Async Task                      | Huey             |
| ----------------------- | ------------------------------- | ---------------- |
| **Async Support**       | ✅ Async-first                   | ⚠️ Limited async  |
| **Multi-Driver**        | ✅ 5 drivers                     | ⚠️ Redis/SQLite   |
| **Type Safety**         | ✅ Full type hints               | ❌ Limited        |
| **ORM Integration**     | ✅ Auto-serialization            | ❌ Manual         |
| **Enterprise Features** | ✅ ACID, DLQ, visibility timeout | ⚠️ Basic features |
| **Simplicity**          | ✅ Clean, modern API             | ✅ Simple         |

**When to use Async Task:**

- Async-first applications
- Enterprise requirements
- Type-safe codebase
- ORM integration

**When to use Huey:**

- Lightweight use cases
- Simple task queues
- SQLite-backed queues

---

### Key Differentiators

**Async Task stands out with:**

1. **True async-first design** – Built with asyncio from the ground up
2. **msgpack serialization** – Faster and more efficient than JSON
3. **Intelligent ORM handling** – Automatic model serialization for 3 major ORMs
4. **Multi-driver flexibility** – Seamlessly switch between 5 production-ready drivers (Redis, PostgreSQL, MySQL, RabbitMQ, SQS)
5. **Type safety** – Full type hints with Generic[T] support
6. **Enterprise ACID guarantees** – PostgreSQL/MySQL drivers with transactional dequeue
7. **Dead-letter queues** – Built-in support for failed task inspection
8. **FastAPI integration** – First-class support with lifecycle management
9. **Elegant, expressive API** – Method chaining and intuitive task definitions
10. **Zero configuration** – Works with environment variables out of the box

---

## Documentation

For detailed documentation, see the following guides:

- **[Installation](docs/installation.md)** – Installation instructions for uv and pip
- **[Queue Drivers](docs/queue-drivers.md)** – Redis, PostgreSQL, MySQL, RabbitMQ, AWS SQS
- **[ORM Integrations](docs/orm-integrations.md)** – SQLAlchemy, Django, Tortoise ORM
- **[Framework Integrations](docs/framework-integrations.md)** – FastAPI integration
- **[Task Definitions](docs/task-definitions.md)** – Function-based and class-based tasks
- **[Running Workers](docs/running-workers.md)** – CLI and programmatic workers
- **[Configuration](docs/configuration.md)** – Environment variables, programmatic, CLI
- **[CLI Reference](docs/cli-reference.md)** – Complete command reference
- **[Best Practices](docs/best-practices.md)** – Task design, queue organization, production deployment

---

## Examples

For complete examples, see the following guides:

- **[Function-Based Tasks Examples](docs/examples/function-based-tasks.md)** – Complete examples guide
- **[Class-Based Tasks Examples](docs/examples/class-based-tasks.md)** – Complete examples guide

---

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## License

MIT License – see [LICENSE](LICENSE) file for details.

---

## Support

- **Repository:** [github.com/adamrefaey/async-task](https://github.com/adamrefaey/async-task)
- **Issues:** [github.com/adamrefaey/async-task/issues](https://github.com/adamrefaey/async-task/issues)
- **Discussions:** [github.com/adamrefaey/async-task/discussions](https://github.com/adamrefaey/async-task/discussions)

---

## Roadmap

- [ ] SQLite driver support
- [ ] Oracle driver support
- [ ] Task batching support
- [ ] Task chaining and workflows
- [ ] Rate limiting
- [ ] Task priority within queues
- [ ] Web UI for monitoring
- [ ] Prometheus metrics exporter
- [ ] Additional ORM support

---

## Credits

Built with ❤️ by [Adam Refaey](https://github.com/adamrefaey).
