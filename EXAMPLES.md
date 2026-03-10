# LLM Observability Proxy 使用示例

## 快速开始

### 1. 启动服务

```bash
# 进入项目目录
cd llm-observability-proxy

# 设置环境变量
export MASTER_API_KEY="my-secret-master-key"

# 启动服务
python -m src.main
```

或者使用 Docker:

```bash
cd docker
docker-compose up -d
```

服务将在 http://localhost:8000 启动

### 2. 创建 Provider Key

首先添加你的 LLM Provider API Key:

```bash
curl -X POST "http://localhost:8000/api/provider-keys" \
  -H "Authorization: Bearer my-secret-master-key" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My OpenAI Key",
    "provider": "openai",
    "api_key": "sk-your-openai-api-key-here"
  }'
```

响应:
```json
{
  "id": "uuid-here",
  "name": "My OpenAI Key",
  "provider": "openai",
  "created_at": "2024-01-01T00:00:00"
}
```

记住返回的 `id`，下一步会用到。

### 3. 创建 Proxy Key

为每个应用创建独立的 Proxy Key:

```bash
curl -X POST "http://localhost:8000/api/proxy-keys" \
  -H "Authorization: Bearer my-secret-master-key" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "MyApp-Production",
    "provider_key_id": "uuid-from-previous-step"
  }'
```

响应:
```json
{
  "id": "proxy-key-uuid",
  "name": "MyApp-Production",
  "proxy_key": "sk-helicone-proxy-abc123-uuid",
  "provider_key_id": "provider-key-uuid",
  "created_at": "2024-01-01T00:00:00"
}
```

**重要**: `proxy_key` 只会显示这一次！请妥善保存。

### 4. 使用 Proxy Key 调用 API

现在可以使用 Proxy Key 代替直接的 OpenAI Key:

#### Python 示例

```python
from openai import OpenAI

# 指向本地代理服务
client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="sk-helicone-proxy-abc123-uuid"  # 你的 Proxy Key
)

response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"}
    ]
)

print(response.choices[0].message.content)
```

#### cURL 示例

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-helicone-proxy-abc123-uuid" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [
      {"role": "user", "content": "Hello!"}
    ]
  }'
```

### 5. 查看请求记录

访问 Dashboard:
```
http://localhost:8000/dashboard
```

或者通过 API 查询:

```bash
# 获取所有请求
curl "http://localhost:8000/api/requests" \
  -H "Authorization: Bearer my-secret-master-key"

# 按应用统计
curl "http://localhost:8000/api/requests/stats/by-app" \
  -H "Authorization: Bearer my-secret-master-key"

# 按模型统计
curl "http://localhost:8000/api/requests/stats/by-model" \
  -H "Authorization: Bearer my-secret-master-key"

# 获取请求详情
curl "http://localhost:8000/api/requests/{request-id}" \
  -H "Authorization: Bearer my-secret-master-key"
```

## 多应用管理示例

### 为不同应用创建不同的 Proxy Key

```bash
# 应用 A - 生产环境
curl -X POST "http://localhost:8000/api/proxy-keys" \
  -H "Authorization: Bearer $MASTER_KEY" \
  -d '{"name": "AppA-Prod", "provider_key_id": "$PROVIDER_KEY_ID"}'

# 应用 A - 开发环境
curl -X POST "http://localhost:8000/api/proxy-keys" \
  -H "Authorization: Bearer $MASTER_KEY" \
  -d '{"name": "AppA-Dev", "provider_key_id": "$PROVIDER_KEY_ID"}'

# 应用 B - 生产环境
curl -X POST "http://localhost:8000/api/proxy-keys" \
  -H "Authorization: Bearer $MASTER_KEY" \
  -d '{"name": "AppB-Prod", "provider_key_id": "$PROVIDER_KEY_ID"}'
```

### 查看特定应用的使用情况

```bash
# 获取应用的使用统计
curl "http://localhost:8000/api/proxy-keys/{proxy-key-id}/usage" \
  -H "Authorization: Bearer $MASTER_KEY"
```

### 禁用某个应用的访问

```bash
curl -X DELETE "http://localhost:8000/api/proxy-keys/{proxy-key-id}" \
  -H "Authorization: Bearer $MASTER_KEY"
```

## API 参考

### 管理 API

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/provider-keys` | POST | 创建 Provider Key |
| `/api/provider-keys` | GET | 列出所有 Provider Keys |
| `/api/provider-keys/{id}` | DELETE | 删除 Provider Key |
| `/api/proxy-keys` | POST | 创建 Proxy Key |
| `/api/proxy-keys` | GET | 列出所有 Proxy Keys |
| `/api/proxy-keys/{id}` | GET | 获取 Proxy Key 详情 |
| `/api/proxy-keys/{id}` | DELETE | 删除 Proxy Key |
| `/api/proxy-keys/{id}/usage` | GET | 获取使用统计 |

### 查询 API

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/requests` | GET | 获取请求列表 |
| `/api/requests/{id}` | GET | 获取请求详情 |
| `/api/requests/stats/overview` | GET | 总体统计 |
| `/api/requests/stats/by-app` | GET | 按应用统计 |
| `/api/requests/stats/by-model` | GET | 按模型统计 |
| `/api/requests/stats/timeline` | GET | 时间趋势 |

### Proxy 端点

| 端点 | 方法 | 描述 |
|------|------|------|
| `/v1/{path}` | ALL | 代理到 LLM Provider |

## 环境变量

| 变量 | 描述 | 默认值 |
|------|------|--------|
| `MASTER_API_KEY` | 管理 API 的认证 Key | 必填 |
| `DATABASE_URL` | 数据库连接 | `sqlite:///./data/proxy.db` |
| `HOST` | 监听地址 | `0.0.0.0` |
| `PORT` | 监听端口 | `8000` |
| `LOG_LEVEL` | 日志级别 | `INFO` |
