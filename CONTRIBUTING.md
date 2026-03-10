# Contributing to LLM Observability Proxy

Thank you for your interest in contributing to LLM Observability Proxy! This document provides guidelines and instructions for contributing to the project.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [How to Contribute](#how-to-contribute)
  - [Reporting Bugs](#reporting-bugs)
  - [Suggesting Features](#suggesting-features)
  - [Code Contributions](#code-contributions)
- [Pull Request Guidelines](#pull-request-guidelines)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
- [Documentation](#documentation)

## Code of Conduct

This project adheres to the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code. Please report unacceptable behavior to [xiang49999@gmail.com](mailto:xiang49999@gmail.com).

## Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/your-username/llm-observability-proxy.git
   cd llm-observability-proxy
   ```
3. **Set up the development environment** (see below)
4. **Create a branch** for your contribution:
   ```bash
   git checkout -b feature/your-feature-name
   ```

## Development Setup

### Prerequisites

- Python 3.10 or higher
- pip
- Git

### Install Dependencies

```bash
# Create a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install in development mode
pip install -e ".[dev]"
```

### Run Tests

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ -v --cov=src --cov-report=html

# Run specific test file
pytest tests/unit/test_auth.py -v
```

### Code Quality

```bash
# Lint with ruff
ruff check src/ tests/

# Format with ruff
ruff format src/ tests/

# Type check with mypy
mypy src/ --ignore-missing-imports
```

## How to Contribute

### Reporting Bugs

Before creating bug reports, please check existing issues as you might find out that you don't need to create one. When you are creating a bug report, please include as many details as possible:

- Use a clear and descriptive title
- Describe the exact steps to reproduce the problem
- Provide specific examples to demonstrate the steps
- Describe the behavior you observed and what behavior you expected
- Include screenshots if applicable
- Include Python version, OS, and any relevant environment details

**Bug report template:**

```markdown
**Describe the bug**
A clear and concise description of what the bug is.

**To Reproduce**
Steps to reproduce the behavior:
1. Configure '...'
2. Run with '...'
3. See error

**Expected behavior**
A clear and concise description of what you expected to happen.

**Environment:**
- Python version: 3.11
- OS: macOS 14.0
- Project version: 0.1.0

**Additional context**
Add any other context about the problem here.
```

### Suggesting Features

Feature suggestions are always welcome! Please provide:

- Use a clear and descriptive title
- Describe the use case and why this feature would be valuable
- Provide examples of how the feature would be used
- Discuss any potential drawbacks or alternatives

### Code Contributions

1. **Find an issue** to work on or propose a new feature via discussion
2. **Comment on the issue** to let others know you're working on it
3. **Create a branch** from the main branch
4. **Make your changes** following the coding standards
5. **Write tests** for your changes
6. **Ensure all tests pass** before submitting
7. **Update documentation** if applicable
8. **Submit a pull request**

## Pull Request Guidelines

### Before Submitting

- [ ] My code follows the project's coding standards
- [ ] I have added tests for my changes
- [ ] All existing tests pass
- [ ] I have updated the documentation if needed
- [ ] My changes are covered by the existing test suite or new tests

### PR Description

Please include the following in your pull request description:

- What problem does this PR solve?
- How does it solve the problem?
- Are there any breaking changes?
- Link to any related issues

### Review Process

1. Maintainers will review your PR
2. Address any feedback or requested changes
3. Once approved, your PR will be merged

## Coding Standards

### Python Style

- Follow [PEP 8](https://pep8.org/) style guidelines
- Use [ruff](https://docs.astral.sh/ruff/) for linting
- Maximum line length is 88 characters (handled by ruff formatter)
- Use type hints where possible

### Code Organization

- Keep functions and modules focused and single-purpose
- Use descriptive variable and function names
- Add docstrings for public APIs
- Group related functionality together

### Example

```python
"""Module for handling API key authentication."""

from typing import Optional
from fastapi import HTTPException, status


async def validate_api_key(api_key: str) -> dict:
    """Validate an API key and return the associated proxy key.

    Args:
        api_key: The API key to validate.

    Returns:
        The proxy key configuration dict.

    Raises:
        HTTPException: If the API key is invalid.
    """
    proxy_key = await get_proxy_key(api_key)
    if proxy_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )
    return proxy_key
```

## Testing

### Writing Tests

- Write tests for all new features and bug fixes
- Use pytest for testing
- Follow the Arrange-Act-Assert pattern
- Mock external dependencies

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test category
pytest tests/unit/
pytest tests/integration/
```

## Documentation

### Updating Documentation

- Update README.md if user-facing features change
- Update ARCHITECTURE.md for significant architectural changes
- Add inline documentation for complex logic
- Update EXAMPLES.md with new usage examples

### Documentation Style

- Use clear, concise language
- Include code examples where applicable
- Keep documentation up to date with code changes

## Questions?

If you have any questions, please:

1. Check existing documentation
2. Search existing issues
3. Create a new issue for discussion

Thank you for contributing to LLM Observability Proxy! 🎉
