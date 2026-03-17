"""Migration: Add composite indexes for dashboard optimization.

Run this migration to add composite indexes that improve query performance
for common dashboard query patterns.

Usage:
    python -m migrations.add_composite_indexes
"""

import asyncio

from sqlalchemy import text

from src.models.database import engine


async def create_indexes():
    """Create composite indexes for dashboard optimization."""
    indexes = [
        # Existing composite indexes for dashboard queries
        ("idx_request_logs_app_time", "proxy_key_id", "created_at"),
        ("idx_request_logs_model_time", "model", "created_at"),
        ("idx_request_logs_status_time", "status_code", "created_at"),
        ("idx_request_logs_proxy_status_time", "proxy_key_id", "status_code", "created_at"),
        # Additional indexes for user/session queries
        ("idx_request_logs_user_created", "user_id", "created_at"),
        ("idx_request_logs_session_created", "session_id", "created_at"),
    ]

    async with engine.connect() as conn:
        for index_name, *columns in indexes:
            try:
                # Check if index already exists
                result = await conn.execute(
                    text(f"""
                        SELECT name FROM sqlite_master
                        WHERE type='index' AND name='{index_name}'
                    """)
                )
                if result.fetchone():
                    print(f"Index {index_name} already exists, skipping...")
                    continue

                # Create index
                column_list = ", ".join(columns)
                await conn.execute(
                    text(f"CREATE INDEX IF NOT EXISTS {index_name} ON request_logs ({column_list})")
                )
                await conn.commit()
                print(f"Created index: {index_name} on ({column_list})")

            except Exception as e:
                print(f"Error creating index {index_name}: {e}")
                await conn.rollback()

    # Enable WAL mode and performance pragmas
    async with engine.connect() as conn:
        pragmas = [
            ("journal_mode", "WAL"),
            ("synchronous", "NORMAL"),
            ("cache_size", "10000"),
            ("temp_store", "MEMORY"),
        ]
        for pragma, value in pragmas:
            try:
                await conn.execute(text(f"PRAGMA {pragma}={value}"))
                await conn.commit()
                print(f"Set PRAGMA {pragma}={value}")
            except Exception as e:
                print(f"Error setting PRAGMA {pragma}: {e}")


if __name__ == "__main__":
    print("Running migration: add_composite_indexes")
    asyncio.run(create_indexes())
    print("Migration completed!")
