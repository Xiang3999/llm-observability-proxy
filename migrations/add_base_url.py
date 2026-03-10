#!/usr/bin/env python3
"""
Database migration script to add base_url column to provider_keys table.

Usage:
    python migrate_add_base_url.py
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from src.models.database import engine


async def add_base_url_column():
    """Add base_url column to provider_keys table if it doesn't exist."""
    print("Checking if 'base_url' column exists...")

    async with engine.connect() as conn:
        # Try to add the column (SQLite will ignore if exists, PostgreSQL will error)
        try:
            # First check if column exists
            result = await conn.execute(text(
                "PRAGMA table_info(provider_keys)"
            ))
            columns = [row[1] for row in result.all()]

            if 'base_url' in columns:
                print("Column 'base_url' already exists in provider_keys table.")
                return True

            # Add the column
            print("Adding 'base_url' column to provider_keys table...")
            await conn.execute(text(
                "ALTER TABLE provider_keys ADD COLUMN base_url VARCHAR(512)"
            ))
            await conn.commit()
            print("Successfully added 'base_url' column!")
            return True

        except Exception as e:
            if "duplicate column" in str(e).lower():
                print("Column 'base_url' already exists.")
                return True
            raise


async def main():
    """Run the migration."""
    print("=" * 50)
    print("Database Migration: Add base_url column")
    print("=" * 50)
    print()

    try:
        success = await add_base_url_column()
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
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
