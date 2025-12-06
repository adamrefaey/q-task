# Framework Integrations

## FastAPI Integration

Async TasQ provides seamless FastAPI integration with automatic lifecycle management and dependency injection.

**Installation:**

```bash
# With uv
uv add "asynctasq[fastapi]"

# With pip
pip install "asynctasq[fastapi]"
```

**Requirements:**

- fastapi >= 0.115.0

**Basic Setup:**

```python
from fastapi import FastAPI, Depends
from asynctasq.integrations.fastapi import AsyncTaskIntegration
from asynctasq.core.task import task
from asynctasq.core.dispatcher import Dispatcher
from asynctasq.drivers.base_driver import BaseDriver

# Auto-configure from environment variables
# asynctasq_DRIVER=redis
# asynctasq_REDIS_URL=redis://localhost:6379
asynctasq = AsyncTaskIntegration()

# Create FastAPI app with asynctasq lifespan
app = FastAPI(lifespan=asynctasq.lifespan)

# Define a task
@task(queue='emails')
async def send_email(to: str, subject: str, body: str):
    print(f"Sending email to {to}: {subject}")
    return f"Email sent to {to}"

# Use in endpoint
@app.post("/send-email")
async def send_email_route(to: str, subject: str, body: str):
    task_id = await send_email.dispatch(to=to, subject=subject, body=body)
    return {"task_id": task_id, "status": "queued"}
```

**Explicit Configuration:**

```python
from asynctasq.config import Config

config = Config(
    driver="redis",
    redis_url="redis://localhost:6379",
    redis_db=1
)
asynctasq = AsyncTaskIntegration(config=config)
app = FastAPI(lifespan=asynctasq.lifespan)
```

**Dependency Injection:**

```python
@app.post("/dispatch-task")
async def dispatch_task(
    dispatcher: Dispatcher = Depends(asynctasq.get_dispatcher)
):
    # Use dispatcher directly
    task_id = await dispatcher.dispatch(my_task)
    return {"task_id": task_id}

@app.get("/queue-stats")
async def get_stats(
    driver: BaseDriver = Depends(asynctasq.get_driver)
):
    # Access driver for queue inspection
    size = await driver.get_queue_size("default")
    return {"queue": "default", "size": size}
```

**Custom Driver Instance:**

```python
from asynctasq.drivers.redis_driver import RedisDriver

# Use pre-configured driver
custom_driver = RedisDriver(url='redis://cache-server:6379', db=2)
asynctasq = AsyncTaskIntegration(driver=custom_driver)
app = FastAPI(lifespan=asynctasq.lifespan)
```

**Important Notes:**

- FastAPI integration handles **task dispatching only**
- **Workers must run separately** to process tasks
- Two processes required:
  - **Terminal 1:** FastAPI app (dispatch tasks)
  - **Terminal 2:** Worker (process tasks)

**Example Deployment:**

```bash
# Terminal 1: Start FastAPI app
uvicorn app:app --host 0.0.0.0 --port 8000

# Terminal 2: Start worker
python -m asynctasq worker \
    --driver redis \
    --redis-url redis://localhost:6379 \
    --queues default,emails \
    --concurrency 10
```

**Features:**

- Automatic driver connection on startup
- Graceful driver disconnection on shutdown
- Zero-configuration with environment variables
- Dependency injection for dispatcher and driver access
- Works with all drivers (Redis, PostgreSQL, MySQL, RabbitMQ, AWS SQS)

---

## Event Streaming with FastAPI

For real-time monitoring, you can stream task events via WebSocket:

```python
from fastapi import FastAPI, WebSocket
from asynctasq.integrations.fastapi import AsyncTaskIntegration
from asynctasq.core.events import EventSubscriber

asynctasq = AsyncTaskIntegration()
app = FastAPI(lifespan=asynctasq.lifespan)

@app.websocket("/events")
async def events_websocket(websocket: WebSocket):
    await websocket.accept()
    
    subscriber = EventSubscriber(redis_url="redis://localhost:6379")
    await subscriber.connect()
    
    try:
        async for event in subscriber.listen():
            await websocket.send_json({
                "type": event.event_type,
                "task_id": event.task_id,
                "task_name": event.task_name,
                "timestamp": event.timestamp.isoformat()
            })
    finally:
        await subscriber.disconnect()
```
