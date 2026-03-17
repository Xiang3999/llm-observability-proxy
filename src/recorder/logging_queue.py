"""Async logging queue for non-blocking observability."""

import asyncio
from datetime import datetime
from typing import Any, Optional

import structlog

from src.models.database import AsyncSessionLocal
from src.recorder.recorder import RequestRecorder

logger = structlog.get_logger(__name__)


class LoggingQueue:
    """Async queue for fire-and-forget request logging.

    Provides non-blocking logging by queuing log requests and processing
    them in a background worker. This reduces latency on the critical
    request path.
    """

    _instance: Optional["LoggingQueue"] = None
    _worker_task: Optional[asyncio.Task] = None

    def __init__(
        self,
        max_size: int = 10000,
        batch_size: int = 50,
        flush_interval: float = 5.0,
    ):
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=max_size)
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.running = False
        self.dropped_count = 0
        self.processed_count = 0

    @classmethod
    def get_instance(cls) -> "LoggingQueue":
        """Get or create the singleton instance."""
        if cls._instance is None:
            cls._instance = LoggingQueue()
        return cls._instance

    @classmethod
    async def start_worker(cls) -> None:
        """Start the background worker (call once at application startup)."""
        instance = cls.get_instance()
        if instance.running:
            return
        instance.running = True
        instance._worker_task = asyncio.create_task(instance._worker())
        logger.info("logging_queue_started", max_size=instance.queue.maxsize)

    @classmethod
    async def stop_worker(cls) -> None:
        """Stop the background worker (call at application shutdown)."""
        instance = cls.get_instance()
        if not instance.running:
            return
        instance.running = False

        if instance._worker_task:
            try:
                await asyncio.wait_for(instance._worker_task, timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning("logging_queue_shutdown_timeout", remaining=instance.queue.qsize())
                instance._worker_task.cancel()

        logger.info("logging_queue_stopped", processed=instance.processed_count, dropped=instance.dropped_count)

    async def enqueue(
        self,
        proxy_key_id: str,
        path: str,
        method: str,
        model: Optional[str],
        provider: str,
        body: dict[str, Any],
        start_time: datetime,
        status_code: int,
        response_body: dict,
        request_headers: Optional[dict[str, Any]] = None,
    ) -> bool:
        """Enqueue a log entry for background processing."""
        try:
            self.queue.put_nowait({
                "proxy_key_id": proxy_key_id,
                "path": path,
                "method": method,
                "model": model,
                "provider": provider,
                "body": body,
                "start_time": start_time,
                "status_code": status_code,
                "response_body": response_body,
                "request_headers": request_headers,
            })
            return True
        except asyncio.QueueFull:
            self.dropped_count += 1
            logger.warning("logging_queue_full", dropped=self.dropped_count, queue_size=self.queue.qsize())
            return False

    async def _worker(self) -> None:
        """Background worker that processes queued log entries."""
        batch: list[dict] = []
        last_flush = asyncio.get_event_loop().time()

        while self.running:
            try:
                try:
                    item = await asyncio.wait_for(self.queue.get(), timeout=self.flush_interval)
                    batch.append(item)
                except asyncio.TimeoutError:
                    pass

                now = asyncio.get_event_loop().time()
                should_flush = len(batch) >= self.batch_size or (batch and now - last_flush >= self.flush_interval)

                if should_flush and batch:
                    await self._flush_batch(batch)
                    self.processed_count += len(batch)
                    batch = []
                    last_flush = now

            except Exception as e:
                logger.error("logging_queue_worker_error", error=str(e), exc_info=True)

        if batch:
            await self._flush_batch(batch)

    async def _flush_batch(self, batch: list[dict]) -> None:
        """Flush a batch of log entries to the database."""
        async with AsyncSessionLocal() as session:
            recorder = RequestRecorder(session)

            for i, item in enumerate(batch):
                try:
                    await recorder.record_request_start(
                        proxy_key_id=item["proxy_key_id"],
                        path=item["path"],
                        method=item["method"],
                        model=item["model"],
                        provider=item["provider"],
                        body=item["body"],
                        start_time=item["start_time"],
                        headers=item["request_headers"],
                    )
                    await recorder.record_response(
                        status_code=item["status_code"],
                        headers={},
                        body=item["response_body"],
                        end_time=datetime.now(),
                        first_token_time=datetime.now(),
                    )
                    await recorder.finalize()
                except Exception as e:
                    logger.error("logging_queue_item_error", item_index=i, batch_size=len(batch), error=str(e), exc_info=True)

            await session.commit()

        logger.debug("logging_queue_batch_flushed", batch_size=len(batch), total_processed=self.processed_count)


async def log_request_async(
    proxy_key_id: str, path: str, method: str, model: Optional[str], provider: str,
    body: dict[str, Any], start_time: datetime, status_code: int, response_body: dict,
    request_headers: Optional[dict[str, Any]] = None,
) -> None:
    """Log a request using the fire-and-forget queue."""
    queue = LoggingQueue.get_instance()
    if not queue.running:
        async with AsyncSessionLocal() as session:
            recorder = RequestRecorder(session)
            await recorder.record_request_start(
                proxy_key_id=proxy_key_id, path=path, method=method, model=model,
                provider=provider, body=body, start_time=start_time, headers=request_headers,
            )
            await recorder.record_response(
                status_code=status_code, headers={}, body=response_body,
                end_time=datetime.now(), first_token_time=datetime.now(),
            )
            await recorder.finalize()
            await session.commit()
    else:
        await queue.enqueue(
            proxy_key_id=proxy_key_id, path=path, method=method, model=model,
            provider=provider, body=body, start_time=start_time, status_code=status_code,
            response_body=response_body, request_headers=request_headers,
        )
