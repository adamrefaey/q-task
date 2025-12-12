# AsyncTasQ

[![Tests](https://raw.githubusercontent.com/adamrefaey/asynctasq/main/.github/tests.svg)](https://github.com/adamrefaey/asynctasq/actions/workflows/ci.yml)
[![Coverage](https://raw.githubusercontent.com/adamrefaey/asynctasq/main/.github/coverage.svg)](https://raw.githubusercontent.com/adamrefaey/asynctasq/main/.github/coverage.svg)
[![Python Version](https://raw.githubusercontent.com/adamrefaey/asynctasq/main/.github/python-version.svg)](https://www.python.org/downloads/)
[![PyPI Version](https://img.shields.io/pypi/v/asynctasq)](https://pypi.org/project/asynctasq/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A modern, async-first, type-safe task queue for Python 3.12+. Inspired by Laravel's elegant queue system. Native FastAPI integration. Switch between multiple queue backends (Redis, PostgreSQL, MySQL, RabbitMQ, AWS SQS) with one config line. Automatic ORM serialization (SQLAlchemy, Django, Tortoise) using msgpack reduces payloads by 90%+. Features ACID guarantees, dead-letter queues, crash recovery, and real-time event streaming.

> 📊 **Looking for a monitoring dashboard?** Check out **[asynctasq-monitor](https://github.com/adamrefaey/asynctasq-monitor)** – a beautiful real-time UI to monitor your tasks, workers, and queues.

---

## Table of Contents

- [AsyncTasQ](#asynctasq)
  - [Table of Contents](#table-of-contents)
  - [Why AsyncTasQ?](#why-asynctasq)
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
    - [AsyncTasQ vs. Celery](#asynctasq-vs-celery)
    - [AsyncTasQ vs. Dramatiq](#asynctasq-vs-dramatiq)
    - [AsyncTasQ vs. RQ (Redis Queue)](#asynctasq-vs-rq-redis-queue)
    - [AsyncTasQ vs. Huey](#asynctasq-vs-huey)
    - [Key Differentiators](#key-differentiators)
  - [📊 Monitoring Dashboard](#-monitoring-dashboard)
    - [asynctasq-monitor](#asynctasq-monitor)
  - [Documentation](#documentation)
  - [Examples](#examples)
  - [Contributing](#contributing)
  - [License](#license)
  - [Support](#support)
  - [Roadmap](#roadmap)
  - [Credits](#credits)

---

## Why AsyncTasQ?

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
- **Real-time events** – Redis Pub/Sub event streaming for task lifecycle monitoring

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

  - ✅ **Async-first design** with asyncio throughout the stack

  - ✅ **Multiple queue drivers**: Redis, PostgreSQL, MySQL, RabbitMQ, AWS SQS

  - ✅ **High-performance msgpack serialization** with binary support

  - ✅ **Automatic ORM model handling** for SQLAlchemy, Django, Tortoise

  - ✅ **Type-safe** with full type hints and Generic support

  - ✅ **Three execution modes**: Async (I/O), Thread pool (moderate CPU), Process pool (heavy CPU)

  - ✅ **Configurable retries** with custom retry logic hooks

  - ✅ **Task timeouts** to prevent runaway tasks

  - ✅ **Delayed task execution** with precision timing

  - ✅ **Queue priority** with multiple queues per worker

  - ✅ **Graceful shutdown** with signal handlers

### Enterprise Features

  - ✅ **ACID guarantees** (PostgreSQL/MySQL drivers)

  - ✅ **Dead-letter queues** for failed task inspection

  - ✅ **Visibility timeouts** for crash recovery

  - ✅ **Connection pooling** for optimal resource usage

  - ✅ **Transactional dequeue** with `SELECT FOR UPDATE SKIP LOCKED`

  - ✅ **Task metadata tracking** (attempts, timestamps, task IDs)

  - ✅ **Concurrent processing** with configurable worker concurrency

  - ✅ **Real-time event streaming** via Redis Pub/Sub

### Integrations

  - ✅ **FastAPI** – Automatic lifecycle management, dependency injection

  - ✅ **SQLAlchemy** – Async and sync model serialization

  - ✅ **Django ORM** – Native async support (Django 3.1+)

  - ✅ **Tortoise ORM** – Full async ORM integration

  - ✅ **[asynctasq-monitor](https://github.com/adamrefaey/asynctasq-monitor)** – Real-time monitoring dashboard (optional)

### Developer Tools

  - ✅ **Comprehensive CLI** – Worker management and database migrations

  - ✅ **Function-based tasks** with `@task` decorator

  - ✅ **Class-based tasks** with 4 execution modes:
    - `AsyncTask` – Async I/O-bound (API calls, async DB queries)
    - `SyncTask` – Sync I/O-bound via thread pool (`requests`, sync DB drivers)
    - `AsyncProcessTask` – Async CPU-intensive via process pool
    - `SyncProcessTask` – Sync CPU-intensive via process pool (bypasses GIL)

  - ✅ **Lifecycle hooks** – `execute()`, `failed()`, `should_retry()` for complete control

  - ✅ **Method chaining** for fluent task configuration

  - ✅ **Environment variable configuration** for 12-factor apps

---

## Quick Start

Get started in 60 seconds:

```bash
# Install AsyncTasQ (Python 3.12+ required)
uv add asynctasq[redis]
```

```python
import asyncio

from asynctasq.config import set_global_config
from asynctasq.tasks import task

# 1. Configure (or use environment variables)
set_global_config(driver="redis", redis_url="redis://localhost:6379")


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
# Run the worker (in a separate terminal)
python -m asynctasq worker
```

**That's it!** Your first AsyncTasQ is ready. Now let's explore the powerful features.

---

## Quick Reference

- **One-line setup:** `just init` — install deps and pre-commit hooks
- **Start services:** `just services-up` — Redis, PostgreSQL, MySQL, RabbitMQ, LocalStack (SQS) for local integration tests
- **Run tests:** `just test` (or `pytest`) — use `just test-unit` / `just test-integration` to scope
- **Run with coverage:** `just test-cov` or `pytest --cov=src/asynctasq --cov-report=html`
- **Run the worker locally:** `python -m asynctasq worker`
- **Pre-commit hooks:** [`./setup-pre-commit.sh`](https://github.com/adamrefaey/asynctasq/blob/main/setup-pre-commit.sh) or `just setup-hooks`
- **Format / lint / typecheck:** `just format`, `just lint`, `just typecheck`

## CI & Contributing (short)

- **CI runs on PRs and pushes to `main`** and includes lint, type checks and tests across Python 3.12–3.14.
- **Pre-commit hooks** enforce formatting and static checks locally before commits (see [`./setup-pre-commit.sh`](https://github.com/adamrefaey/asynctasq/blob/main/setup-pre-commit.sh)).
- **Branch protection:** enable required status checks (CI success, lint, unit/integration jobs) for `main`.
- **Coverage badge:** the repository updates `.github/coverage.svg` automatically via `.github/workflows/coverage-badge.yml`.
- **Run full CI locally:** `just ci` (runs format/lint/typecheck/tests like the workflow).

## Comparison with Alternatives

### AsyncTasQ vs. Celery

| Feature                 | AsyncTasQ                                        | Celery                                    |
| ----------------------- | ------------------------------------------------- | ----------------------------------------- |
| **Async Support**       | ✅ Async-first, built with asyncio                 | ❌ No native asyncio support               |
| **Type Safety**         | ✅ Full type hints, Generic[T]                     | ⚠️ Third-party stubs (celery-types)        |
| **Multi-Driver**        | ✅ 5 drivers (Redis/PostgreSQL/MySQL/RabbitMQ/SQS) | ⚠️ 3 brokers (Redis/RabbitMQ/SQS)          |
| **ORM Integration**     | ✅ Auto-serialization (SQLAlchemy/Django/Tortoise) | ❌ Manual serialization                    |
| **Serialization**       | ✅ msgpack (fast, binary)                          | ⚠️ JSON/pickle (configurable)              |
| **FastAPI Integration** | ✅ First-class, lifespan management                | ⚠️ Manual setup                            |
| **Dead-Letter Queue**   | ✅ Built-in (PG/MySQL)                             | ⚠️ Manual setup (RabbitMQ DLX)             |
| **ACID Guarantees**     | ✅ PostgreSQL/MySQL drivers                        | ❌ Not available                           |
| **Setup Complexity**    | ✅ Zero-config with env vars                       | ⚠️ Complex configuration                   |
| **Learning Curve**      | ✅ Simple, intuitive API                           | ⚠️ Steep learning curve                    |

**When to use AsyncTasQ:**

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

### AsyncTasQ vs. Dramatiq

| Feature                 | AsyncTasQ             | Dramatiq                   |
| ----------------------- | ---------------------- | -------------------------- |
| **Async Support**       | ✅ Async-first          | ⚠️ Limited (via middleware) |
| **Type Safety**         | ✅ Full type hints      | ✅ Type hints (py.typed)    |
| **Multi-Driver**        | ✅ 5 drivers            | ⚠️ Redis/RabbitMQ           |
| **ORM Integration**     | ✅ Auto-serialization   | ❌ Manual serialization     |
| **Dead-Letter Queue**   | ✅ Built-in             | ✅ Built-in                 |
| **FastAPI Integration** | ✅ First-class          | ⚠️ Manual setup             |
| **Database Drivers**    | ✅ PostgreSQL/MySQL     | ❌ Not available            |
| **Simplicity**          | ✅ Clean, intuitive API | ✅ Simple, well-designed    |

**When to use AsyncTasQ:**

- Async applications (FastAPI, aiohttp)
- Type-safe codebase
- Database-backed queues (ACID)
- ORM model handling

**When to use Dramatiq:**

- Synchronous applications
- Need for mature, battle-tested library
- Complex middleware requirements

---

### AsyncTasQ vs. RQ (Redis Queue)

| Feature               | AsyncTasQ                       | RQ                     |
| --------------------- | -------------------------------- | ---------------------- |
| **Async Support**     | ✅ Async-first                    | ❌ Sync only            |
| **Multi-Driver**      | ✅ 5 drivers                      | ❌ Redis only           |
| **Type Safety**       | ✅ Full type hints                | ✅ Type hints added     |
| **Retries**           | ✅ Configurable with custom logic | ✅ Configurable retries |
| **Dead-Letter Queue** | ✅ Built-in                       | ❌ Not available        |
| **Database Drivers**  | ✅ PostgreSQL/MySQL               | ❌ Not available        |
| **Simplicity**        | ✅ Intuitive, clean API           | ✅ Very simple          |

**When to use AsyncTasQ:**

- Async applications
- Multiple driver options
- Enterprise features (DLQ, ACID)
- Type safety

**When to use RQ:**

- Simple use cases
- Synchronous applications
- Redis-only infrastructure

---

### AsyncTasQ vs. Huey

| Feature                 | AsyncTasQ                      | Huey             |
| ----------------------- | ------------------------------- | ---------------- |
| **Async Support**       | ✅ Async-first                   | ⚠️ Limited async  |
| **Multi-Driver**        | ✅ 5 drivers                     | ⚠️ Redis/SQLite   |
| **Type Safety**         | ✅ Full type hints               | ❌ Limited        |
| **ORM Integration**     | ✅ Auto-serialization            | ❌ Manual         |
| **Enterprise Features** | ✅ ACID, DLQ, visibility timeout | ⚠️ Basic features |
| **Simplicity**          | ✅ Clean, modern API             | ✅ Simple         |

**When to use AsyncTasQ:**

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

**AsyncTasQ stands out with:**

1. **True async-first design** – Built with asyncio from the ground up
2. **msgpack serialization** – Faster and more efficient than JSON
3. **Intelligent ORM handling** – Automatic model serialization for 3 major ORMs
4. **Multi-driver flexibility** – Seamlessly switch between 5 production-ready drivers (Redis, PostgreSQL, MySQL, RabbitMQ, SQS)
5. **Type safety** – Full type hints with Generic[T] support
6. **Enterprise ACID guarantees** – PostgreSQL/MySQL drivers with transactional dequeue
7. **Dead-letter queues** – Built-in support for failed task inspection
8. **FastAPI integration** – First-class support with lifecycle management
9. **Real-time event streaming** – Redis Pub/Sub for live monitoring dashboards
10. **Optional monitoring UI** – Beautiful dashboard via [asynctasq-monitor](https://github.com/adamrefaey/asynctasq-monitor)
11. **Elegant, expressive API** – Method chaining and intuitive task definitions
12. **Zero configuration** – Works with environment variables out of the box

---

## 📊 Monitoring Dashboard

### [asynctasq-monitor](https://github.com/adamrefaey/asynctasq-monitor)

A beautiful **real-time monitoring dashboard** for AsyncTasQ:

- 📈 **Live Dashboard** – Real-time task metrics, queue depths, and worker status
- 📊 **Task Analytics** – Execution times, success/failure rates, retry patterns
- 🔍 **Task Explorer** – Browse, search, and inspect task details
- 👷 **Worker Management** – Monitor worker health and performance
- 🚨 **Alerts** – Get notified about failures and queue backlogs

```bash
# Install the monitoring package
uv add asynctasq-monitor

# Start the monitoring server
asynctasq-monitor web
```

---

## Documentation

For detailed documentation, see the following guides:

- **[Installation](https://github.com/adamrefaey/asynctasq/blob/main/docs/installation.md)** – Installation instructions for uv and pip
- **[Queue Drivers](https://github.com/adamrefaey/asynctasq/blob/main/docs/queue-drivers.md)** – Redis, PostgreSQL, MySQL, RabbitMQ, AWS SQS
- **[ORM Integrations](https://github.com/adamrefaey/asynctasq/blob/main/docs/orm-integrations.md)** – SQLAlchemy, Django, Tortoise ORM
- **[Framework Integrations](https://github.com/adamrefaey/asynctasq/blob/main/docs/framework-integrations.md)** – FastAPI integration
- **[Task Definitions](https://github.com/adamrefaey/asynctasq/blob/main/docs/task-definitions.md)** – Function-based and class-based tasks
- **[Running Workers](https://github.com/adamrefaey/asynctasq/blob/main/docs/running-workers.md)** – CLI and programmatic workers
- **[Configuration](https://github.com/adamrefaey/asynctasq/blob/main/docs/configuration.md)** – Environment variables, programmatic, CLI
- **[CLI Reference](https://github.com/adamrefaey/asynctasq/blob/main/docs/cli-reference.md)** – Complete command reference
- **[Best Practices](https://github.com/adamrefaey/asynctasq/blob/main/docs/best-practices.md)** – Task design, queue organization, production deployment

---

## Examples

For complete examples, see the following guides:

- **[Function-Based Tasks Examples](https://github.com/adamrefaey/asynctasq/blob/main/docs/examples/function-based-tasks.md)** – Complete examples guide
- **[Class-Based Tasks Examples](https://github.com/adamrefaey/asynctasq/blob/main/docs/examples/class-based-tasks.md)** – Complete examples guide

---

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](https://github.com/adamrefaey/asynctasq/blob/main/CONTRIBUTING.md) for guidelines.

---

## License

MIT License – see [LICENSE](https://github.com/adamrefaey/asynctasq/blob/main/LICENSE) file for details.

---

## Support

- **Repository:** [github.com/adamrefaey/asynctasq](https://github.com/adamrefaey/asynctasq)
- **Issues:** [github.com/adamrefaey/asynctasq/issues](https://github.com/adamrefaey/asynctasq/issues)
- **Discussions:** [github.com/adamrefaey/asynctasq/discussions](https://github.com/adamrefaey/asynctasq/discussions)

---

## Roadmap

- [ ] SQLite driver support
- [ ] Oracle driver support
- [ ] Task batching support
- [ ] Task chaining and workflows (chains, chords, groups)
- [ ] Rate limiting
- [ ] Task priority within queues
- [ ] Scheduled/cron tasks

---

## Credits

Built with ❤️ by [Adam Refaey](https://github.com/adamrefaey).
