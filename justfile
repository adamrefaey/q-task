# Start Docker services for testing
docker-up:
    docker-compose -f tests/infrastructure/docker-compose.yml up -d

# Stop Docker services
docker-down:
    docker-compose -f tests/infrastructure/docker-compose.yml down

# Clean up cache files and directories
clean:
    find . -type d -name "__pycache__" -exec rm -rf {} +
    find . -type d -name ".pytest_cache" -exec rm -rf {} +
    find . -type d -name "htmlcov" -exec rm -rf {} +
    find . -type d -name ".coverage" -exec rm -rf {} +
    find . -type d -name "*.egg-info" -exec rm -rf {} +
    find . -type f -name "*.pyc" -delete
    find . -type f -name "*.pyo" -delete
    find . -type f -name "*.cover" -delete
    find . -type f -name ".coverage" -delete
    find . -type f -name ".coverage.*" -delete

# Run all tests
test:
    uv run pytest

# Run unit tests only
test-unit:
    uv run pytest -m unit

# Run integration tests only (requires Docker services)
test-integration:
    uv run pytest -m integration

# Run all tests with coverage report
test-cov:
    uv run pytest --cov=async_task --cov-branch --cov-report=term-missing --cov-report=html

# Run unit tests with coverage
test-unit-cov:
    uv run pytest -m unit --cov=async_task --cov-branch --cov-report=term-missing --cov-report=html

# Run integration tests with coverage (requires Docker services)
test-integration-cov:
    uv run pytest -m integration --cov=async_task --cov-branch --cov-report=term-missing --cov-report=html

# Run a specific test file
test-file FILE:
    uv run pytest {{FILE}}

# Run tests matching a pattern
test-match PATTERN:
    uv run pytest -k {{PATTERN}}

# Run tests with Docker services up
test-with-docker:
    docker-compose -f tests/infrastructure/docker-compose.yml up -d
    uv run pytest
    docker-compose -f tests/infrastructure/docker-compose.yml down

# Run integration tests with Docker services
test-integration-docker:
    docker-compose -f tests/infrastructure/docker-compose.yml up -d
    uv run pytest -m integration
    docker-compose -f tests/infrastructure/docker-compose.yml down
