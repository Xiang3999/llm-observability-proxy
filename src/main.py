"""Main FastAPI application."""

import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from src.analytics.deep_analytics import router as deep_analytics_router
from src.analytics.provider_routes import router as provider_keys_router
from src.analytics.request_routes import router as requests_router
from src.analytics.routes import router as proxy_keys_router
from src.api.model_mapping import router as model_mapping_router
from src.config import settings
from src.models.database import init_db, start_maintenance_tasks, stop_maintenance_tasks
from src.proxy.routes import router as proxy_router
# from src.web.middleware import PageViewMiddleware  # Disabled due to session conflict
from src.web.routes import router as web_router

# Configure logging
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, settings.log_level.upper())),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("Starting up...", database=settings.database_url)
    await init_db()
    logger.info("Database initialized")

    # Start the async logging queue worker
    from src.recorder.logging_queue import LoggingQueue
    await LoggingQueue.start_worker()

    # Start database maintenance tasks (checkpoint + backup)
    await start_maintenance_tasks(
        checkpoint_interval=settings.db_checkpoint_interval_seconds,
        backup_interval_hours=settings.db_backup_interval_hours,
        backup_keep_count=settings.db_backup_keep_count,
    )

    # 连接预热：对常用上游建连，避免首次请求多 200–500ms 的 TCP+TLS
    prewarm = getattr(settings, "prewarm_urls", "") or ""
    if prewarm:
        from src.proxy.routes import get_http_client
        client = get_http_client()
        for raw in prewarm.split(","):
            url = raw.strip()
            if not url:
                continue
            try:
                r = await client.get(url, timeout=5.0)
                logger.info("Prewarm ok", url=url, status=r.status_code)
            except Exception as e:
                logger.warning("Prewarm skip", url=url, error=str(e))
    yield
    # Shutdown
    logger.info("Shutting down...")
    # Stop database maintenance tasks
    await stop_maintenance_tasks()
    # Stop the logging queue worker
    await LoggingQueue.stop_worker()
    # Close the global HTTP client to release connections
    from src.proxy.routes import _http_client, get_http_client
    if _http_client is not None:
        await _http_client.aclose()
        logger.info("HTTP client closed")


# Create FastAPI app
app = FastAPI(
    title="LLM Observability Proxy",
    description="A lightweight API proxy for monitoring LLM usage",
    version="0.1.0",
    lifespan=lifespan
)

# Page view tracking middleware - disabled due to session conflict
# app.add_middleware(PageViewMiddleware)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(proxy_router)
app.include_router(proxy_keys_router)
app.include_router(provider_keys_router)
app.include_router(requests_router)
app.include_router(deep_analytics_router)
app.include_router(model_mapping_router)
app.include_router(web_router)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/")
async def root():
    """Root endpoint - redirect to dashboard."""
    return RedirectResponse(url="/dashboard")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.log_level == "DEBUG"
    )
