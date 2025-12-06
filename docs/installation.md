# Installation

## Requirements

- **Python 3.12+** (required)

## Using uv (Recommended)

[uv](https://github.com/astral-sh/uv) is a fast Python package installer and resolver.

```bash
# Basic installation
uv add asynctasq

# With specific drivers
uv add "asynctasq[redis]"      # Redis support
uv add "asynctasq[postgres]"   # PostgreSQL support
uv add "asynctasq[mysql]"      # MySQL support
uv add "asynctasq[rabbitmq]"   # RabbitMQ support
uv add "asynctasq[sqs]"        # AWS SQS support

# With ORM support
uv add "asynctasq[sqlalchemy]" # SQLAlchemy
uv add "asynctasq[django]"     # Django
uv add "asynctasq[tortoise]"   # Tortoise ORM

# With framework integrations
uv add "asynctasq[fastapi]"    # FastAPI integration

# With monitoring support (real-time events)
uv add "asynctasq[monitor]"    # Redis Pub/Sub for events

# Complete installation with all features
uv add "asynctasq[all]"
```

## Using pip

```bash
# Basic installation
pip install asynctasq

# With specific drivers
pip install "asynctasq[redis]"
pip install "asynctasq[postgres]"
pip install "asynctasq[mysql]"
pip install "asynctasq[rabbitmq]"
pip install "asynctasq[sqs]"

# With ORM support
pip install "asynctasq[sqlalchemy]"
pip install "asynctasq[django]"
pip install "asynctasq[tortoise]"

# With framework integrations
pip install "asynctasq[fastapi]"

# With monitoring support
pip install "asynctasq[monitor]"

# Complete installation
pip install "asynctasq[all]"
```
