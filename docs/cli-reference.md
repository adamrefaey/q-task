# CLI Reference

## Worker Command

Start a worker to process tasks from queues.

```bash
python -m asynctasq worker [OPTIONS]
```

**Options:**

| Option                          | Description                                  | Default                  |
| ------------------------------- | -------------------------------------------- | ------------------------ |
| `--driver DRIVER`               | Queue driver (redis/postgres/mysql/rabbitmq/sqs) | `redis`                  |
| `--queues QUEUES`               | Comma-separated queue names (priority order) | `default`                |
| `--concurrency N`               | Max concurrent tasks                         | `10`                     |
| `--redis-url URL`               | Redis connection URL                         | `redis://localhost:6379` |
| `--redis-password PASSWORD`     | Redis password                               | `None`                   |
| `--redis-db N`                  | Redis database number (0-15)                 | `0`                      |
| `--redis-max-connections N`     | Redis connection pool size                   | `10`                     |
| `--postgres-dsn DSN`            | PostgreSQL connection DSN                    | -                        |
| `--postgres-queue-table TABLE`  | PostgreSQL queue table name                  | `task_queue`             |
| `--postgres-dead-letter-table TABLE` | PostgreSQL dead letter table name       | `dead_letter_queue`      |
| `--mysql-dsn DSN`               | MySQL connection DSN                         | -                        |
| `--mysql-queue-table TABLE`     | MySQL queue table name                       | `task_queue`             |
| `--mysql-dead-letter-table TABLE` | MySQL dead letter table name               | `dead_letter_queue`      |
| `--sqs-region REGION`           | AWS SQS region                               | `us-east-1`              |
| `--sqs-queue-url-prefix PREFIX` | SQS queue URL prefix                         | -                        |
| `--aws-access-key-id KEY`       | AWS access key (optional)                    | -                        |
| `--aws-secret-access-key KEY`   | AWS secret key (optional)                    | -                        |

**Examples:**

```bash
# Basic usage
python -m asynctasq worker

# Multiple queues with priority
python -m asynctasq worker --queues high,default,low --concurrency 20

# Redis with auth
python -m asynctasq worker \
    --driver redis \
    --redis-url redis://localhost:6379 \
    --redis-password secret

# PostgreSQL worker
python -m asynctasq worker \
    --driver postgres \
    --postgres-dsn postgresql://user:pass@localhost/db

# MySQL worker
python -m asynctasq worker \
    --driver mysql \
    --mysql-dsn mysql://user:pass@localhost:3306/db

# SQS worker
python -m asynctasq worker \
    --driver sqs \
    --sqs-region us-west-2

# RabbitMQ worker
python -m asynctasq worker \
    --driver rabbitmq \
    --queues default,emails \
    --concurrency 5
```

---

## Migrate Command

Initialize database schema for PostgreSQL or MySQL drivers.

```bash
python -m asynctasq migrate [OPTIONS]
```

**Options:**

| Option                               | Description                | Default             |
| ------------------------------------ | -------------------------- | ------------------- |
| `--driver DRIVER`                    | Driver (postgres or mysql) | `postgres`          |
| `--postgres-dsn DSN`                 | PostgreSQL connection DSN  | -                   |
| `--postgres-queue-table TABLE`       | Queue table name           | `task_queue`        |
| `--postgres-dead-letter-table TABLE` | Dead letter table name     | `dead_letter_queue` |
| `--mysql-dsn DSN`                    | MySQL connection DSN       | -                   |
| `--mysql-queue-table TABLE`          | Queue table name           | `task_queue`        |
| `--mysql-dead-letter-table TABLE`    | Dead letter table name     | `dead_letter_queue` |

**Examples:**

```bash
# PostgreSQL migration (default)
python -m asynctasq migrate \
    --postgres-dsn postgresql://user:pass@localhost/db

# PostgreSQL with custom tables
python -m asynctasq migrate \
    --postgres-dsn postgresql://user:pass@localhost/db \
    --postgres-queue-table my_queue \
    --postgres-dead-letter-table my_dlq

# MySQL migration
python -m asynctasq migrate \
    --driver mysql \
    --mysql-dsn mysql://user:pass@localhost:3306/db

# Using environment variables
export asynctasq_POSTGRES_DSN=postgresql://user:pass@localhost/db
python -m asynctasq migrate
```

**What it does:**

- Creates queue table with optimized indexes
- Creates dead-letter table for failed tasks
- Idempotent (safe to run multiple times)
- Only works with PostgreSQL and MySQL drivers
