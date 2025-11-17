# Contributing to Async Task

Thank you for your interest in contributing to Async Task! We welcome contributions from the community.

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/yourusername/async-task.git`
3. Install dependencies with uv: `uv sync --all-extras --group dev`

## Development Workflow

### Setting Up Pre-commit Hooks

We use pre-commit hooks to ensure code quality:

```bash
pre-commit install
```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=async_task --cov-report=html

# Run specific test file
pytest tests/unit/test_task.py
```

### Code Style

We use `ruff` for linting and formatting:

```bash
# Check code style
ruff check src/ tests/

# Auto-fix issues
ruff check --fix src/ tests/
```

### Type Checking

We use `pyright` for type checking:

```bash
pyright src/
```

## Making Changes

1. Create a new branch: `git checkout -b feature/your-feature-name`
2. Make your changes
3. Add tests for your changes
4. Ensure all tests pass
5. Commit your changes: `git commit -m "Add feature: description"`
6. Push to your fork: `git push origin feature/your-feature-name`
7. Create a pull request

## Pull Request Guidelines

- Write clear, descriptive commit messages
- Include tests for new features
- Update documentation as needed
- Ensure all CI checks pass
- Reference any related issues

## Code Review Process

1. A maintainer will review your PR
2. Address any feedback or requested changes
3. Once approved, your PR will be merged

## Questions?

Feel free to open an issue for any questions or concerns.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
