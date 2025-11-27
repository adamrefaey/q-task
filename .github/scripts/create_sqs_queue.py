#!/usr/bin/env python3
"""Create the LocalStack SQS queue used by integration tests.

This script assumes LocalStack is reachable at the endpoint provided
by the `LOCALSTACK_ENDPOINT` environment variable (defaults to http://127.0.0.1:4566).
"""

import os

import boto3


def main() -> int:
    endpoint = os.environ.get("LOCALSTACK_ENDPOINT", "http://127.0.0.1:4566")
    queue_name = os.environ.get("LOCALSTACK_QUEUE_NAME", "test-queue")

    client = boto3.client(
        "sqs",
        endpoint_url=endpoint,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
    )

    print(f"Creating SQS queue {queue_name} at {endpoint}...")
    client.create_queue(QueueName=queue_name)
    print("Created SQS queue")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
