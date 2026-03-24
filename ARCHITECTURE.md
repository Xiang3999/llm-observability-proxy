# 系统架构设计文档

## 1. 项目概述

LLM Observability Proxy 是一个轻量级的 LLM API 代理监控系统，用于观察和分析不同应用对 LLM API 的调用情况。

### 1.1 核心目标

- 通过 API Proxy 拦截所有 LLM API 调用
- 记录完整的请求和响应内容
- 监控性能指标（延迟、Token 使用等）
- 支持多应用隔离（通过 Proxy Key）
- 提供分析查询能力

---

## 2. 功能需求

### 2.1 API Proxy 功能

| 功能 | 描述 | 优先级 |
|------|------|--------|
| 请求拦截 | 拦截 OpenAI、Anthropic 等 LLM API 请求 | P0 |
| 请求转发 | 将请求转发到真实的 LLM Provider | P0 |
| 响应接收 | 接收并记录 Provider 返回的响应 | P0 |
| Key 替换 | 将 Proxy Key 替换为真实的 Provider Key | P0 |
| 流式支持 | 支持 SSE 流式响应 | P0 |
| 错误处理 | 处理超时、错误等情况 | P1 |
| 重试机制 | 支持请求重试 | P2 |

### 2.2 记录功能

| 功能 | 描述 | 优先级 |
|------|------|--------|
| 请求记录 | 记录完整的请求 Body、Headers | P0 |
| 响应记录 | 记录完整的响应 Body、Status | P0 |
| 时间戳 | 记录请求/响应时间 | P0 |
| 延迟计算 | 计算总延迟、首 Token 时间 | P0 |
| Token 统计 | 计算 prompt/completion/total tokens | P0 |
| 成本计算 | 根据模型计算成本 | P1 |

### 2.3 认证和 Key 管理

| 功能 | 描述 | 优先级 |
|------|------|--------|
| Master Key | 管理界面的认证 | P0 |
| Proxy Key 生成 | 为应用生成唯一的 Proxy Key | P0 |
| Key 映射 | Proxy Key → Provider Key 映射 | P0 |
| Key 限额 | 设置 Key 的使用限额 | P1 |
| Key 统计 | 查看每个 Key 的使用情况 | P1 |

### 2.4 分析查询

| 功能 | 描述 | 优先级 |
|------|------|--------|
| 请求列表 | 查询所有请求记录 | P0 |
| 按应用过滤 | 按 Proxy Key 过滤请求 | P0 |
| 时间范围 | 按时间范围查询 | P0 |
| 统计分析 | Token、成本、延迟统计 | P0 |
| 趋势图表 | 使用趋势图表 | P1 |
| 错误分析 | 错误率分析 | P2 |

---

## 3. 系统架构

### 3.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        Client Applications                       │
│          (App1, App2, App3... 使用不同的 Proxy Key)               │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             │ HTTP/HTTPS
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      API Proxy Server                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │   FastAPI    │  │   Proxy      │  │   Request/Response   │   │
│  │   Server     │  │   Handler    │  │   Recorder           │   │
│  │   (8000)     │  │              │  │                      │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │   Auth &     │  │   Analytics  │  │   Web                │   │
│  │   Key Mgmt   │  │   & Query    │  │   Dashboard          │   │
│  │              │  │              │  │                      │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                             │
                             │ HTTP
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                     LLM Providers                                │
│         OpenAI        Anthropic        Gemini        ...        │
└─────────────────────────────────────────────────────────────────┘

Data Storage:
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  SQLite     │    │  MinIO/S3   │    │  Redis      │
│  (Metadata) │    │  (Bodies)   │    │  (Cache)    │
└─────────────┘    └─────────────┘    └─────────────┘
```

### 3.2 请求处理流程

```
1. Client 发送请求到 Proxy
   Authorization: Bearer sk-proxy-xxx

2. Proxy 验证 Proxy Key
   - 从数据库查询 Proxy Key 对应的真实 Provider Key
   - 验证 Key 是否有效、是否超出限额

3. Proxy 转发请求到 Provider
   - 替换 Authorization Header 为真实 Key
   - 记录请求开始时间

4. Provider 返回响应
   - 记录响应时间
   - 计算延迟
   - 提取 Token 使用量

5. 存储记录
   - 请求/响应 Body 存储到 S3/SQLite
   - 元数据存储到数据库

6. 返回响应给 Client
```

---

## 4. 数据模型设计

### 4.1 核心表结构

```sql
-- Proxy Keys 表
CREATE TABLE proxy_keys (
    id UUID PRIMARY KEY,
    name VARCHAR(255) NOT NULL,          -- Key 名称（应用名）
    proxy_key_hash VARCHAR(255) NOT NULL, -- Proxy Key 哈希
    provider VARCHAR(50) NOT NULL,        -- Provider 类型
    provider_key_id UUID NOT NULL,        -- 关联的 Provider Key
    created_at TIMESTAMP DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE
);

-- Provider Keys 表
CREATE TABLE provider_keys (
    id UUID PRIMARY KEY,
    name VARCHAR(255) NOT NULL,          -- Key 名称
    provider VARCHAR(50) NOT NULL,       -- Provider 类型
    encrypted_key TEXT NOT NULL,         -- 加密后的真实 Key
    created_at TIMESTAMP DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE
);

-- 请求记录表
CREATE TABLE requests (
    id UUID PRIMARY KEY,
    proxy_key_id UUID NOT NULL,          -- 关联的 Proxy Key
    request_path VARCHAR(500),           -- 请求路径
    model VARCHAR(100),                  -- 使用的模型
    status_code INTEGER,                 -- 响应状态码

    -- Token 统计
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,

    -- 延迟统计
    total_latency_ms INTEGER,
    time_to_first_token_ms INTEGER,

    -- 时间
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,

    -- 存储位置
    request_body_path VARCHAR(500),
    response_body_path VARCHAR(500),

    -- 成本
    cost_usd DECIMAL(10, 6)
);

-- 限额配置表
CREATE TABLE rate_limits (
    id UUID PRIMARY KEY,
    proxy_key_id UUID NOT NULL,
    time_window_seconds INTEGER,
    max_requests INTEGER,
    max_cost_usd DECIMAL(10, 2),
    current_requests INTEGER DEFAULT 0,
    current_cost_usd DECIMAL(10, 2) DEFAULT 0,
    reset_at TIMESTAMP
);
```

---

## 5. API 设计

### 5.1 Proxy 端点

```
POST /v1/chat/completions     - OpenAI 兼容的聊天接口
POST /v1/completions          - OpenAI 兼容的完成接口
POST /v1/embeddings           - OpenAI 兼容的嵌入接口
```

### 5.2 管理 API

```
# Proxy Key 管理
POST   /api/proxy-keys         - 创建 Proxy Key
GET    /api/proxy-keys         - 获取所有 Proxy Key
DELETE /api/proxy-keys/:id     - 删除 Proxy Key

# 请求记录查询
GET    /api/requests           - 获取请求列表
GET    /api/requests/:id       - 获取请求详情
GET    /api/requests/:id/body  - 获取请求/响应 Body

# 统计分析
GET    /api/stats/overview     - 总体统计
GET    /api/stats/by-app       - 按应用统计
GET    /api/stats/by-model     - 按模型统计
GET    /api/stats/timeline     - 时间趋势
```

---

## 6. 技术选型

### 6.1 后端框架

- **FastAPI** - 高性能 async Web 框架
- **Uvicorn** - ASGI 服务器

### 6.2 数据存储

- **SQLite** - 开发环境，存储元数据
- **PostgreSQL** - 生产环境，存储元数据
- **MinIO/S3** - 存储请求/响应 Body

### 6.3 认证

- **API Key** - 简单高效的认证方式
- **bcrypt** - Key 哈希存储

### 6.4 其他

- **SQLAlchemy** - ORM
- **Pydantic** - 数据验证
- **structlog** - 结构化日志

---

## 7. 目录结构

```
llm-observability-proxy/
├── src/
│   ├── __init__.py
│   ├── config.py           # 配置管理
│   ├── main.py             # 应用入口
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── database.py     # 数据库连接
│   │   ├── proxy_key.py    # Proxy Key 模型
│   │   ├── request.py      # Request 模型
│   │   └── provider_key.py # Provider Key 模型
│   │
│   ├── proxy/
│   │   ├── __init__.py
│   │   ├── handler.py      # 请求处理
│   │   ├── forwarder.py    # 请求转发
│   │   └── parser.py       # 请求/响应解析
│   │
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── middleware.py   # 认证中间件
│   │   ├── key_manager.py  # Key 管理
│   │   └── validator.py    # Key 验证
│   │
│   ├── recorder/
│   │   ├── __init__.py
│   │   ├── recorder.py     # 记录器
│   │   └── storage.py      # 存储后端
│   │
│   ├── analytics/
│   │   ├── __init__.py
│   │   ├── query.py        # 查询逻辑
│   │   └── stats.py        # 统计逻辑
│   │
│   └── web/
│       ├── __init__.py
│       ├── routes.py       # Web 路由
│       └── templates/      # HTML 模板
│
├── tests/
│   ├── unit/               # 单元测试
│   └── integration/        # 集成测试
│
├── docker/
│   └── Dockerfile
│
├── requirements.txt
├── .env.example
└── README.md
```

---

## 8. 部署方案

### 8.1 Docker Compose

```yaml
version: '3.8'
services:
  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:pass@db:5432/llm_proxy
      - MASTER_API_KEY=your-key
    depends_on:
      - db

  db:
    image: postgres:15
    volumes:
      - pgdata:/var/lib/postgresql/data
    environment:
      - POSTGRES_DB=llm_proxy
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=pass

  minio:
    image: minio/minio
    command: server /data
    ports:
      - "9000:9000"
    volumes:
      - miniodata:/data

volumes:
  pgdata:
  miniodata:
```

---

## 9. 安全考虑

1. **Key 存储**: 所有 Key 使用 bcrypt 哈希存储
2. **传输加密**: 生产环境使用 HTTPS
3. **访问控制**: 管理 API 需要 Master Key 认证
4. **数据隔离**: 不同应用的请求通过 Proxy Key 隔离

---

## 10. 性能优化

1. **异步处理**: 所有 I/O 操作使用 async
2. **缓存**: Redis 缓存 Key 验证结果
3. **批量写入**: 请求记录批量写入数据库
4. **存储分离**: Body 存储到对象存储，减轻数据库压力
