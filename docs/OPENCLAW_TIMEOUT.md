# OpenClaw 使用 Proxy 时出现 "LLM request timed out"

## 现象

在 `~/.openclaw` 中配置 bailian 使用 proxy（`baseUrl: "http://localhost:8000/v1"`）时，经常出现 **"LLM request timed out."**。

## 如何调查报错原因（先看 Proxy 日志）

Proxy 已加上请求级诊断日志，**先复现一次超时，同时看 proxy 控制台输出**，即可判断时间耗在哪儿：

1. **认证是否拖慢首包**
   - 若出现 `auth cache miss db_lookup_ms=...` 且数值很大（例如 >1000）：说明第一次用该 key 时查 DB 很慢，可能 SQLite 锁或 IO 慢。
   - 若只有 `auth cache hit`（DEBUG 级别）或没有 auth 相关日志：认证不是瓶颈。

2. **上游是否迟迟不返回 HTTP 头**
   - 若在「超时前」出现 `upstream headers received path=chat/completions status=200 elapsed_ms=...`：说明上游在 elapsed_ms 内就回了头，**首包慢在 OpenClaw 与 Proxy 之间**（例如 OpenClaw 侧超时太短、或网络问题）。
   - 若在超时时刻出现 `stream timeout waiting for upstream headers path=... elapsed_ms=...`：说明**上游在 proxy 等待期内一直没返回 HTTP 头**，瓶颈在上游或「Proxy → 上游」网络/配置（如 base_url、模型名错误导致上游挂起）。

3. **上游是否报错**
   - 若出现 `stream worker error path=... after_ms=... error=...`：上游在 after_ms 后抛错（如 401、502、连接失败），可根据 error 内容排查 base_url、provider key、模型名等。

**建议**：用 `openclaw agent --local -m "只回复OK"` 触发一次请求，把 proxy 从收到请求到报错/成功这段时间的日志贴出来，按上面三点对号入座即可定位是「认证慢」「上游慢/挂起」还是「上游报错」。

### 根因（已修复）

- **直连**：OpenClaw 以 **chunked / 流式** 发请求体，上游边收边处理，大请求也能在数秒内返回头。
- **经 proxy（修复前）**：Proxy 用 `await request.json()` 收完整 body，再用 `json=body` **一次性** 发给上游；上游按「整块大 body」处理，迟迟不返回 HTTP 头（>120s），导致 OpenClaw 报 "LLM request timed out"。
- **修复**：流式请求时改为用 **chunked 转发请求体**（`content=_stream_body_chunks(body)`），与直连行为一致；修复后同一大请求经 proxy 约 1.9s 收到上游头，总耗时约 3s，不再超时。

## 原因（现象层面）

- 报错来自 OpenClaw 客户端对**单次 LLM HTTP 请求**的超时（如 `withTimeout` / `fetchWithTimeout`）。
- 单次请求的超时时间由**各端实现/配置**决定；部分构建（如 `@qingchencloud/openclaw-zh`）的 provider 配置**不支持** `timeoutSeconds`，因此会使用较短默认值（例如约 60s 或更短）。
- 请求路径为：**OpenClaw → Proxy → 上游**。若「首包时间」或「整次请求时间」超过客户端单次请求超时，就会报 "LLM request timed out"。

## 已做验证

- 使用 `openclaw agent --local --agent main -m "只回复一个词：OK"` 可稳定复现。
- 使用相同 proxy key、对 proxy 直接发小 body 或约 24k 的 body，TTFB 约 2.5–3s，说明 **proxy 与上游本身可在数秒内返回**。
- 因此更可能是：**OpenClaw 侧单次 LLM 请求超时过短**，或在某些场景下（大 prompt、冷启动等）首包超过该超时。

## 可采取的缓解措施

1. **拉长 proxy 侧上游超时（避免 proxy 先超时）**  
   在 proxy 中已支持 `UPSTREAM_TIMEOUT_SECONDS`（默认 120s），例如：
   ```bash
   export UPSTREAM_TIMEOUT_SECONDS=180
   # 再启动 proxy
   ```
   这样至少不会因为「proxy → 上游」过慢而先断掉。

2. **拉长整次 agent 运行时间（不影响单次 LLM 超时）**  
   在 `~/.openclaw/openclaw.json` 的 `agents.defaults` 中增加：
   ```json
   "timeoutSeconds": 300
   ```
   并可使用：
   ```bash
   openclaw agent --local --timeout 300 -m "..." --json
   ```
   这只影响整次 run 的最长执行时间，**不会**改变单次 LLM 请求的超时。

3. **若使用官方 OpenClaw 且 schema 支持**  
   在对应 provider（如 bailian）下配置：
   ```json
   "timeoutSeconds": 300
   ```
   部分发行版（如当前使用的 openclaw-zh）会报 `Unrecognized key: "timeoutSeconds"`，则无法通过该方式拉长单次请求超时。

4. **减小单次请求负担**  
   减少 system prompt / skills / tools 体积，或先用「最小 agent」测试，有助于在相同超时时间内拿到首包，降低超时概率。

## 为什么 Python 脚本能调通 Proxy，而 OpenClaw 会超时？

**Proxy 没有改任何协议。** 对 Python 和 OpenClaw 的请求，proxy 行为一致：

- 协议：收到 `POST /v1/chat/completions`，按 OpenAI 兼容格式解析 body（含 `stream: true`），原样转发到上游；流式时按 chunk 原样吐回给客户端。
- 代码路径（修复后）：`body = await request.json()` → `is_stream = body.get("stream") is True` → `client.stream(..., content=_stream_body_chunks(body))`（chunked 发 body，与直连一致）→ 上游首包与后续 chunk 经 queue 直接 `StreamingResponse` 写出。

差异只在**客户端**：

| 对比项 | Python 脚本（test_proxy_vs_direct_stream.py） | OpenClaw |
|--------|-----------------------------------------------|----------|
| **请求超时** | 显式 `httpx.AsyncClient(timeout=120.0)`，即 **120 秒** | 内置单次 LLM 请求超时，**无法配置**（openclaw-zh 不支持 provider `timeoutSeconds`），约 **数十秒或更短** |
| **请求体大小** | 一条短消息，body 很小 | 约 24k 字符 system prompt + skills + tools，body 很大 |
| **TTFB 需求** | 在 120s 内收到首包即可 | 若首包超过其内部超时即报 "LLM request timed out" |

因此：**不是 proxy 改了协议或“对 Python 更友好”，而是 Python 用了更长超时 + 更小 body**，所以能稳定通过；OpenClaw 用短超时 + 大 body，首包或总时间容易超过其内部限制，就超时。用 Python 对 proxy 发**大 body + 短 timeout**（例如 5s）可复现超时；15s 在本机约 8s 内返回则成功，说明 proxy 未改协议，差异仅在客户端超时与体量。

## 小结

- **根本原因（已修复）**：Proxy 之前用 `json=body` 一次性发大 body，上游按整块处理导致迟迟不回头；直连时客户端 chunked 发 body，上游边收边处理。流式请求已改为 chunked 转发请求体（`_stream_body_chunks`），与直连一致。
- **Proxy 侧**：流式时请求体以 chunked 转发，响应流不变；已支持 `UPSTREAM_TIMEOUT_SECONDS` 与诊断日志。
- **若仍遇超时**：按上文「如何调查报错原因」看 proxy 日志区分认证慢、上游慢或上游报错。
