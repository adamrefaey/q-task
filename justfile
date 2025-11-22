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
