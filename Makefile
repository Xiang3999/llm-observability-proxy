.PHONY: help install dev test lint type-check clean build docker-run docs

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install production dependencies
	pip install -r requirements.txt

dev: ## Install development dependencies
	pip install -e ".[dev]"

test: ## Run tests
	pytest tests/ -v

test-cov: ## Run tests with coverage
	pytest tests/ -v --cov=src --cov-report=html --cov-report=xml

lint: ## Run linter
	ruff check src/ tests/

format: ## Format code
	ruff format src/ tests/

type-check: ## Run type checker
	mypy src/ --ignore-missing-imports

clean: ## Clean build artifacts
	rm -rf build/ dist/ *.egg-info __pycache__/ .pytest_cache/ htmlcov/
	rm -rf .mypy_cache/ .ruff_cache/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

build: ## Build package
	pip install build
	python -m build

docker-build: ## Build Docker image
	docker build -f docker/Dockerfile -t llm-observability-proxy:latest .

docker-run: ## Run Docker container
	docker run -d --name llm-proxy \
		-p 8000:8000 \
		-v $(PWD)/data:/app/data \
		-e MASTER_API_KEY="your-master-key" \
		llm-observability-proxy:latest

docker-stop: ## Stop Docker container
	docker stop llm-proxy && docker rm llm-proxy

run: ## Run the application
	python -m src.main

migrate: ## Run database migrations
	@echo "Database migrations are applied automatically on startup."
	@echo "Migration files are in the migrations/ directory."
