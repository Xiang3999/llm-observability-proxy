"""Model mapping API routes."""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.models.database import get_db
from src.models.model_mapping import ModelMapping
from src.auth.middleware import verify_master_key
from pydantic import BaseModel


router = APIRouter(prefix="/api/model-mappings", tags=["Model Mapping"])


# Pydantic models for request/response
class ModelMappingCreate(BaseModel):
    source_model: str
    target_model: str
    description: Optional[str] = None


class ModelMappingUpdate(BaseModel):
    target_model: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class ModelMappingResponse(BaseModel):
    id: str
    source_model: str
    target_model: str
    description: Optional[str]
    is_active: bool
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


@router.get("", response_model=List[ModelMappingResponse])
async def list_model_mappings(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(verify_master_key)
):
    """List all model mappings."""
    result = await db.execute(
        select(ModelMapping).order_by(ModelMapping.created_at.desc())
    )
    mappings = result.scalars().all()
    return [
        ModelMappingResponse(
            id=m.id,
            source_model=m.source_model,
            target_model=m.target_model,
            description=m.description,
            is_active=m.is_active,
            created_at=m.created_at.isoformat() if m.created_at else "",
            updated_at=m.updated_at.isoformat() if m.updated_at else "",
        )
        for m in mappings
    ]


@router.post("", response_model=ModelMappingResponse)
async def create_model_mapping(
    data: ModelMappingCreate,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(verify_master_key)
):
    """Create a new model mapping."""
    from src.proxy.routes import clear_model_mapping_cache

    # Check if source_model already exists
    existing = await db.execute(
        select(ModelMapping).where(ModelMapping.source_model == data.source_model)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Source model already exists")

    mapping = ModelMapping(
        source_model=data.source_model,
        target_model=data.target_model,
        description=data.description,
    )
    db.add(mapping)
    await db.flush()
    await db.refresh(mapping)

    # Clear cache so new mapping takes effect immediately
    clear_model_mapping_cache()

    return ModelMappingResponse(
        id=mapping.id,
        source_model=mapping.source_model,
        target_model=mapping.target_model,
        description=mapping.description,
        is_active=mapping.is_active,
        created_at=mapping.created_at.isoformat() if mapping.created_at else "",
        updated_at=mapping.updated_at.isoformat() if mapping.updated_at else "",
    )


@router.put("/{mapping_id}", response_model=ModelMappingResponse)
async def update_model_mapping(
    mapping_id: str,
    data: ModelMappingUpdate,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(verify_master_key)
):
    """Update a model mapping."""
    from src.proxy.routes import clear_model_mapping_cache

    result = await db.execute(
        select(ModelMapping).where(ModelMapping.id == mapping_id)
    )
    mapping = result.scalar_one_or_none()
    if not mapping:
        raise HTTPException(status_code=404, detail="Model mapping not found")

    if data.target_model is not None:
        mapping.target_model = data.target_model
    if data.description is not None:
        mapping.description = data.description
    if data.is_active is not None:
        mapping.is_active = data.is_active

    await db.flush()
    await db.refresh(mapping)

    # Clear cache so updated mapping takes effect immediately
    clear_model_mapping_cache()

    return ModelMappingResponse(
        id=mapping.id,
        source_model=mapping.source_model,
        target_model=mapping.target_model,
        description=mapping.description,
        is_active=mapping.is_active,
        created_at=mapping.created_at.isoformat() if mapping.created_at else "",
        updated_at=mapping.updated_at.isoformat() if mapping.updated_at else "",
    )


@router.delete("/{mapping_id}")
async def delete_model_mapping(
    mapping_id: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(verify_master_key)
):
    """Delete a model mapping."""
    from src.proxy.routes import clear_model_mapping_cache

    result = await db.execute(
        select(ModelMapping).where(ModelMapping.id == mapping_id)
    )
    mapping = result.scalar_one_or_none()
    if not mapping:
        raise HTTPException(status_code=404, detail="Model mapping not found")

    await db.delete(mapping)
    await db.flush()

    # Clear cache so deleted mapping takes effect immediately
    clear_model_mapping_cache()

    return {"status": "deleted"}


@router.get("/resolve/{source_model}")
async def resolve_model(
    source_model: str,
    db: AsyncSession = Depends(get_db)
):
    """Resolve a source model to its target model.

    This is a public endpoint (no auth required) for fast lookups during proxying.
    Supports exact match, prefix match (e.g., claude-*), and wildcard (*).
    Returns the source_model if no mapping exists.
    """
    # Get all active mappings
    result = await db.execute(
        select(ModelMapping).where(ModelMapping.is_active == True)
    )
    all_mappings = result.scalars().all()

    # Priority 1: Exact match
    for mapping in all_mappings:
        if mapping.source_model == source_model:
            return {"source_model": source_model, "target_model": mapping.target_model, "mapped": True, "match_type": "exact"}

    # Priority 2: Prefix match (e.g., "claude-*" matches "claude-3-5-sonnet")
    prefix_mappings = [m for m in all_mappings if m.source_model.endswith("*") and m.source_model != "*"]
    prefix_mappings.sort(key=lambda m: len(m.source_model), reverse=True)

    for mapping in prefix_mappings:
        prefix = mapping.source_model[:-1]
        if source_model.startswith(prefix):
            return {"source_model": source_model, "target_model": mapping.target_model, "mapped": True, "match_type": "prefix", "pattern": mapping.source_model}

    # Priority 3: Wildcard match ("*" matches everything)
    for mapping in all_mappings:
        if mapping.source_model == "*":
            return {"source_model": source_model, "target_model": mapping.target_model, "mapped": True, "match_type": "wildcard"}

    return {"source_model": source_model, "target_model": source_model, "mapped": False}