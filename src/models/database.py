"""Database connection and session management."""

import asyncio
import shutil
from collections.abc import AsyncGenerator
from datetime import datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from src.config import settings


class Base(DeclarativeBase):
    """Base class for all database models."""
    pass


# Create async engine
engine = create_async_engine(
    settings.database_url,
    echo=settings.log_level == "DEBUG",
    future=True,
)

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator:
    """Get database session dependency injection."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Initialize database - create all tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _get_db_path() -> Path | None:
    """Extract database file path from database URL."""
    url = settings.database_url
    if url.startswith("sqlite"):
        # Handle sqlite:///./data/proxy.db or sqlite+aiosqlite:///./data/proxy.db
        path_part = url.split("///")[-1]
        if path_part.startswith("./"):
            return Path(path_part)
        return Path(path_part)
    return None


async def checkpoint_database():
    """Execute WAL checkpoint to merge WAL file into main database."""
    if not settings.database_url.startswith("sqlite"):
        return  # Only for SQLite

    try:
        async with engine.begin() as conn:
            # TRUNCATE: aggressively merges all WAL content, resets WAL file
            result = await conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE);")
            return result.fetchall()
    except Exception as e:
        import structlog
        logger = structlog.get_logger()
        logger.warning("Checkpoint failed", error=str(e))
        return None


async def backup_database(backup_dir: str = "data/backups") -> str | None:
    """Create a backup of the SQLite database file."""
    db_path = _get_db_path()
    if db_path is None or not db_path.exists():
        return None

    backup_path = Path(backup_dir)
    backup_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = backup_path / f"proxy_backup_{timestamp}.db"

    try:
        # Run checkpoint first to ensure WAL is merged
        await checkpoint_database()

        # Copy database file
        shutil.copy2(db_path, backup_file)
        return str(backup_file)
    except Exception as e:
        import structlog
        logger = structlog.get_logger()
        logger.warning("Backup failed", error=str(e))
        return None


async def _periodic_checkpoint(interval_seconds: int = 300):
    """Background task for periodic WAL checkpoint."""
    import structlog
    logger = structlog.get_logger()

    while True:
        try:
            await asyncio.sleep(interval_seconds)
            result = await checkpoint_database()
            if result:
                logger.debug("Periodic checkpoint completed", result=result)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("Periodic checkpoint error", error=str(e))


async def _periodic_backup(interval_hours: int = 24, keep_count: int = 7):
    """Background task for periodic database backup."""
    import structlog
    logger = structlog.get_logger()

    while True:
        try:
            await asyncio.sleep(interval_hours * 3600)
            backup_file = await backup_database()
            if backup_file:
                logger.info("Periodic backup completed", file=backup_file)
                # Clean up old backups
                await _cleanup_old_backups(keep_count)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("Periodic backup error", error=str(e))


async def _cleanup_old_backups(keep_count: int = 7):
    """Remove old backup files, keeping only the most recent ones."""
    backup_dir = Path("data/backups")
    if not backup_dir.exists():
        return

    backups = sorted(backup_dir.glob("proxy_backup_*.db"), reverse=True)
    for old_backup in backups[keep_count:]:
        old_backup.unlink()


# Background task handles
_checkpoint_task: asyncio.Task | None = None
_backup_task: asyncio.Task | None = None


async def start_maintenance_tasks(checkpoint_interval: int = 300, backup_interval_hours: int = 24, backup_keep_count: int = 7):
    """Start background maintenance tasks for SQLite database."""
    global _checkpoint_task, _backup_task

    if not settings.database_url.startswith("sqlite"):
        return  # Only for SQLite

    import structlog
    logger = structlog.get_logger()

    # Start checkpoint task (every 5 minutes by default)
    _checkpoint_task = asyncio.create_task(_periodic_checkpoint(checkpoint_interval))
    logger.info("Database checkpoint task started", interval_seconds=checkpoint_interval)

    # Start backup task (every 24 hours by default)
    _backup_task = asyncio.create_task(_periodic_backup(backup_interval_hours, backup_keep_count))
    logger.info("Database backup task started", interval_hours=backup_interval_hours, keep_count=backup_keep_count)


async def stop_maintenance_tasks():
    """Stop background maintenance tasks."""
    global _checkpoint_task, _backup_task

    import structlog
    logger = structlog.get_logger()

    if _checkpoint_task:
        _checkpoint_task.cancel()
        try:
            await _checkpoint_task
        except asyncio.CancelledError:
            pass
        logger.info("Database checkpoint task stopped")

    if _backup_task:
        _backup_task.cancel()
        try:
            await _backup_task
        except asyncio.CancelledError:
            pass
        logger.info("Database backup task stopped")
