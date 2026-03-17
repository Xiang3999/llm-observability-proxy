#!/usr/bin/env python3
"""Benchmark dashboard response times before/after optimization."""

import asyncio
import time
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
import random
import string

import httpx


async def generate_test_data(base_url: str, api_key: str, count: int = 100):
    """Generate test request data."""
    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"Bearer {api_key}"}

        models = ["gpt-4", "gpt-3.5-turbo", "claude-3-opus", "claude-3-sonnet"]
        statuses = [200, 200, 200, 200, 400, 429, 500]  # Weighted towards success

        for i in range(count):
            # Simulate requests over the past 7 days
            days_ago = random.randint(0, 7)
            hours_ago = random.randint(0, 23)

            await client.post(
                f"{base_url}/v1/chat/completions",
                headers=headers,
                json={
                    "model": random.choice(models),
                    "messages": [
                        {"role": "user", "content": f"Test message {i}"}
                    ],
                },
                timeout=30.0,
            )
            await asyncio.sleep(0.01)  # Small delay to avoid rate limiting


async def measure_dashboard_response(base_url: str, endpoint: str) -> float:
    """Measure response time for a dashboard endpoint."""
    async with httpx.AsyncClient() as client:
        start = time.perf_counter()
        response = await client.get(f"{base_url}{endpoint}", timeout=30.0)
        elapsed = time.perf_counter() - start

        if response.status_code != 200:
            print(f"  WARNING: {endpoint} returned {response.status_code}")

        return elapsed


async def run_benchmark(base_url: str, iterations: int = 5):
    """Run benchmark and report results."""
    print(f"\n{'='*60}")
    print(f"Dashboard Performance Benchmark")
    print(f"Base URL: {base_url}")
    print(f"Iterations: {iterations}")
    print(f"{'='*60}\n")

    endpoints = {
        "Dashboard": "/dashboard",
        "Requests List": "/requests",
        "Health Check": "/health",
    }

    results = {name: [] for name in endpoints}

    for i in range(iterations):
        print(f"Iteration {i+1}/{iterations}...")
        for name, endpoint in endpoints.items():
            elapsed = await measure_dashboard_response(base_url, endpoint)
            results[name].append(elapsed)
            print(f"  {name}: {elapsed*1000:.2f}ms")
        # Small delay between iterations
        await asyncio.sleep(0.5)

    print(f"\n{'='*60}")
    print("Results Summary (average response time):")
    print(f"{'='*60}")

    for name, times in results.items():
        avg = sum(times) / len(times)
        min_t = min(times)
        max_t = max(times)
        print(f"{name:20s}: {avg*1000:7.2f}ms (min: {min_t*1000:.2f}ms, max: {max_t*1000:.2f}ms)")

    print(f"{'='*60}\n")


async def main():
    """Main entry point."""
    base_url = "http://localhost:8000"  # Production port

    # Check if server is running
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{base_url}/health", timeout=5.0)
            if response.status_code != 200:
                print("Server is not healthy. Please start the server first.")
                return
        except Exception as e:
            print(f"Cannot connect to server: {e}")
            print("Please start the server first with: uv run uvicorn src.main:app")
            return

    # Run benchmark
    await run_benchmark(base_url, iterations=5)


if __name__ == "__main__":
    asyncio.run(main())
