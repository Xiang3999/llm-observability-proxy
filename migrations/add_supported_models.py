#!/usr/bin/env python3
"""Add supported_models column to provider_keys table."""

import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text


async def migrate():
    """Run the migration."""
    import os
    # Determine database path from environment or use default relative path
    db_path = os.environ.get(
        "DATABASE_URL",
        "sqlite+aiosqlite:///./data/proxy.db"
    )
    engine = create_async_engine(db_path)

    async with engine.begin() as conn:
        # Check if column already exists
        result = await conn.execute(text("PRAGMA table_info(provider_keys)"))
        columns = [row[1] for row in result.fetchall()]

        if "supported_models" not in columns:
            print("Adding supported_models column to provider_keys table...")
            await conn.execute(text(
                "ALTER TABLE provider_keys ADD COLUMN supported_models JSON"
            ))
            print("Migration completed successfully!")
        else:
            print("supported_models column already exists, skipping migration.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(migrate())
