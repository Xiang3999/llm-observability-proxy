# LLM Observability Proxy

[![CI](https://github.com/Xiang3999/llm-observability-proxy/actions/workflows/ci.yml/badge.svg)](https://github.com/Xiang3999/llm-observability-proxy/actions/workflows/ci.yml)
[![Python Versions](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-purple)](https://github.com/astral-sh/ruff)

[🇨🇳 中文版 README](docs/README.zh-CN.md)

A lightweight LLM API proxy for monitoring and analyzing LLM API calls across different applications. Built with Python and FastAPI.

---

## 📑 Table of Contents

- [Features](#-features)
- [Quick Start](#-quick-start)
- [Usage](#-usage)
- [Architecture](#-architecture)
- [Core Modules](#-core-modules)
- [Configuration](#-configuration)
- [Semantic Cache](#-semantic-cache)
- [Development](#-development)
- [Contributing](#-contributing)
- [License](#-license)

## ✨ Features

- 🔍 **API Proxy** - Intercept and forward LLM API requests (supports OpenAI, Anthropic, etc.)
- 📊 **Request Recording** - Complete logging of request and response content for each API call
- ⏱️ **Latency Monitoring** - Track first token time, total latency, and other performance metrics
- 💰 **Token Statistics** - Automatic calculation of prompt/completion/total tokens
- 🔑 **Multi-Application Isolation** - Create independent API keys for different applications via Proxy Keys
- 📈 **Analytics** - Analyze usage by application, time range, model, and more
- 🎛️ **Web Dashboard** - Interactive web interface with chat-style conversation view, JSON/raw data inspection
- 🚀 **Semantic Cache** - Response caching based on semantic similarity (disabled by default, reduces redundant API calls)

## 🚀 Quick Start

### Run Locally (Recommended)

```bash
# Clone the repository
git clone https://github.com/Xiang3999/llm-observability-proxy.git
cd llm-observability-proxy

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
export MASTER_API_KEY="your-master-key"
export DATABASE_URL="sqlite:///./data/proxy.db"

# Start the service (foreground)
python -m src.main

# Or run in background
nohup python -m src.main > server.log 2>&1 &
```

Access the dashboard at http://localhost:8000

### Using Docker (Optional)

```bash
# Build Docker image locally
docker build -f docker/Dockerfile -t llm-observability-proxy:latest .

# Run the container
docker run -d --name llm-proxy \
  -p 8000:8000 \
  -v ./data:/app/data \
  -e MASTER_API_KEY="your-master-key" \
  llm-observability-proxy:latest
```

## 💡 Usage

### 1. Create a Proxy Key

```bash
curl -X POST http://localhost:8000/api/proxy-keys \
  -H "Authorization: Bearer your-master-key" \
  -H "Content-Type: application/json" \
  -d '{"name": "my-app", "provider": "openai", "provider_key": "sk-xxx"}'
```

### 2. Use Proxy Key to Call API

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="sk-proxy-key-xxx"  # Your Proxy Key
)

response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Hello!"}]
)
```

### 3. View Analytics Data

```bash
# Get all requests
curl http://localhost:8000/api/requests \
  -H "Authorization: Bearer your-master-key"

# Get stats by application
curl http://localhost:8000/api/stats/by-app \
  -H "Authorization: Bearer your-master-key"

# Get stats by model
curl http://localhost:8000/api/stats/by-model \
  -H "Authorization: Bearer your-master-key"
```

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Client Application                      │
│                 (Call API using Proxy Key)                   │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    API Proxy Server                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │  Auth &     │  │   Request   │  │   Response          │  │
│  │  Key Mgmt   │→ │  Recorder   │  │   Recorder          │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└─────────────────────────┬───────────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          │               │               │
          ▼               ▼               ▼
┌─────────────────┐ ┌─────────────┐ ┌─────────────┐
│   PostgreSQL    │ │   SQLite    │ │   File/     │
│   (Production)  │ │   (Dev)     │ │   SQLite    │
└─────────────────┘ └─────────────┘ └─────────────┘
```

## 📦 Core Modules

| Module | Description |
|--------|-------------|
| `src/proxy/` | API proxy core logic |
| `src/auth/` | Authentication and API Key management |
| `src/recorder/` | Request/Response recording |
| `src/analytics/` | Analytics and querying |
| `src/web/` | Web Dashboard |
| `src/models/` | Data models |

## ⚙️ Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `MASTER_API_KEY` | Master API Key for admin operations | Required |
| `DATABASE_URL` | Database connection URL | `sqlite:///./data/proxy.db` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `HOST` | Server bind address | `127.0.0.1` |
| `PORT` | Server port | `8000` |
| `CACHE_ENABLED` | Enable semantic cache | `false` |
| `CACHE_SIMILARITY_THRESHOLD` | Cache similarity threshold (0.0-1.0) | `0.95` |
| `CACHE_TTL_SECONDS` | Cache TTL in seconds | `3600` |
| `CACHE_MAX_SIZE` | Maximum cache entries | `10000` |

## 🧠 Semantic Cache

Semantic cache returns cached responses based on prompt semantic similarity, reducing redundant LLM API calls.

### Enable Cache

```bash
export CACHE_ENABLED=true
export CACHE_SIMILARITY_THRESHOLD=0.95  # Return cache if similarity > 95%
```

### How It Works

1. **On Request**: Calculate embedding vector of the request prompt
2. **Similarity Search**: Find semantically similar requests in cache
3. **Threshold Check**: Return cached response if similarity exceeds threshold
4. **Cache Response**: Cache LLM response on cache miss

### Cache Response Indicators

Cached responses include:
```json
{
  "cache_hit": true,
  "usage": {"cache_hit": true}
}
```

Response headers also include:
```
X-Cache-Hit: true
X-Cache-Similarity: 0.98
```

### Notes

- Currently uses hash-based pseudo-embedding (demo purpose)
- For production, replace with real embedding models (OpenAI embeddings, Sentence Transformers)
- Cache is stored in memory and lost on restart
- For production, consider using Redis or a dedicated vector database

## 🛠️ Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run tests
pytest tests/

# Lint code
ruff check src/

# Type check
mypy src/
```

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details on how to participate in the project.

- 🐛 [Report a Bug](https://github.com/Xiang3999/llm-observability-proxy/issues/new?template=bug_report.yml)
- 💡 [Suggest a Feature](https://github.com/Xiang3999/llm-observability-proxy/issues/new?template=feature_request.yml)
- 🔧 [Submit a PR](https://github.com/Xiang3999/llm-observability-proxy/pulls)

## 📄 License

MIT License - See [LICENSE](LICENSE) file for details.

## 🔗 Related Links

- [Architecture Documentation](ARCHITECTURE.md)
- [Usage Examples](EXAMPLES.md)
- [Changelog](CHANGELOG.md)
- [Code of Conduct](CODE_OF_CONDUCT.md)
- [Security Policy](SECURITY.md)
