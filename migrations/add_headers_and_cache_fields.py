#!/usr/bin/env python3
"""
Database migration to add headers and cache metrics fields to request_logs table.

Usage:
    python migrations/add_headers_and_cache_fields.py
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from src.models.database import engine


async def add_headers_and_cache_fields():
    """Add headers and cache metrics columns to request_logs table."""
    print("Adding headers and cache metrics columns to request_logs...")

    async with engine.connect() as conn:
        # Check existing columns
        result = await conn.execute(text("PRAGMA table_info(request_logs)"))
        columns = [row[1] for row in result.all()]

        # Fields to add
        fields = [
            ("request_headers", "JSON"),
            ("response_headers", "JSON"),
            ("cache_read_tokens", "INTEGER"),
            ("cache_creation_tokens", "INTEGER"),
            ("anthropic_metadata", "JSON"),
            ("usage_breakdown", "JSON"),
        ]

        for field_name, field_type in fields:
            if field_name in columns:
                print(f"  Column '{field_name}' already exists, skipping.")
            else:
                print(f"  Adding column '{field_name}'...")
                await conn.execute(text(
                    f"ALTER TABLE request_logs ADD COLUMN {field_name} {field_type}"
                ))

        await conn.commit()
        print("Migration completed successfully!")
        return True


async def main():
    """Run the migration."""
    print("=" * 50)
    print("Database Migration: Add Headers and Cache Fields")
    print("=" * 50)
    print()

    try:
        success = await add_headers_and_cache_fields()
        if success:
            print()
            print("Migration completed successfully!")
            return 0
        else:
            print()
            print("Migration failed!")
            return 1
    except Exception as e:
        print(f"Error during migration: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
