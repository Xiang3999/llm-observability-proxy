"""Middleware for tracking page views."""

from fastapi import Request
from fastapi.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware
from datetime import datetime
import asyncio

from src.models.page_view import PageView
from src.models.database import AsyncSessionLocal


class PageViewMiddleware(BaseHTTPMiddleware):
    """Middleware to track page views with visitor information."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip tracking for static files, API endpoints, and non-GET requests
        path = request.url.path
        if not path.startswith("/"):
            return await call_next(request)

        # Skip API endpoints, static files, and favicon
        skip_prefixes = ("/api/", "/docs", "/redoc", "/openapi.json", "/favicon.ico", "/static/")
        if any(path.startswith(prefix) for prefix in skip_prefixes):
            return await call_next(request)

        # Get client IP (handle proxy headers)
        ip_address = request.headers.get("x-forwarded-for", "")
        if ip_address:
            ip_address = ip_address.split(",")[0].strip()
        else:
            ip_address = request.client.host if request.client else "unknown"

        # Get user agent and referer
        user_agent = request.headers.get("user-agent", "")
        referer = request.headers.get("referer", "")

        # Extract proxy key from session or cookies if available
        proxy_key_id = None
        # TODO: Add session/cookie extraction when auth is implemented

        # Process the request
        response = await call_next(request)

        # Record page view asynchronously (non-blocking)
        asyncio.create_task(
            self._record_page_view(
                path=path,
                page_name=self._extract_page_name(path),
                ip_address=ip_address,
                user_agent=user_agent,
                referer=referer,
                method=request.method,
                proxy_key_id=proxy_key_id,
            )
        )

        return response

    @staticmethod
    def _extract_page_name(path: str) -> str:
        """Extract human-readable page name from path."""
        path_parts = path.strip("/").split("/")

        # Map known routes to page names
        route_map = {
            "": "Home",
            "dashboard": "Dashboard",
            "requests": "All Requests",
            "system-prompts": "System Prompts",
            "applications": "Applications",
            "docs": "API Documentation",
        }

        if path_parts[0] in route_map:
            return route_map[path_parts[0]]

        # Handle dynamic routes
        if path_parts[0] == "applications" and len(path_parts) > 1:
            if len(path_parts) == 2:
                return "Application Overview"
            elif path_parts[1] == "analytics":
                return "Application Analytics"
            elif path_parts[1] == "deep-analytics":
                return "Deep Analytics"

        if path_parts[0] == "requests" and len(path_parts) > 1:
            return "Request Details"

        if path_parts[0] == "system-prompts" and len(path_parts) > 1:
            if path_parts[1] == "compare":
                return "Compare Prompts"
            return "Prompt Details"

        return "Unknown"

    @staticmethod
    async def _record_page_view(
        path: str,
        page_name: str,
        ip_address: str,
        user_agent: str,
        referer: str,
        method: str,
        proxy_key_id: str = None,
    ):
        """Record page view in database."""
        try:
            async with AsyncSessionLocal() as session:
                page_view = PageView(
                    path=path,
                    page_name=page_name,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    referer=referer,
                    method=method,
                    proxy_key_id=proxy_key_id,
                )
                session.add(page_view)
                await session.commit()
        except Exception as e:
            # Silently fail - don't break user experience for analytics
            print(f"Failed to record page view: {e}")
