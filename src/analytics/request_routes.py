"""API routes for request logs and analytics."""

from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import datetime, timedelta

from src.models.database import get_db
from src.models.request_log import RequestLog
from src.models.proxy_key import ProxyKey
from src.auth.middleware import verify_master_key

router = APIRouter(prefix="/api/requests", tags=["Requests"])

# Type alias for database session dependency
DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.get("")
async def list_requests(
    db: DbSession,
    proxy_key_id: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    status_code: Optional[int] = Query(None),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    _: str = Depends(verify_master_key)
):
    """List request logs with filtering."""
    query = select(RequestLog).where(ProxyKey.is_active == True)

    # Apply filters
    if proxy_key_id:
        query = query.where(RequestLog.proxy_key_id == proxy_key_id)
    if model:
        query = query.where(RequestLog.model == model)
    if status_code:
        query = query.where(RequestLog.status_code == status_code)
    if start_time:
        query = query.where(RequestLog.created_at >= start_time)
    if end_time:
        query = query.where(RequestLog.created_at <= end_time)

    # Order and paginate
    query = query.order_by(RequestLog.created_at.desc())
    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    requests = list(result.scalars().all())

    # Get total count
    count_query = select(func.count(RequestLog.id))
    if proxy_key_id:
        count_query = count_query.where(RequestLog.proxy_key_id == proxy_key_id)
    if model:
        count_query = count_query.where(RequestLog.model == model)
    count_result = await db.execute(count_query)
    total = count_result.scalar()

    return {
        "data": [
            {
                "id": r.id,
                "proxy_key_id": r.proxy_key_id,
                "path": r.request_path,
                "model": r.model,
                "status_code": r.status_code,
                "total_tokens": r.total_tokens,
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
                "total_latency_ms": r.total_latency_ms,
                "cost_usd": float(r.cost_usd) if r.cost_usd else None,
                "created_at": r.created_at.isoformat()
            }
            for r in requests
        ],
        "total": total,
        "limit": limit,
        "offset": offset
    }


@router.get("/{request_id}")
async def get_request(
    db: DbSession,
    request_id: str,
    _: str = Depends(verify_master_key)
):
    """Get a specific request log with full details."""
    result = await db.execute(
        select(RequestLog).where(RequestLog.id == request_id)
    )
    request = result.scalar_one_or_none()

    if not request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found"
        )

    return {
        "id": request.id,
        "proxy_key_id": request.proxy_key_id,
        "path": request.request_path,
        "method": request.method,
        "model": request.model,
        "provider": request.provider,
        "status_code": request.status_code,
        "error_message": request.error_message,
        "prompt_tokens": request.prompt_tokens,
        "completion_tokens": request.completion_tokens,
        "total_tokens": request.total_tokens,
        "total_latency_ms": request.total_latency_ms,
        "time_to_first_token_ms": request.time_to_first_token_ms,
        "cost_usd": float(request.cost_usd) if request.cost_usd else None,
        "created_at": request.created_at.isoformat(),
        "completed_at": request.completed_at.isoformat() if request.completed_at else None,
        "request_body": request.request_body,
        "response_body": request.response_body,
        "user_id": request.user_id,
        "properties": request.properties
    }


@router.get("/stats/overview")
async def get_stats_overview(
    db: DbSession,
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    _: str = Depends(verify_master_key)
):
    """Get overall statistics."""
    # Build base query
    filters = []
    if start_time:
        filters.append(RequestLog.created_at >= start_time)
    if end_time:
        filters.append(RequestLog.created_at <= end_time)

    query = select(
        func.count(RequestLog.id).label("total_requests"),
        func.sum(RequestLog.total_tokens).label("total_tokens"),
        func.sum(RequestLog.prompt_tokens).label("prompt_tokens"),
        func.sum(RequestLog.completion_tokens).label("completion_tokens"),
        func.avg(RequestLog.total_latency_ms).label("avg_latency_ms"),
        func.sum(RequestLog.cost_usd).label("total_cost")
    )

    if filters:
        query = query.where(and_(*filters))

    result = await db.execute(query)
    row = result.one()

    return {
        "total_requests": row.total_requests or 0,
        "total_tokens": row.total_tokens or 0,
        "prompt_tokens": row.prompt_tokens or 0,
        "completion_tokens": row.completion_tokens or 0,
        "avg_latency_ms": float(row.avg_latency_ms or 0),
        "total_cost_usd": float(row.total_cost or 0)
    }


@router.get("/stats/by-app")
async def get_stats_by_app(
    db: DbSession,
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    _: str = Depends(verify_master_key)
):
    """Get statistics grouped by application (proxy key)."""
    # Build filters
    filters = []
    if start_time:
        filters.append(RequestLog.created_at >= start_time)
    if end_time:
        filters.append(RequestLog.created_at <= end_time)

    query = (
        select(
            ProxyKey.id,
            ProxyKey.name,
            func.count(RequestLog.id).label("total_requests"),
            func.sum(RequestLog.total_tokens).label("total_tokens"),
            func.sum(RequestLog.cost_usd).label("total_cost")
        )
        .join(RequestLog, RequestLog.proxy_key_id == ProxyKey.id)
        .group_by(ProxyKey.id, ProxyKey.name)
    )

    if filters:
        query = query.where(and_(*filters))

    result = await db.execute(query)
    rows = result.all()

    return [
        {
            "app_id": row.id,
            "app_name": row.name,
            "total_requests": row.total_requests,
            "total_tokens": row.total_tokens or 0,
            "total_cost_usd": float(row.total_cost or 0)
        }
        for row in rows
    ]


@router.get("/stats/by-model")
async def get_stats_by_model(
    db: DbSession,
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    _: str = Depends(verify_master_key)
):
    """Get statistics grouped by model."""
    filters = []
    if start_time:
        filters.append(RequestLog.created_at >= start_time)
    if end_time:
        filters.append(RequestLog.created_at <= end_time)

    query = (
        select(
            RequestLog.model,
            func.count(RequestLog.id).label("total_requests"),
            func.sum(RequestLog.total_tokens).label("total_tokens"),
            func.avg(RequestLog.total_latency_ms).label("avg_latency_ms"),
            func.sum(RequestLog.cost_usd).label("total_cost")
        )
        .where(RequestLog.model.isnot(None))
        .group_by(RequestLog.model)
    )

    if filters:
        query = query.where(and_(*filters))

    result = await db.execute(query)
    rows = result.all()

    return [
        {
            "model": row.model,
            "total_requests": row.total_requests,
            "total_tokens": row.total_tokens or 0,
            "avg_latency_ms": float(row.avg_latency_ms or 0),
            "total_cost_usd": float(row.total_cost or 0)
        }
        for row in rows
    ]


@router.get("/stats/timeline")
async def get_stats_timeline(
    db: DbSession,
    hours: int = Query(24, ge=1, le=168),
    _: str = Depends(verify_master_key)
):
    """Get request count over time."""
    end_time = datetime.now()
    start_time = end_time - timedelta(hours=hours)

    # Group by hour
    query = (
        select(
            func.strftime("%Y-%m-%d %H:00", RequestLog.created_at).label("hour"),
            func.count(RequestLog.id).label("request_count"),
            func.sum(RequestLog.total_tokens).label("total_tokens"),
            func.avg(RequestLog.total_latency_ms).label("avg_latency_ms")
        )
        .where(RequestLog.created_at >= start_time)
        .where(RequestLog.created_at <= end_time)
        .group_by("hour")
        .order_by("hour")
    )

    result = await db.execute(query)
    rows = result.all()

    return [
        {
            "hour": row.hour,
            "request_count": row.request_count,
            "total_tokens": row.total_tokens or 0,
            "avg_latency_ms": float(row.avg_latency_ms or 0)
        }
        for row in rows
    ]
