# 流式请求 Usage / Cache 字段调试

## 如何打开调试日志

环境变量设置：

```bash
export LOG_LEVEL=DEBUG
```

或 `.env` 中：

```
LOG_LEVEL=DEBUG
```

然后重启 proxy，再发**流式**请求（例如 `stream: true` 的 chat/completions）。

## 会打出哪些日志

仅当 **LOG_LEVEL=DEBUG** 时，流式路径会多出三类日志，用于确认上游返回的 usage 结构（尤其是 cache 相关字段）。

### 1. `stream_sse_usage_chunk`

- **时机**：解析 SSE 时，每遇到一个 `data:` 事件里包含 `usage`、`prompt_tokens`、`input_tokens`、或包含 `cached_tokens` / `cache_creation` 的片段。
- **内容**：
  - `raw_obj`：该条 SSE 的**原始 JSON 对象**（上游返回的整条 event）。
  - `has_usage`：是否包含顶层 `usage`。
  - `usage_keys`：若有 `usage`，则列出其所有 key。
- **用途**：看 DashScope/Anthropic 等在**最后一条或某条** chunk 里到底塞了哪些字段（例如 `usage`、`prompt_tokens_details`、`completion_tokens_details`、`cached_tokens`、`cache_creation` 等），以及是顶层还是嵌套。

### 2. `stream_reconstructed_usage`

- **时机**：所有 chunk 解析完后，合并出「最终 usage」之后。
- **内容**：
  - `usage_final`：解析并 normalize 后的 **usage 字典**（即写入 DB 的 `response_body.usage` 的雏形）。
  - `usage_raw_keys`：合并前原始 usage 里出现过的 key。
- **用途**：确认我们最终认为的 prompt_tokens / completion_tokens / total_tokens 以及** cache 相关字段**（如 cache_read_tokens、cache_creation_tokens 或 prompt_tokens_details.cached_tokens 等）是否被正确合并进来。

### 3. `stream_update_log`

- **时机**：用解析结果去 **update 该流式请求的 request_log** 之前。
- **内容**：
  - `request_log_id`：被更新的请求 ID。
  - `response_usage`：即将写入的 **response_body.usage**（完整 usage 对象）。
  - `response_usage_keys`：usage 的所有 key。
  - `prompt_tokens_details`：usage 中的 `prompt_tokens_details`（通常含 cached_tokens、cache_creation 等）。
  - `completion_tokens_details`：usage 中的 `completion_tokens_details`。
- **用途**：确认**最终写入 DB 的 usage 长什么样**，以及 cache 相关是否在 `usage` 顶层或 `prompt_tokens_details` / `completion_tokens_details` 里，便于对照 DB 里 Cache Read Tokens / Cache Creation Tokens 的解析逻辑。

## 如何根据日志排查 Cache 显示为 `-`

1. 发一笔流式请求，并保证 **LOG_LEVEL=DEBUG**。
2. 在日志里搜 **stream_sse_usage_chunk**，看**最后一条**（或唯一一条）带 usage 的 chunk 的 `raw_obj`：
   - 看 `usage` 下是否有 `cache_read_input_tokens`、`cache_creation_input_tokens`。
   - 看是否有 `prompt_tokens_details`，其下是否有 `cached_tokens`、`cache_creation`、`cache_creation_input_tokens` 等。
3. 看 **stream_reconstructed_usage** 的 `usage_final`：上述 cache 相关字段是否被合并进来、key 是否一致。
4. 看 **stream_update_log** 的 `response_usage` 和 `prompt_tokens_details`：确认我们写入 DB 的 usage 和 details 是否包含这些字段。

若上游在 stream 的 usage 里**没有**带 cache 相关字段（例如 DashScope 某些模型/配置下不在 stream 最后一 chunk 里带），则 DB 里 Cache Read / Cache Creation 会保持为空，页面上就会显示 `-`；此时需要对照上游文档或联系上游确认「流式响应里是否返回 usage.cache_* / prompt_tokens_details.cached_tokens」等。
