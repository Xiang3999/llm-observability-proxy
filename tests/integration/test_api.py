"""Integration tests for the API."""

import pytest
import asyncio
from httpx import AsyncClient, ASGITransport

from src.main import app
from src.models.database import init_db, engine, AsyncSessionLocal
from src.models.provider_key import ProviderKey, ProviderType
from src.models.proxy_key import ProxyKey
from src.auth.key_manager import hash_key


@pytest.fixture
async def db_session():
    """Create a fresh database session for each test."""
    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(type(init_db).__globals__["Base"].metadata.create_all)

    async with AsyncSessionLocal() as session:
        yield session

    # Drop tables after test
    async with engine.begin() as conn:
        await conn.run_sync(type(init_db).__globals__["Base"].metadata.drop_all)


@pytest.fixture
async def client(db_session):
    """Create test client with database override."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as ac:
        yield ac


@pytest.mark.asyncio
async def test_health_check(client):
    """Test health check endpoint."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


@pytest.mark.asyncio
async def test_root_endpoint(client):
    """Test root endpoint."""
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "LLM Observability Proxy"
    assert "version" in data


@pytest.mark.asyncio
async def test_create_provider_key(client):
    """Test creating a provider key."""
    response = await client.post(
        "/api/provider-keys",
        json={
            "name": "Test OpenAI Key",
            "provider": "openai",
            "api_key": "sk-test123456"
        },
        headers={"Authorization": "Bearer change-me-in-production"}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test OpenAI Key"
    assert data["provider"] == "openai"
    assert "id" in data


@pytest.mark.asyncio
async def test_list_provider_keys(client, db_session):
    """Test listing provider keys."""
    # Create a provider key
    provider_key = ProviderKey(
        id="test-provider-key-id",
        name="Test Key",
        provider=ProviderType.OPENAI,
        encrypted_key="hashed-key"
    )
    db_session.add(provider_key)
    await db_session.commit()

    response = await client.get(
        "/api/provider-keys",
        headers={"Authorization": "Bearer change-me-in-production"}
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_create_proxy_key(client, db_session):
    """Test creating a proxy key."""
    # First create a provider key
    provider_key = ProviderKey(
        id="test-provider-key-id",
        name="Test Key",
        provider=ProviderType.OPENAI,
        encrypted_key="hashed-key"
    )
    db_session.add(provider_key)
    await db_session.commit()

    response = await client.post(
        "/api/proxy-keys",
        params={
            "name": "Test App",
            "provider_key_id": "test-provider-key-id"
        },
        headers={"Authorization": "Bearer change-me-in-production"}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test App"
    assert "proxy_key" in data  # Should return the plain key once
    assert data["proxy_key"].startswith("sk-helicone-proxy-")


@pytest.mark.asyncio
async def test_proxy_request_without_auth(client):
    """Test that proxy endpoint requires authentication."""
    response = await client.post("/v1/chat/completions", json={})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_proxy_request_with_invalid_key(client):
    """Test proxy with invalid proxy key."""
    response = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o-mini", "messages": []},
        headers={"Authorization": "Bearer sk-helicone-proxy-invalid"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_requests_list(client, db_session):
    """Test listing requests."""
    response = await client.get(
        "/api/requests",
        headers={"Authorization": "Bearer change-me-in-production"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_stats_overview(client):
    """Test stats overview endpoint."""
    response = await client.get(
        "/api/requests/stats/overview",
        headers={"Authorization": "Bearer change-me-in-production"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "total_requests" in data
    assert "total_tokens" in data


@pytest.mark.asyncio
async def test_dashboard(client):
    """Test dashboard HTML endpoint."""
    response = await client.get("/dashboard")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert b"LLM Observability Proxy" in response.content
