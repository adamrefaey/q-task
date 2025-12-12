# Error Handling Architecture

## Overview

The asynctasq error handling system is designed with clear separation of concerns between framework-level error management and user-level error hooks. This document outlines the error handling flow, responsibilities, and extension points.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                          Worker Loop                            │
│  (Continuously polls queues for tasks)                          │
└─────────────────┬───────────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                      TaskExecutor.execute()                     │
│  Framework Entry Point - Wraps execution with timeout           │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  try:                                                     │  │
│  │      result = await asyncio.wait_for(                    │  │
│  │          task.execute(),                                 │  │
│  │          timeout=task.config.timeout                     │  │
│  │      )                                                     │  │
│  │      return SUCCESS                                       │  │
│  │  except asyncio.TimeoutError:                            │  │
│  │      # Framework handles timeout                         │  │
│  │  except Exception as e:                                  │  │
│  │      # Framework catches all exceptions                  │  │
│  │      return await handle_failed(task, e)                 │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────┬───────────────────────────────────────────────┘
                  │ (Exception caught)
                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                 TaskExecutor.handle_failed()                    │
│  Framework Error Recovery Logic                                 │
│                                                                  │
│  1. Check if task.should_retry(exception) → User Hook          │
│  2. Check if attempts < max_retries                            │
│  3. If retry: Re-queue task with incremented attempts          │
│  4. If exhausted: Call task.failed(exception) → User Hook      │
│  5. Return appropriate status (RETRY or FAILED)                │
└─────────────────────────────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                     User Extension Points                       │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  BaseTask.should_retry(exception: Exception) -> bool    │  │
│  │  ─────────────────────────────────────────────────────  │  │
│  │  Purpose: Decide if task should retry after failure     │  │
│  │  Default: Always return True (retry until max_retries)  │  │
│  │  Override: Custom retry logic (e.g., fail fast on       │  │
│  │           validation errors, retry on network errors)   │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  async BaseTask.failed(exception: Exception) -> None    │  │
│  │  ─────────────────────────────────────────────────────  │  │
│  │  Purpose: Handle task failure after retries exhausted   │  │
│  │  Default: No-op (pass)                                  │  │
│  │  Override: Custom failure handling (alerts, logging,    │  │
│  │           cleanup, compensation logic)                   │  │
│  │  Note: Exceptions raised here are logged but don't      │  │
│  │        affect task processing (fail-safe)                │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Layer Responsibilities

### 1. Framework Layer (TaskExecutor)

**File:** `src/asynctasq/tasks/services/executor.py`

**Responsibilities:**
- Wrap task execution with timeout (`asyncio.wait_for`)
- Catch ALL exceptions from task execution
- Implement retry logic (attempts counting, re-queueing)
- Call user hooks (`should_retry()`, `failed()`)
- Handle timeout errors specifically
- Ensure worker stability (no unhandled exceptions escape)

**Key Methods:**
- `execute(task)` - Main entry point with timeout wrapper
- `handle_failed(task, exception)` - Retry/failure decision logic

**Error Handling Rules:**
1. All task exceptions are caught at this level
2. Timeout errors are treated as retriable failures
3. User hooks (`failed()`) are called in try-except to prevent worker crashes
4. Framework NEVER lets exceptions escape to worker loop

### 2. User Layer (BaseTask)

**File:** `src/asynctasq/tasks/core/base_task.py`

**Responsibilities:**
- Implement business logic in `handle()`
- Optionally override `should_retry()` for custom retry decisions
- Optionally override `failed()` for custom failure handling
- Let exceptions propagate to framework (don't catch unless needed)

**Key Methods:**
- `should_retry(exception)` - User hook for retry decision
- `failed(exception)` - User hook for exhausted retries

**Error Handling Rules:**
1. Users implement business logic; framework handles errors
2. Override `should_retry()` ONLY if custom retry logic needed
3. Override `failed()` ONLY if custom failure handling needed
4. Don't catch exceptions in `handle()` unless recovering in-place

## Error Flow Examples

### Example 1: Successful Execution (No Error)

```
Worker → TaskExecutor.execute()
       → task.execute()
       → task.handle() [User Code]
       ← Returns result
       ← SUCCESS
       → Mark task complete
```

### Example 2: Transient Error with Retry

```
Worker → TaskExecutor.execute()
       → task.execute()
       → task.handle() [User Code]
       ← Raises ConnectionError
       → TaskExecutor.handle_failed()
       → Check task.should_retry(ConnectionError) → True (default)
       → Check attempts < max_retries → True
       → Re-queue task with attempts++
       ← RETRY
```

### Example 3: Permanent Failure (Retries Exhausted)

```
Worker → TaskExecutor.execute()
       → task.execute()
       → task.handle() [User Code]
       ← Raises ValueError
       → TaskExecutor.handle_failed()
       → Check task.should_retry(ValueError) → True (default)
       → Check attempts < max_retries → False (exhausted)
       → Call task.failed(ValueError) [User Hook]
       ← FAILED
       → Mark task failed
```

### Example 4: Custom Retry Logic (Fail Fast)

```python
class ValidateDataTask(AsyncTask[None]):
    async def handle(self) -> None:
        if not self.data:
            raise ValueError("Invalid data")
        # Process data...
    
    def should_retry(self, exception: Exception) -> bool:
        # Don't retry validation errors
        if isinstance(exception, ValueError):
            return False
        return True  # Retry other errors

# Execution flow:
Worker → TaskExecutor.execute()
       → task.execute()
       → task.handle() [User Code]
       ← Raises ValueError("Invalid data")
       → TaskExecutor.handle_failed()
       → Check task.should_retry(ValueError) → False (custom logic)
       → Call task.failed(ValueError) immediately
       ← FAILED (no retry)
```

### Example 5: Custom Failure Handling

```python
class SendEmailTask(AsyncTask[None]):
    email: str
    
    async def handle(self) -> None:
        # Send email logic...
        raise ConnectionError("SMTP server unavailable")
    
    async def failed(self, exception: Exception) -> None:
        # Custom failure handling
        await alert_team(f"Email to {self.email} failed: {exception}")
        await log_to_monitoring(exception)

# Execution flow:
Worker → TaskExecutor.execute()
       → task.execute()
       → task.handle() [User Code]
       ← Raises ConnectionError
       → TaskExecutor.handle_failed()
       → Retry logic... (exhausted after 3 attempts)
       → Call task.failed(ConnectionError) [User Hook]
         → alert_team() called
         → log_to_monitoring() called
       ← FAILED
```

## Common Patterns

### Pattern 1: Retry Only on Specific Errors

```python
class ResilientTask(AsyncTask[int]):
    def should_retry(self, exception: Exception) -> bool:
        # Retry only on transient network/timeout errors
        return isinstance(exception, (ConnectionError, TimeoutError))
```

### Pattern 2: Exponential Backoff (Framework Handles)

```python
# Framework automatically re-queues with retry_delay
task = MyTask().retry_after(60)  # 60s between retries
```

### Pattern 3: Compensation Logic on Failure

```python
class TransactionTask(AsyncTask[None]):
    transaction_id: str
    
    async def failed(self, exception: Exception) -> None:
        # Rollback transaction on permanent failure
        await rollback_transaction(self.transaction_id)
        await notify_user(self.transaction_id, "failed")
```

### Pattern 4: No Retry for Business Logic Errors

```python
class ProcessOrderTask(AsyncTask[None]):
    def should_retry(self, exception: Exception) -> bool:
        # Don't retry business logic errors
        if isinstance(exception, (ValueError, ValidationError)):
            return False
        return True  # Retry infrastructure errors
```

## Exception Types

### Framework-Raised Exceptions

- `asyncio.TimeoutError` - Task exceeded timeout (retriable)
- `SerializationError` - Task serialization/deserialization failed
- `DriverError` - Queue driver error (connection, etc.)

### User-Raised Exceptions

- Any exception from `task.handle()` is caught by framework
- Framework doesn't interpret exception types (delegates to `should_retry()`)

## Best Practices

### ✅ DO

1. **Let exceptions propagate** - Don't catch in `handle()` unless recovering
2. **Override `should_retry()` for custom logic** - Framework calls it
3. **Override `failed()` for cleanup** - Compensation, alerts, logging
4. **Use specific exception types** - Easier to distinguish in `should_retry()`
5. **Keep `failed()` idempotent** - It might be called multiple times (e.g., on worker restart)

### ❌ DON'T

1. **Don't catch all exceptions in `handle()`** - Defeats retry mechanism
2. **Don't raise exceptions in `failed()`** - They're logged but ignored
3. **Don't depend on `failed()` for critical logic** - It's best-effort
4. **Don't use `should_retry()` for side effects** - It's a decision function
5. **Don't retry indefinitely** - Set reasonable `max_retries`

## Configuration

### Task-Level Configuration

```python
class MyTask(AsyncTask[None]):
    queue = "high-priority"
    max_retries = 5          # Retry up to 5 times
    retry_delay = 120        # 2 minutes between retries
    timeout = 300            # 5-minute timeout per attempt
```

### Runtime Configuration

```python
task = MyTask(data="x")
task.on_queue("urgent").retry_after(60).dispatch()
```

## Observability

### Logging

All error events are logged with structured context:

```python
logger.error(
    "Task execution failed",
    extra={
        "task_id": task._task_id,
        "task_class": task.__class__.__name__,
        "attempt": task._attempts,
        "max_retries": task.config.max_retries,
        "exception_type": type(exception).__name__,
        "exception_message": str(exception),
    }
)
```

### Events (if enabled)

- `task_failed` - Emitted on each failure (includes retry status)
- `task_retry` - Emitted when task is re-queued
- `task_exhausted` - Emitted when retries exhausted

## Testing Error Handling

### Unit Test Example

```python
import pytest
from asynctasq.tasks.types import AsyncTask

class FailingTask(AsyncTask[None]):
    fail_count: int = 0
    
    async def handle(self) -> None:
        self.fail_count += 1
        if self.fail_count < 3:
            raise ConnectionError("Transient error")
        # Success on 3rd attempt

@pytest.mark.asyncio
async def test_task_retries():
    task = FailingTask()
    task.config.max_retries = 3
    
    # Simulate 3 execution attempts
    for attempt in range(1, 4):
        task._attempts = attempt
        if attempt < 3:
            with pytest.raises(ConnectionError):
                await task.execute()
        else:
            await task.execute()  # Succeeds on 3rd attempt
```

## Summary

| Component | Responsibility | Entry Points |
|-----------|---------------|-------------|
| **TaskExecutor** | Framework error handling, retry logic, timeout | `execute()`, `handle_failed()` |
| **BaseTask** | Business logic, custom error decisions | `handle()`, `should_retry()`, `failed()` |

**Key Principle:** Framework manages error recovery; users implement business logic and custom error decisions via hooks.
