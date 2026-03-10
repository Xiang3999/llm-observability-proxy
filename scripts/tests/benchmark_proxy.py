#!/usr/bin/env python3
"""
Benchmark proxy layer latency (auth cache + hot path).

Usage:
  # 需要先安装依赖并确保 Python 3.10+ 或使用 venv
  python benchmark_proxy.py

Measures: 请求进入 proxy 到返回响应的时间（上游用 mock 即时返回，只测 proxy 自身开销）
"""

import asyncio
import json
import os
import statistics
import time

# 使用内存 SQLite 避免磁盘 I/O
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("MASTER_API_KEY", "bench-master-key")

# Mock 上游响应，避免真实网络
MOCK_RESPONSE = {
    "id": "mock-1",
    "object": "chat.completion",
    "created": 0,
    "model": "gpt-4o-mini",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hi"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
}


async def run_benchmark(num_requests: int = 50, warmup: int = 5):
    from httpx import ASGITransport, AsyncClient

    from src.main import app
    from src.models.database import AsyncSessionLocal, init_db
    from src.models.database import Base, engine
    from src.models.provider_key import ProviderKey, ProviderType
    from src.models.proxy_key import ProxyKey

    # 建表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 创建 Provider Key + Proxy Key
    async with AsyncSessionLocal() as session:
        pk = ProviderKey(
            name="bench-provider",
            provider=ProviderType.OPENAI,
            encrypted_key="sk-mock-openai-key",
        )
        session.add(pk)
        await session.flush()
        proxy = ProxyKey(
            name="bench-app",
            proxy_key="sk-proxy-bench-test-key",
            proxy_key_hash="dummy-hash",
            provider_key_id=pk.id,
        )
        session.add(proxy)
        await session.commit()
        proxy_key_plain = "sk-proxy-bench-test-key"

    # 替换全局 httpx 客户端为 mock：不请求真实上游，直接返回
    import src.proxy.routes as proxy_routes

    original_client = proxy_routes._http_client

    class MockResponse:
        status_code = 200
        content = json.dumps(MOCK_RESPONSE).encode()
        headers = {"content-type": "application/json"}

    class MockClient:
        async def request(self, *args, **kwargs):
            return MockResponse()

    proxy_routes._http_client = MockClient()

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            timeout=10.0,
        ) as client:
            # Warmup：前几次会走 DB 填 auth cache
            for _ in range(warmup):
                await client.post(
                    "/v1/chat/completions",
                    json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hi"}]},
                    headers={"Authorization": f"Bearer {proxy_key_plain}"},
                )

            latencies_ms = []
            for i in range(num_requests):
                start = time.perf_counter()
                r = await client.post(
                    "/v1/chat/completions",
                    json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": f"Hi {i}"}]},
                    headers={"Authorization": f"Bearer {proxy_key_plain}"},
                )
                elapsed_ms = (time.perf_counter() - start) * 1000
                latencies_ms.append(elapsed_ms)
                if r.status_code != 200:
                    print(f"Request {i} failed: {r.status_code} {r.text[:200]}")

            # 等待后台记录任务结束，避免漏测
            await asyncio.sleep(0.5)
    finally:
        proxy_routes._http_client = original_client

    return latencies_ms


def main():
    try:
        latencies = asyncio.run(run_benchmark(num_requests=50, warmup=5))
    except Exception as e:
        print(f"Benchmark failed: {e}")
        import traceback
        traceback.print_exc()
        return

    if not latencies:
        print("No successful requests.")
        return

    latencies.sort()
    n = len(latencies)
    print("=" * 50)
    print("Proxy 层延迟 (上游 mock 即时返回，仅测 proxy 开销)")
    print("=" * 50)
    print(f"  请求数: {n}")
    print(f"  最小:   {min(latencies):.2f} ms")
    print(f"  最大:   {max(latencies):.2f} ms")
    print(f"  平均:   {statistics.mean(latencies):.2f} ms")
    if n >= 2:
        print(f"  中位数: {statistics.median(latencies):.2f} ms")
        print(f"  标准差: {statistics.stdev(latencies):.2f} ms")
    print(f"  P50:    {latencies[int(n * 0.5)]:.2f} ms")
    print(f"  P95:    {latencies[int(n * 0.95)]:.2f} ms")
    print(f"  P99:    {latencies[int(n * 0.99)]:.2f} ms")
    print("=" * 50)


if __name__ == "__main__":
    main()
