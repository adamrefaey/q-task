# Default recipe to display help
default:
	@just --list

# Install package with all optional dependencies
install:
	uv sync --all-extras --group dev

# Setup pre-commit hooks
setup-hooks:
	uv run pre-commit install
	@echo "✅ Pre-commit hooks installed successfully!"

# Format code with Ruff
format:
	uv run ruff format .

# Auto-fix linting issues
lint-fix:
	uv run ruff check --fix .

# Type check with Pyright
typecheck:
	uv run pyright

# Run all CI checks locally (format, lint, typecheck, test)
ci: format lint-fix typecheck test
	@echo "✅ All CI checks passed!"

# Run pre-commit on all files
pre-commit:
	uv run pre-commit run --all-files

# Run pre-commit autoupdate
pre-commit-update:
	uv run pre-commit autoupdate

# Start Docker services for testing
docker-up:
	docker-compose -f tests/infrastructure/docker-compose.yml up -d
	@echo "✅ Docker services started"

# Stop Docker services
docker-down:
	docker-compose -f tests/infrastructure/docker-compose.yml down

# Restart Docker services
docker-restart:
	docker-compose -f tests/infrastructure/docker-compose.yml restart

# Clean up cache files and directories
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
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

# Show test coverage in browser
coverage-html: test-cov
	open htmlcov/index.html || xdg-open htmlcov/index.html

# Run tests with specific Python version
test-py VERSION:
	uv run --python {{VERSION}} pytest

# Run security checks with bandit
security:
	uv run bandit -r src/async_task -ll

# Run dependency security audit
audit:
	uv run pip-audit

# Show outdated dependencies
outdated:
	uv pip list --outdated

# Initialize project (install deps + setup hooks)
init: install setup-hooks
	@echo "✅ Project initialized successfully!"
	@echo "Run 'just services-up' to start Docker services"
	@echo "Run 'just test' to verify everything is working"

# Show ruff statistics
lint-stats:
	uv run ruff check --statistics .

# Profile tests (show slowest tests)
test-profile:
	uv run pytest --durations=10

# Run tests with verbose output
test-verbose:
	uv run pytest -vv

# Build the package
build:
	uv build

# Publish to PyPI (requires credentials)
publish:
	uv build
	uv publish

# Publish to Test PyPI
publish-test:
	uv build
	uv publish --index-url https://test.pypi.org/legacy/

# Generate coverage badge
coverage-badge:
	uv pip install coverage-badge
	uv run coverage-badge -o coverage.svg

# Type check with Pyright
pyright:
	uv pip install pyright
	uv run pyright

# Show project info
info:
	@echo "Project: async-task"
	@echo "Python: $(uv run python --version)"
	@echo "UV: $(uv --version)"
	@echo ""
	@echo "Run 'just --list' to see all available commands"
