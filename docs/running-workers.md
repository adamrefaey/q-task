# Running Workers

Workers continuously poll queues and execute tasks. Run workers via CLI (recommended) or programmatically.

## CLI Workers (Recommended)

**Basic Usage:**

```bash
# Start worker with default settings
python -m asynctasq worker

# Or with uv
uv run python -m asynctasq worker
```

**With Driver Configuration:**

```bash
# Redis worker
python -m asynctasq worker \
    --driver redis \
    --redis-url redis://localhost:6379 \
    --redis-password secret \
    --redis-db 1

# PostgreSQL worker
python -m asynctasq worker \
    --driver postgres \
    --postgres-dsn postgresql://user:pass@localhost/dbname \
    --queues default,emails \
    --concurrency 10

# MySQL worker
python -m asynctasq worker \
    --driver mysql \
    --mysql-dsn mysql://user:pass@localhost:3306/dbname \
    --queues default,emails \
    --concurrency 10

# AWS SQS worker
python -m asynctasq worker \
    --driver sqs \
    --sqs-region us-west-2 \
    --sqs-queue-url-prefix https://sqs.us-west-2.amazonaws.com/123456789/ \
    --queues default,emails
```

**Multiple Queues with Priority:**

```bash
# Process queues in priority order: high → default → low
python -m asynctasq worker --queues high,default,low --concurrency 20
```

**Environment Variables:**

```bash
# Set environment variables
export asynctasq_DRIVER=redis
export asynctasq_REDIS_URL=redis://localhost:6379

# Start worker (reads from env vars)
python -m asynctasq worker
```

**Worker Options:**

| Option          | Description                                  | Default   |
| --------------- | -------------------------------------------- | --------- |
| `--driver`      | Queue driver (redis/postgres/mysql/rabbitmq/sqs)      | `redis`   |
| `--queues`      | Comma-separated queue names (priority order) | `default` |
| `--concurrency` | Max concurrent tasks                         | `10`      |

**Driver-Specific Options:**

See [Configuration](configuration.md) section for complete list of driver-specific CLI options.

---

## Programmatic Workers

For custom worker implementations or embedding workers in applications:

```python
import asyncio
from asynctasq.config import Config
from asynctasq.core.driver_factory import DriverFactory
from asynctasq.core.worker import Worker

async def main():
    # Create configuration
    config = Config.from_env(driver='redis', redis_url='redis://localhost:6379')

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

        # Start worker (blocks until SIGTERM/SIGINT)
        await worker.start()
    finally:
        # Cleanup
        await driver.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
```

**Worker Parameters:**

| Parameter            | Type             | Default | Description                                    |
| -------------------- | ---------------- | ------- | ---------------------------------------------- |
| `queue_driver`       | `BaseDriver`     | -       | Queue driver instance                          |
| `queues`             | `list[str]`      | `["default"]` | Queue names to process (priority order)  |
| `concurrency`        | `int`            | `10`    | Maximum concurrent tasks                       |
| `max_tasks`          | `int \| None`    | `None`  | Process N tasks then exit (None = run forever) |
| `serializer`         | `BaseSerializer` | `MsgpackSerializer` | Custom serializer            |
| `event_emitter`      | `EventEmitter`   | `None`  | Event emitter for real-time monitoring         |
| `worker_id`          | `str \| None`    | auto    | Custom worker identifier (auto-generated if None) |
| `heartbeat_interval` | `float`          | `60.0`  | Seconds between heartbeat events               |

**Worker Behavior:**

1. **Polling Loop:** Continuously checks queues until stopped
2. **Round-Robin:** Processes queues in priority order (first = highest priority)
3. **Concurrency Control:** Tracks active tasks, respects concurrency limit
4. **Fair Distribution:** Polls all queues before repeating first queue
5. **Sleep on Empty:** 100ms sleep when no tasks available (prevents CPU spinning)
6. **Graceful Shutdown:** SIGTERM/SIGINT wait for in-flight tasks to complete

**Testing/Batch Mode:**

```python
# Process exactly 10 tasks then exit
worker = Worker(
    queue_driver=driver,
    queues=['default'],
    concurrency=5,
    max_tasks=10  # Exit after 10 tasks
)
await worker.start()
```

---

## Multiple Workers for Different Queues

Run multiple worker processes for different queue priorities:

```bash
# Terminal 1: High-priority queue with high concurrency
python -m asynctasq worker --queues high-priority --concurrency 20

# Terminal 2: Default queue with moderate concurrency
python -m asynctasq worker --queues default --concurrency 10

# Terminal 3: Low-priority and batch jobs with low concurrency
python -m asynctasq worker --queues low-priority,batch --concurrency 5
```

**Benefits:**

- Isolate critical tasks from low-priority work
- Prevent slow tasks from blocking fast tasks
- Scale different queues independently
- Dedicate resources based on queue importance

---

## Event Streaming

Workers can emit real-time events for monitoring via Redis Pub/Sub. This enables live dashboards and metrics.

**Event Types:**

| Event              | Description                                |
| ------------------ | ------------------------------------------ |
| `task_enqueued`    | Task added to queue                        |
| `task_started`     | Worker began executing task                |
| `task_completed`   | Task finished successfully                 |
| `task_failed`      | Task failed after all retries              |
| `task_retrying`    | Task failed, will retry                    |
| `worker_online`    | Worker started                             |
| `worker_heartbeat` | Periodic worker status (every 60s default) |
| `worker_offline`   | Worker shutting down                       |

**Enable Event Streaming:**

```python
from asynctasq.core.events import create_event_emitter
from asynctasq.core.worker import Worker

# Create event emitter (uses Redis Pub/Sub)
emitter = create_event_emitter(redis_url="redis://localhost:6379")

# Create worker with events
worker = Worker(
    queue_driver=driver,
    queues=['default'],
    event_emitter=emitter,
    worker_id="worker-1",       # Custom ID for identification
    heartbeat_interval=60.0     # Heartbeat every 60 seconds
)
await worker.start()
```

**Configure via Environment:**

```bash
export asynctasq_EVENTS_REDIS_URL=redis://localhost:6379
export asynctasq_EVENTS_CHANNEL=asynctasq:events
```

**Consume Events:**

```python
from asynctasq.core.events import EventSubscriber

async def monitor_events():
    subscriber = EventSubscriber(redis_url="redis://localhost:6379")
    await subscriber.connect()
    
    async for event in subscriber.listen():
        print(f"Event: {event.event_type} - Task: {event.task_id}")
```

---

## Graceful Shutdown

Workers handle `SIGTERM` and `SIGINT` signals for clean shutdown:

**Shutdown Process:**

1. **Stop accepting new tasks** – No new tasks dequeued from driver
2. **Wait for completion** – Currently processing tasks finish naturally
3. **Disconnect** – Driver connections closed cleanly
4. **Exit** – Process terminates gracefully

**Trigger Shutdown:**

```bash
# Send SIGTERM for graceful shutdown
kill -TERM <worker_pid>

# Or use Ctrl+C for SIGINT (same behavior)
```

**Production Deployment:**

Use process managers that send SIGTERM for clean shutdowns:

- **systemd:** Sends SIGTERM by default
- **supervisor:** Configure `stopasgroup=true`
- **Kubernetes:** Sends SIGTERM before SIGKILL (grace period)
- **Docker:** `docker stop` sends SIGTERM

**Example systemd service:**

```ini
[Unit]
Description=Async TasQ Worker
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/app
ExecStart=/usr/bin/python -m asynctasq worker --driver redis --queues default
Restart=always
KillSignal=SIGTERM
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```
