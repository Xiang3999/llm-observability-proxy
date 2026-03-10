#!/usr/bin/env python3
"""Test that proxy records requests when using a proxy key.

Usage:
  # Use existing proxy key (dashboard or .env):
  PROXY_KEY=sk-proxy-xxx python3 scripts/test_proxy_recording.py

  # Or create keys (requires MASTER_API_KEY to match server):
  MASTER_API_KEY=your-master python3 scripts/test_proxy_recording.py
"""

import asyncio
import os
import sys

import httpx

BASE = os.environ.get("PROXY_URL", "http://localhost:8000")
MASTER = os.environ.get("MASTER_API_KEY", "change-me-in-production")
PROXY_KEY = os.environ.get("PROXY_KEY")


async def ensure_proxy_key(client: httpx.AsyncClient) -> str:
    """Use PROXY_KEY from env or create provider+proxy key (needs valid MASTER)."""
    if PROXY_KEY:
        return PROXY_KEY
    r = await client.post(
        f"{BASE}/api/provider-keys",
        json={"name": "RecordingTest", "provider": "openai", "api_key": "sk-test-fake"},
        headers={"Authorization": f"Bearer {MASTER}"},
    )
    if r.status_code != 201:
        print("Create provider key failed (need MASTER_API_KEY?):", r.status_code)
        sys.exit(1)
    pid = r.json()["id"]
    r = await client.post(
        f"{BASE}/api/proxy-keys",
        json={"name": "RecordingTestApp", "provider_key_id": pid},
        headers={"Authorization": f"Bearer {MASTER}"},
    )
    if r.status_code != 201:
        print("Create proxy key:", r.status_code)
        sys.exit(1)
    return r.json()["proxy_key"]


async def main():
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(f"{BASE}/health")
        if r.status_code != 200:
            print("Server not healthy:", r.status_code)
            sys.exit(1)
        print("Server OK")

        proxy_key = await ensure_proxy_key(client)
        print("Proxy key: ...%s" % (proxy_key[-12:] if len(proxy_key) > 12 else proxy_key))

        before = None
        r = await client.get(f"{BASE}/api/requests", headers={"Authorization": f"Bearer {MASTER}"})
        if r.status_code == 200:
            before = r.json().get("total", 0)
            print("Requests before:", before)
        else:
            print("(List requests: %s - set MASTER_API_KEY to match server)" % r.status_code)

        r = await client.post(
            f"{BASE}/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hi"}], "stream": False},
            headers={"Authorization": f"Bearer {proxy_key}"},
        )
        print("Proxy non-stream:", r.status_code)

        r = await client.post(
            f"{BASE}/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hi"}], "stream": True},
            headers={"Authorization": f"Bearer {proxy_key}"},
        )
        if r.status_code == 200:
            async for _ in r.aiter_bytes():
                pass
        print("Proxy stream:", r.status_code)

        r = await client.get(f"{BASE}/api/requests", headers={"Authorization": f"Bearer {MASTER}"})
        if r.status_code != 200:
            print("List after:", r.status_code, "- open %s/requests in browser" % BASE)
            return
        after = r.json().get("total", 0)
        print("Requests after:", after)
        if before is not None and after > before:
            print("OK: +%d request(s) recorded. Dashboard: %s/requests" % (after - before, BASE))
        else:
            print("Dashboard: %s/requests" % BASE)


if __name__ == "__main__":
    asyncio.run(main())
