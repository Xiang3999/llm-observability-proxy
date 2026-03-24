# LLM Observability Proxy

[![CI](https://github.com/Xiang3999/llm-observability-proxy/actions/workflows/ci.yml/badge.svg)](https://github.com/Xiang3999/llm-observability-proxy/actions/workflows/ci.yml)
[![Python Versions](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-purple)](https://github.com/astral-sh/ruff)

[🇺🇸 English README](../README.md)

一个用 Python 编写的轻量级 LLM API 代理监控系统，用于观察和分析不同应用对 LLM API 的调用情况。

---

## 📑 目录

- [功能特性](#-功能特性)
- [快速开始](#-快速开始)
- [使用方式](#-使用方式)
- [架构设计](#-架构设计)
- [核心模块](#-核心模块)
- [配置项](#-配置项)
- [语义缓存](#-语义缓存)
- [开发](#-开发)
- [贡献](#-贡献)
- [License](#-license)

## ✨ 功能特性

- 🔍 **API 代理** - 拦截和转发 LLM API 请求（支持 OpenAI、Anthropic 等）
- 📊 **请求记录** - 完整记录每个 API 调用的请求和响应内容
- ⏱️ **延迟监控** - 记录首 Token 时间、总延迟等性能指标
- 💰 **Token 统计** - 自动计算 prompt/completion/total tokens
- 🔑 **多应用隔离** - 通过 Proxy Key 为不同应用创建独立的 API Key
- 📈 **分析查询** - 按应用、时间、模型等维度分析使用情况
- 🎛️ **Web Dashboard** - 交互式 Web 界面，支持对话式消息展示、JSON/原始数据查看、角色筛选等功能
- 🚀 **语义缓存** - 基于语义相似度的响应缓存（默认关闭，可减少重复 API 调用）

## 🚀 快速开始

### 本地运行（推荐）

```bash
# 克隆仓库
git clone https://github.com/Xiang3999/llm-observability-proxy.git
cd llm-observability-proxy

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
export MASTER_API_KEY="your-master-key"
export DATABASE_URL="sqlite:///./data/proxy.db"

# 启动服务（前台运行）
python -m src.main

# 或后台运行
nohup python -m src.main > server.log 2>&1 &
```

访问 http://localhost:8000 查看 Dashboard

### 使用 Docker（可选）

```bash
# 本地构建 Docker 镜像
docker build -f docker/Dockerfile -t llm-observability-proxy:latest .

# 运行容器
docker run -d --name llm-proxy \
  -p 8000:8000 \
  -v ./data:/app/data \
  -e MASTER_API_KEY="your-master-key" \
  llm-observability-proxy:latest
```

## 💡 使用方式

### 1. 创建 Proxy Key

```bash
curl -X POST http://localhost:8000/api/proxy-keys \
  -H "Authorization: Bearer your-master-key" \
  -H "Content-Type: application/json" \
  -d '{"name": "my-app", "provider": "openai", "provider_key": "sk-xxx"}'
```

### 2. 使用 Proxy Key 调用 API

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="sk-proxy-key-xxx"  # 你的 Proxy Key
)

response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Hello!"}]
)
```

### 3. 查看分析数据

```bash
# 获取所有请求
curl http://localhost:8000/api/requests \
  -H "Authorization: Bearer your-master-key"

# 按应用统计
curl http://localhost:8000/api/stats/by-app \
  -H "Authorization: Bearer your-master-key"

# 按模型统计
curl http://localhost:8000/api/stats/by-model \
  -H "Authorization: Bearer your-master-key"
```

## 🏗️ 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                      Client Application                      │
│                 (使用 Proxy Key 调用 API)                      │
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
│   (生产环境)    │ │   (开发)    │ │   SQLite    │
└─────────────────┘ └─────────────┘ └─────────────┘
```

## 📦 核心模块

| 模块 | 说明 |
|------|------|
| `src/proxy/` | API 代理核心逻辑 |
| `src/auth/` | 认证和 API Key 管理 |
| `src/recorder/` | 请求/响应记录 |
| `src/analytics/` | 分析和查询 |
| `src/web/` | Web Dashboard |
| `src/models/` | 数据模型 |

## ⚙️ 配置项

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `MASTER_API_KEY` | 管理 API Key | 必填 |
| `DATABASE_URL` | 数据库连接 | `sqlite:///./data/proxy.db` |
| `LOG_LEVEL` | 日志级别 | `INFO` |
| `HOST` | 监听地址 | `127.0.0.1` |
| `PORT` | 监听端口 | `8000` |
| `CACHE_ENABLED` | 是否启用语义缓存 | `false` |
| `CACHE_SIMILARITY_THRESHOLD` | 缓存相似度阈值 (0.0-1.0) | `0.95` |
| `CACHE_TTL_SECONDS` | 缓存过期时间 (秒) | `3600` |
| `CACHE_MAX_SIZE` | 最大缓存条目数 | `10000` |

## 🧠 语义缓存

语义缓存功能可以基于请求的语义相似度返回缓存的响应，减少重复的 LLM API 调用。

### 启用缓存

```bash
export CACHE_ENABLED=true
export CACHE_SIMILARITY_THRESHOLD=0.95  # 相似度超过 95% 返回缓存
```

### 缓存工作原理

1. **请求到来时**：计算请求 prompt 的嵌入向量
2. **相似度搜索**：在缓存中查找语义相似的请求
3. **阈值判断**：相似度超过阈值则返回缓存响应
4. **响应缓存**：未命中时将 LLM 响应缓存

### 缓存响应标识

缓存命中的响应会包含以下标识：
```json
{
  "cache_hit": true,
  "usage": {"cache_hit": true}
}
```

响应头也会包含：
```
X-Cache-Hit: true
X-Cache-Similarity: 0.98
```

### 注意事项

- 当前使用基于 hash 的伪嵌入（演示用途）
- 生产环境建议替换为真实嵌入模型（如 OpenAI embeddings、Sentence Transformers）
- 缓存数据存储在内存中，重启后丢失
- 生产环境建议使用 Redis 或专用向量数据库

## 🛠️ 开发

```bash
# 安装依赖
pip install -r requirements.txt

# 运行测试
pytest tests/

# 代码检查
ruff check src/

# 类型检查
mypy src/
```

## 🤝 贡献

我们欢迎各种形式的贡献！请查看我们的 [贡献指南](../CONTRIBUTING.md) 了解如何参与项目开发。

- 🐛 [报告问题](https://github.com/Xiang3999/llm-observability-proxy/issues/new?template=bug_report.yml)
- 💡 [建议功能](https://github.com/Xiang3999/llm-observability-proxy/issues/new?template=feature_request.yml)
- 🔧 [提交 PR](https://github.com/Xiang3999/llm-observability-proxy/pulls)

## 📄 License

MIT License - 查看 [LICENSE](../LICENSE) 文件了解详情。

## 🔗 相关链接

- [架构文档](../ARCHITECTURE.md)
- [使用示例](../EXAMPLES.md)
- [变更日志](../CHANGELOG.md)
- [行为准则](../CODE_OF_CONDUCT.md)
- [安全政策](../SECURITY.md)
