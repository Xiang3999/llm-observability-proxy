# 语义缓存功能说明

## 概述

语义缓存（Semantic Cache）是 LLM Observability Proxy 的一个可选功能，用于基于请求的语义相似度返回缓存的响应，从而减少重复的 LLM API 调用，降低成本和延迟。

**默认状态：关闭**

## 工作原理

```
请求到来 → 计算 Prompt 嵌入向量 → 搜索相似缓存 → 相似度判断
    ↓                                              ↓
  调用 LLM API                                  返回缓存响应
    ↓                                              ↓
  记录响应到数据库                              记录缓存命中
    ↓
  缓存响应（如果启用）
```

## 启用缓存

### 方法 1：环境变量

```bash
export CACHE_ENABLED=true
export CACHE_SIMILARITY_THRESHOLD=0.95
export CACHE_TTL_SECONDS=3600
export CACHE_MAX_SIZE=10000
```

### 方法 2：修改 .env 文件

```bash
# 复制示例配置
cp .env.example .env

# 编辑 .env 文件
CACHE_ENABLED=true
CACHE_SIMILARITY_THRESHOLD=0.95
```

### 方法 3：代码中配置

```python
from src.cache.semantic_cache import SemanticCache

cache = SemanticCache(
    enabled=True,
    similarity_threshold=0.95,
    ttl_seconds=3600,
    max_size=10000
)
```

## 配置参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `CACHE_ENABLED` | bool | `false` | 是否启用缓存 |
| `CACHE_SIMILARITY_THRESHOLD` | float | `0.95` | 相似度阈值 (0.0-1.0) |
| `CACHE_TTL_SECONDS` | int | `3600` | 缓存过期时间（秒） |
| `CACHE_MAX_SIZE` | int | `10000` | 最大缓存条目数 |

### 相似度阈值说明

- **1.0**: 仅完全匹配才命中缓存
- **0.95**: 非常相似的请求命中缓存（推荐）
- **0.80**: 较为相似的请求也能命中
- **0.50**: 宽松的缓存策略

阈值越高，缓存命中率越低，但返回结果越准确。

## 缓存响应标识

### 响应头

缓存命中的响应会包含以下 HTTP 头：

```
X-Cache-Hit: true
X-Cache-Similarity: 0.98
```

### 响应体

```json
{
  "id": "cache-gpt-4o-mini-1234567890",
  "object": "chat.completion",
  "created": 1234567890,
  "model": "gpt-4o-mini",
  "choices": [{
    "index": 0,
    "message": {
      "role": "assistant",
      "content": "Cached response content"
    },
    "finish_reason": "stop"
  }],
  "usage": {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "cache_hit": true
  },
}
```

## 查看缓存统计

### API 方式

```bash
# 缓存统计（需要添加 API 端点）
curl http://localhost:8000/api/cache/stats \
  -H "Authorization: Bearer your-master-key"
```

### 代码方式

```python
from src.proxy.routes import get_semantic_cache

cache = get_semantic_cache()
stats = cache.get_stats()

print(f"Hits: {stats['hits']}")
print(f"Misses: {stats['misses']}")
print(f"Hit Rate: {stats['hit_rate']:.2%}")
print(f"Vector Store Stats: {stats['vector_store']}")
```

## 清除缓存

```python
from src.proxy.routes import get_semantic_cache

cache = get_semantic_cache()
cleared = cache.clear()
print(f"Cleared {cleared} entries")
```

## 清理过期缓存

```python
from src.proxy.routes import get_semantic_cache

cache = get_semantic_cache()
removed = cache.cleanup()
print(f"Removed {removed} expired entries")
```

## 演示脚本

运行演示脚本查看缓存如何工作：

```bash
python demo_cache.py
```

## 当前实现限制

### 嵌入生成器

当前使用的是**基于哈希的伪嵌入**（`HashEmbeddingGenerator`）：

- ✅ 确定性输出（相同输入产生相同向量）
- ✅ 无需外部 API
- ❌ **不捕获语义含义**（仅用于演示）

### 生产环境建议

对于生产环境，建议替换为真实的嵌入模型：

```python
# 示例：使用 OpenAI Embeddings
from openai import OpenAI

class OpenAIEmbeddingGenerator:
    def __init__(self, model="text-embedding-3-small"):
        self.client = OpenAI()
        self.model = model

    def generate(self, text: str) -> list[float]:
        response = self.client.embeddings.create(
            input=text,
            model=self.model
        )
        return response.data[0].embedding
```

其他选项：
- **Sentence Transformers** (`all-MiniLM-L6-v2`) - 本地运行
- **Cohere Embeddings** - 高质量商业 API
- **Jina Embeddings** - 开源选择

### 向量存储

当前使用的是**内存存储**（`InMemoryVectorStore`）：

- ✅ 简单、无需额外服务
- ❌ 重启后数据丢失
- ❌ 不适合大规模数据

生产环境建议使用：
- **FAISS** (Facebook AI Similarity Search)
- **ChromaDB**
- **Qdrant**
- **Pinecone**
- **Redis Stack** (带向量搜索)

## 测试

运行缓存相关测试：

```bash
# 语义缓存测试
pytest tests/unit/test_cache.py -v

# 向量存储测试
pytest tests/unit/test_vector_store.py -v

# 所有单元测试
pytest tests/unit/ -v
```

## 文件结构

```
src/cache/
├── __init__.py           # 模块导出
├── semantic_cache.py     # 语义缓存核心逻辑
├── vector_store.py       # 向量存储（内存实现）
└── embedding.py          # 嵌入生成器

tests/unit/
├── test_cache.py         # 缓存测试
└── test_vector_store.py  # 向量存储测试
```

## 性能考虑

### 缓存命中收益

| 场景 | 延迟 | 成本 |
|------|------|------|
| 缓存命中 | ~1ms | $0 |
| 缓存未命中 | ~500-3000ms | 正常 API 费用 |

### 适用场景

- ✅ 常见问题回答
- ✅ 标准化查询
- ✅ 高重复性请求
- ❌ 创意性/多样性内容
- ❌ 实时数据查询
- ❌ 个性化内容

## 最佳实践

1. **从低流量开始**：先在低流量环境测试，调整相似度阈值
2. **监控命中率**：理想命中率在 20-50% 之间
3. **定期清理**：设置合适的 TTL，避免缓存过大
4. **A/B 测试**：对比缓存与真实响应的质量
5. **分类缓存**：对不同模型/场景使用不同的缓存策略

## 故障排除

### 缓存不生效

1. 检查 `CACHE_ENABLED=true`
2. 确认相似度阈值是否过高
3. 检查日志中的缓存命中信息

### 缓存命中率过低

1. 降低 `CACHE_SIMILARITY_THRESHOLD`
2. 分析请求模式，确认是否存在重复请求
3. 考虑使用更好的嵌入模型

### 内存占用过高

1. 减小 `CACHE_MAX_SIZE`
2. 降低 `CACHE_TTL_SECONDS`
3. 考虑使用外部向量数据库

## 未来改进

- [ ] 集成真实嵌入模型（OpenAI、Sentence Transformers）
- [ ] 支持 Redis 作为向量存储后端
- [ ] 添加缓存预热功能
- [ ] 支持增量更新缓存
- [ ] 添加缓存命中率监控告警
