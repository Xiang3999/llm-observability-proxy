"""Web Dashboard routes."""

import re
from typing import Annotated, Optional, List, Dict
from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timedelta

from src.models.database import get_db
from src.models.request_log import RequestLog
from src.models.proxy_key import ProxyKey
from src.models.provider_key import ProviderKey, ProviderType
from src.auth.key_manager import KeyManager
from src.config import settings
from src.web.layout import render_sidebar, render_breadcrumbs, render_app_tabs, render_page

router = APIRouter(tags=["Web"])

# Type alias for database session dependency
DbSession = Annotated[AsyncSession, Depends(get_db)]


def extract_cron_task_info(request_body: Optional[dict]) -> Optional[str]:
    """Extract cron task_id from request body messages.

    Cron messages have format: [cron:task_id Task Name] at the START of user message content.
    Returns the task_id if found, None otherwise.
    """
    if not request_body:
        return None

    messages = request_body.get("messages", [])
    for msg in messages:
        # Only look for user messages
        if msg.get("role") != "user":
            continue

        content = msg.get("content", "")
        if isinstance(content, str):
            # Match pattern at the START of content: [cron:task_id Task Name]
            match = re.search(r'^\[cron:([a-f0-9-]+)\s+[^\]]+\]', content, re.IGNORECASE)
            if match:
                return match.group(1)
        # Also handle array format content (like [{type: "text", text: "..."}])
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text", "")
                    match = re.search(r'^\[cron:([a-f0-9-]+)\s+[^\]]+\]', text, re.IGNORECASE)
                    if match:
                        return match.group(1)
    return None


def get_cache_read_info(request_log: RequestLog) -> str:
    """Get cache read tokens display string."""
    cache_read = request_log.cache_read_tokens
    if cache_read and cache_read > 0:
        return f"{cache_read:,}"
    return "-"


def render_request_table_row(
    req: RequestLog,
    proxy_names: Optional[Dict[str, str]] = None,
    app_id: Optional[str] = None,
    style: str = "default",
) -> str:
    """
    Render a single request log table row.

    Args:
        req: RequestLog instance
        proxy_names: Optional dict mapping proxy_key_id to name
        app_id: Optional app_id for 'from_app' link parameter
        style: 'default' for full table, 'compact' for analytics table,
               'system-prompt' for system prompt detail page

    Returns:
        HTML string for table row
    """
    status_cls = "bg-green-100 text-green-800" if (req.status_code and req.status_code < 400) else "bg-red-100 text-red-800"
    cache_display = get_cache_read_info(req)
    cron_task_id = extract_cron_task_info(req.request_body)
    cron_display = (
        f'<span class="text-xs font-mono text-blue-600">{cron_task_id[:8] if cron_task_id else "-"}</span>'
        if cron_task_id
        else '<span class="text-xs text-gray-400">-</span>'
    )

    if style == "compact":
        # Compact style for Analytics page
        n_msg = len(req.request_body.get("messages", [])) if req.request_body else 0
        from_app = f"?from_app={app_id}" if app_id else ""
        return (
            f'<tr class="hover:bg-gray-50">'
            f'<td class="px-4 py-3 whitespace-nowrap text-xs text-gray-500">{req.created_at.strftime("%m-%d %H:%M")}</td>'
            f'<td class="px-4 py-3 whitespace-nowrap text-xs text-gray-900">{req.model or "-"}</td>'
            f'<td class="px-4 py-3 whitespace-nowrap text-xs text-gray-500">{n_msg}</td>'
            f'<td class="px-4 py-3 whitespace-nowrap text-xs text-gray-500">{req.total_tokens or "-"}</td>'
            f'<td class="px-4 py-3 whitespace-nowrap text-xs text-gray-500">{req.total_latency_ms or "-"}ms</td>'
            f'<td class="px-4 py-3 whitespace-nowrap text-xs"><span class="px-2 py-1 rounded-full text-xs font-semibold {status_cls}">{req.status_code or "N/A"}</span></td>'
            f'<td class="px-4 py-3 whitespace-nowrap text-xs text-gray-500">{cache_display}</td>'
            f'<td class="px-4 py-3 whitespace-nowrap text-xs">{cron_display}</td>'
            f'<td class="px-4 py-3 whitespace-nowrap text-right text-xs font-medium"><a href="/requests/{req.id}{from_app}" class="text-blue-600 hover:text-blue-900">View</a></td>'
            f'</tr>'
        )
    elif style == "system-prompt":
        # System prompt detail style - compact with proxy name
        time_str = req.created_at.strftime("%m-%d %H:%M:%S")
        proxy_name = proxy_names.get(req.proxy_key_id, "Unknown") if proxy_names else "Unknown"
        return (
            f'<tr class="hover:bg-gray-50">'
            f'<td class="px-4 py-3 whitespace-nowrap text-xs text-gray-500">{time_str}</td>'
            f'<td class="px-4 py-3 whitespace-nowrap text-xs text-gray-900">{proxy_name}</td>'
            f'<td class="px-4 py-3 whitespace-nowrap text-xs text-gray-900">{req.model or "-"}</td>'
            f'<td class="px-4 py-3 whitespace-nowrap text-xs"><span class="px-2 py-1 rounded-full text-xs font-semibold {status_cls}">{req.status_code or "N/A"}</span></td>'
            f'<td class="px-4 py-3 whitespace-nowrap text-xs text-gray-500">{req.total_tokens or "-"}</td>'
            f'<td class="px-4 py-3 whitespace-nowrap text-xs text-gray-500">{req.total_latency_ms or "-"}ms</td>'
            f'<td class="px-4 py-3 whitespace-nowrap text-xs text-gray-500">{cache_display}</td>'
            f'<td class="px-4 py-3 whitespace-nowrap text-xs">{cron_display}</td>'
            f'<td class="px-4 py-3 whitespace-nowrap text-right text-xs font-medium">'
            f'<a href="/requests/{req.id}" class="text-blue-600 hover:text-blue-900"><i class="fas fa-eye"></i> View</a>'
            f'</td>'
            f'</tr>'
        )
    else:
        # Default style for Dashboard and Requests pages
        time_str = req.created_at.strftime("%Y-%m-%d %H:%M:%S")
        proxy_name = proxy_names.get(req.proxy_key_id, "Unknown") if proxy_names else "Unknown"
        return (
            f'<tr>'
            f'<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{time_str}</td>'
            f'<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{proxy_name}</td>'
            f'<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{req.model or "-"}</td>'
            f'<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{req.total_tokens or "-"}</td>'
            f'<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{req.total_latency_ms or "-"}ms</td>'
            f'<td class="px-6 py-4 whitespace-nowrap"><span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full {status_cls}">{req.status_code or "N/A"}</span></td>'
            f'<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">${float(req.cost_usd or 0):.4f}</td>'
            f'<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{cache_display}</td>'
            f'<td class="px-6 py-4 whitespace-nowrap text-sm">{cron_display}</td>'
            f'<td class="px-6 py-4 whitespace-nowrap text-right text-sm font-medium"><a href="/requests/{req.id}" class="text-blue-600 hover:text-blue-900"><i class="fas fa-eye"></i> View</a></td>'
            f'</tr>'
        )


def get_prompt_hash(content: str) -> str:
    """Generate short hash for prompt identification."""
    import hashlib
    return hashlib.md5(content.encode()).hexdigest()[:12]


def extract_system_prompts(requests: List[RequestLog]) -> dict:
    """
    Extract system prompts from requests and aggregate.

    Performance optimizations:
    - Single-pass O(n) processing
    - Uses local variable references for speed
    - Early break after finding first system prompt per request

    Returns: {prompt_hash: {"content": str, "count": int, "first_seen": datetime,
                           "last_seen": datetime, "daily_counts": Dict[str, int],
                           "model_counts": Dict[str, int], "requests": List[RequestLog]}}
    """
    from collections import defaultdict

    result = {}

    # Cache local references for speed in tight loop
    _get_prompt_hash = get_prompt_hash
    _strftime = datetime.strftime

    for req in requests:
        request_body = req.request_body or {}
        messages = request_body.get("messages", [])

        for msg in messages:
            if msg.get("role") == "system" and msg.get("content"):
                content = msg.get("content", "")
                if isinstance(content, list):
                    # Handle array format content
                    content = " ".join(
                        item.get("text", "") if isinstance(item, dict) else str(item)
                        for item in content
                    )

                prompt_hash = _get_prompt_hash(content)

                if prompt_hash not in result:
                    result[prompt_hash] = {
                        "content": content,
                        "count": 0,
                        "first_seen": req.created_at,
                        "last_seen": req.created_at,
                        "daily_counts": defaultdict(int),
                        "model_counts": defaultdict(int),
                        "requests": []
                    }

                data = result[prompt_hash]
                data["count"] += 1
                data["requests"].append(req)

                # Update first/last seen
                if req.created_at < data["first_seen"]:
                    data["first_seen"] = req.created_at
                if req.created_at > data["last_seen"]:
                    data["last_seen"] = req.created_at

                # Daily counts
                date_str = req.created_at.strftime("%Y-%m-%d")
                data["daily_counts"][date_str] += 1

                # Model counts
                model = req.model or "unknown"
                data["model_counts"][model] += 1

                break  # Only count first system prompt per request

    # Convert defaultdicts to regular dicts for JSON serialization
    for data in result.values():
        data["daily_counts"] = dict(data["daily_counts"])
        data["model_counts"] = dict(data["model_counts"])

    return result


def calculate_daily_distribution(requests: List[RequestLog]) -> Dict[str, int]:
    """Calculate requests per day."""
    daily = {}
    for req in requests:
        date_str = req.created_at.strftime("%Y-%m-%d")
        daily[date_str] = daily.get(date_str, 0) + 1
    return daily


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: DbSession,
    error: Optional[str] = None,
    success: Optional[str] = None
):
    """Render the main dashboard with management features."""
    # Get summary stats
    result = await db.execute(
        select(
            func.count(RequestLog.id).label("total_requests"),
            func.sum(RequestLog.total_tokens).label("total_tokens"),
            func.avg(RequestLog.total_latency_ms).label("avg_latency")
        )
    )
    row = result.one()

    # Get recent requests
    recent = await db.execute(
        select(RequestLog)
        .order_by(RequestLog.created_at.desc())
        .limit(10)
    )
    recent_requests = recent.scalars().all()

    # Get proxy key names for mapping
    proxy_result = await db.execute(
        select(ProxyKey.id, ProxyKey.name)
    )
    proxy_names = {pk.id: pk.name for pk in proxy_result.all()}

    # Get apps with provider info
    apps_result = await db.execute(
        select(
            ProxyKey.id,
            ProxyKey.name,
            ProxyKey.proxy_key,
            ProxyKey.is_active,
            ProxyKey.created_at,
            ProviderKey.provider,
            ProviderKey.name.label("provider_name"),
            func.count(RequestLog.id).label("request_count")
        )
        .outerjoin(RequestLog, RequestLog.proxy_key_id == ProxyKey.id)
        .join(ProviderKey, ProxyKey.provider_key_id == ProviderKey.id)
        .group_by(
            ProxyKey.id, ProxyKey.name, ProxyKey.proxy_key,
            ProxyKey.is_active, ProxyKey.created_at, ProviderKey.provider, ProviderKey.name
        )
        .order_by(ProxyKey.created_at.desc())
    )
    apps = apps_result.all()

    # Get provider keys
    provider_result = await db.execute(
        select(ProviderKey).order_by(ProviderKey.created_at.desc())
    )
    provider_keys = provider_result.scalars().all()

    # Precompute table rows to avoid f-string nesting (Python 3.9 compat)
    provider_keys_rows = "".join([
        f'<tr><td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">{pk.name}</td>'
        f'<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500"><span class="px-2 py-1 bg-blue-100 text-blue-800 rounded text-xs">{pk.provider.value}</span></td>'
        f'<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{pk.created_at.strftime("%Y-%m-%d %H:%M")}</td>'
        f'<td class="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">'
        f'<button onclick="if(confirm(\'Delete this provider key?\')) window.location.href=\'/delete-provider/{pk.id}\'" class="text-red-600 hover:text-red-900"><i class="fas fa-trash"></i> Delete</button></td></tr>'
        for pk in provider_keys
    ])
    def _proxy_key_row(app):
        q = chr(39)  # single quote for JS (no backslash in f-string)
        cls = "bg-gray-50" if not app.is_active else ""
        status_cls = "bg-green-100 text-green-800" if app.is_active else "bg-red-100 text-red-800"
        toggle_cls = "text-green-600 hover:text-green-900" if not app.is_active else "text-yellow-600 hover:text-yellow-900"
        toggle_txt = "Activate" if not app.is_active else "Deactivate"
        return (
            f'<tr class="{cls}"><td class="px-6 py-4 whitespace-nowrap"><div class="flex flex-col">'
            f'<a href="/applications/{app.id}/analytics" class="text-sm font-medium text-blue-600 hover:text-blue-900" title="View Analytics">{app.name} <i class="fas fa-chart-line text-xs ml-1"></i></a>'
            f'<a href="/applications/{app.id}/deep-analytics" class="text-xs text-purple-600 hover:text-purple-900 mt-1" title="View Deep Analytics"><i class="fas fa-flask mr-1"></i>Deep Analytics</a></div></td>'
            f'<td class="px-6 py-4 text-sm"><div class="flex items-center gap-2"><code class="text-xs bg-gray-100 px-2 py-1 rounded">{app.proxy_key}</code>'
            f'<button onclick="navigator.clipboard.writeText({q}{app.proxy_key}{q});alert({q}Copied!{q})" class="text-gray-400 hover:text-gray-600" title="Copy"><i class="fas fa-copy"></i></button></div></td>'
            f'<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500"><div class="flex flex-col"><span class="px-2 py-1 bg-blue-100 text-blue-800 rounded text-xs inline-block w-fit mb-1">{app.provider.value}</span><span class="text-xs text-gray-400">{app.provider_name}</span></div></td>'
            f'<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{app.request_count}</td>'
            f'<td class="px-6 py-4 whitespace-nowrap"><span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full {status_cls}">{"Active" if app.is_active else "Inactive"}</span></td>'
            f'<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{app.created_at.strftime("%Y-%m-%d")}</td>'
            f'<td class="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">'
            f'<a href="/test-proxy/{app.id}" class="text-blue-600 hover:text-blue-900 mr-3" title="Test connectivity"><i class="fas fa-plug"></i> Test</a>'
            f'<button onclick="window.location.href={q}/toggle-proxy/{app.id}{q}" class="{toggle_cls} mr-3"><i class="fas fa-power-off"></i> {toggle_txt}</button>'
            f'<button onclick="if(confirm({q}Delete this proxy key?{q})) window.location.href={q}/delete-proxy/{app.id}{q}" class="text-red-600 hover:text-red-900"><i class="fas fa-trash"></i> Delete</button></td></tr>'
        )
    proxy_keys_rows = "".join(_proxy_key_row(app) for app in apps)

    recent_requests_rows = "".join(render_request_table_row(req, proxy_names=proxy_names) for req in recent_requests)
    provider_key_options = "".join([f'<option value="{pk.id}">{pk.name} ({pk.provider.value})</option>' for pk in provider_keys])
    provider_key_msg = '<p class="text-sm text-red-500 mt-2">No provider keys configured. Please add a provider key first.</p>' if not provider_keys else ""

    main_content = f"""
            <!-- Alert Messages -->
            {f'<div class="bg-green-100 border border-green-400 text-green-700 px-4 py-3 rounded mb-4">{success}</div>' if success else ''}
            {f'<div class="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded mb-4">{error}</div>' if error else ''}

            <!-- Summary Cards -->
            <div class="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8" id="stats">
                <div class="bg-white rounded-lg shadow p-6">
                    <div class="flex items-center">
                        <div class="p-3 bg-blue-100 rounded-full">
                            <i class="fas fa-exchange-alt text-blue-600"></i>
                        </div>
                        <div class="ml-4">
                            <h3 class="text-sm font-medium text-gray-500">Total Requests</h3>
                            <p class="text-3xl font-bold text-gray-900">{row.total_requests or 0}</p>
                        </div>
                    </div>
                </div>
                <div class="bg-white rounded-lg shadow p-6">
                    <div class="flex items-center">
                        <div class="p-3 bg-green-100 rounded-full">
                            <i class="fas fa-coins text-green-600"></i>
                        </div>
                        <div class="ml-4">
                            <h3 class="text-sm font-medium text-gray-500">Total Tokens</h3>
                            <p class="text-3xl font-bold text-gray-900">{row.total_tokens or 0:,}</p>
                        </div>
                    </div>
                </div>
                <div class="bg-white rounded-lg shadow p-6">
                    <div class="flex items-center">
                        <div class="p-3 bg-yellow-100 rounded-full">
                            <i class="fas fa-clock text-yellow-600"></i>
                        </div>
                        <div class="ml-4">
                            <h3 class="text-sm font-medium text-gray-500">Avg Latency</h3>
                            <p class="text-3xl font-bold text-gray-900">{int(row.avg_latency or 0)}ms</p>
                        </div>
                    </div>
                </div>
                <div class="bg-white rounded-lg shadow p-6">
                    <div class="flex items-center">
                        <div class="p-3 bg-purple-100 rounded-full">
                            <i class="fas fa-application text-purple-600"></i>
                        </div>
                        <div class="ml-4">
                            <h3 class="text-sm font-medium text-gray-500">Applications</h3>
                            <p class="text-3xl font-bold text-gray-900">{len(apps)}</p>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Provider Keys Section -->
            <div class="bg-white rounded-lg shadow mb-8" id="provider-keys">
                <div class="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
                    <h2 class="text-lg font-semibold text-gray-800">
                        <i class="fas fa-key text-blue-500 mr-2"></i>Provider Keys
                    </h2>
                    <button onclick="document.getElementById('add-provider-modal').classList.remove('hidden')"
                            class="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700">
                        <i class="fas fa-plus mr-2"></i>Add Provider Key
                    </button>
                </div>
                <table class="min-w-full divide-y divide-gray-200">
                    <thead class="bg-gray-50">
                        <tr>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Provider</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Created</th>
                            <th class="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">Actions</th>
                        </tr>
                    </thead>
                    <tbody class="bg-white divide-y divide-gray-200">
                        {provider_keys_rows if provider_keys_rows else '<tr><td colspan="4" class="px-6 py-4 text-center text-gray-500">No provider keys configured</td></tr>'}
                    </tbody>
                </table>
            </div>

            <!-- Proxy Keys Section -->
            <div class="bg-white rounded-lg shadow mb-8" id="proxy-keys">
                <div class="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
                    <div>
                        <h2 class="text-lg font-semibold text-gray-800">
                            <i class="fas fa-shield-alt text-green-500 mr-2"></i>Proxy Keys (Applications)
                        </h2>
                        <p class="text-xs text-gray-500 mt-1">
                            <i class="fas fa-info-circle mr-1"></i>
                            Click application name for <span class="text-blue-600 font-medium">Analytics</span> or <span class="text-purple-600 font-medium"><i class="fas fa-flask"></i> Deep Analytics</span>
                        </p>
                    </div>
                    <button onclick="document.getElementById('add-proxy-modal').classList.remove('hidden')"
                            class="bg-green-600 text-white px-4 py-2 rounded-lg hover:bg-green-700">
                        <i class="fas fa-plus mr-2"></i>Add Proxy Key
                    </button>
                </div>
                <table class="min-w-full divide-y divide-gray-200">
                    <thead class="bg-gray-50">
                        <tr>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Proxy Key</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Provider</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Requests</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Created</th>
                            <th class="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">Actions</th>
                        </tr>
                    </thead>
                    <tbody class="bg-white divide-y divide-gray-200">
                        {proxy_keys_rows if proxy_keys_rows else '<tr><td colspan="7" class="px-6 py-4 text-center text-gray-500">No proxy keys configured</td></tr>'}
                    </tbody>
                </table>
            </div>

            <!-- Recent Requests -->
            <div class="bg-white rounded-lg shadow mb-8">
                <div class="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
                    <h2 class="text-lg font-semibold text-gray-800">
                        <i class="fas fa-history text-gray-500 mr-2"></i>Recent Requests
                    </h2>
                    <a href="/requests" class="text-sm text-blue-600 hover:text-blue-800">
                        View All <i class="fas fa-arrow-right ml-1"></i>
                    </a>
                </div>
                <table class="min-w-full divide-y divide-gray-200">
                    <thead class="bg-gray-50">
                        <tr>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Time</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Application</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Model</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Tokens</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Latency</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Cost</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Cache Read</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Cron Task</th>
                            <th class="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">Actions</th>
                        </tr>
                    </thead>
                    <tbody class="bg-white divide-y divide-gray-200">
                        {recent_requests_rows if recent_requests_rows else '<tr><td colspan="10" class="px-6 py-4 text-center text-gray-500">No requests yet</td></tr>'}
                    </tbody>
                </table>
            </div>

        <!-- Add Provider Key Modal -->
        <div id="add-provider-modal" class="hidden fixed inset-0 bg-gray-600 bg-opacity-50 overflow-y-auto h-full w-full">
            <div class="relative top-20 mx-auto p-5 border w-96 shadow-lg rounded-md bg-white">
                <h3 class="text-lg font-medium text-gray-900 mb-4">Add Provider Key</h3>
                <form action="/add-provider" method="POST">
                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700 mb-2">Name</label>
                        <input type="text" name="name" required
                               class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                               placeholder="My OpenAI Key">
                    </div>
                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700 mb-2">Provider</label>
                        <select name="provider" required
                                class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
                            <option value="openai">OpenAI</option>
                            <option value="anthropic">Anthropic</option>
                            <option value="gemini">Google Gemini</option>
                            <option value="custom">Custom</option>
                        </select>
                    </div>
                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700 mb-2">API Key</label>
                        <input type="password" name="api_key" required
                               class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                               placeholder="sk-...">
                    </div>
                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700 mb-2">
                            Base URL (Optional)
                            <i class="fas fa-info-circle text-gray-400 ml-1" title="Custom base URL for compatible providers like Alibaba Bailian"></i>
                        </label>
                        <input type="url" name="base_url"
                               class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                               placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1">
                        <p class="text-xs text-gray-500 mt-1">Leave empty for default. Example for Bailian: https://dashscope.aliyuncs.com/compatible-mode/v1</p>
                    </div>
                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700 mb-2">
                            Supported Models (Optional)
                            <i class="fas fa-info-circle text-gray-400 ml-1" title="Comma-separated list of supported model names"></i>
                        </label>
                        <input type="text" name="supported_models"
                               class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                               placeholder="qwen-plus, qwen-max, qwen-turbo">
                        <p class="text-xs text-gray-500 mt-1">Comma-separated list. First model will be used for testing.</p>
                    </div>
                    <div class="flex gap-2">
                        <button type="submit" class="flex-1 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700">
                            Add Key
                        </button>
                        <button type="button" onclick="document.getElementById('add-provider-modal').classList.add('hidden')"
                                class="flex-1 bg-gray-300 text-gray-700 px-4 py-2 rounded-lg hover:bg-gray-400">
                            Cancel
                        </button>
                    </div>
                </form>
            </div>
        </div>

        <!-- Add Proxy Key Modal -->
        <div id="add-proxy-modal" class="hidden fixed inset-0 bg-gray-600 bg-opacity-50 overflow-y-auto h-full w-full">
            <div class="relative top-20 mx-auto p-5 border w-96 shadow-lg rounded-md bg-white">
                <h3 class="text-lg font-medium text-gray-900 mb-4">Add Proxy Key</h3>
                <form action="/add-proxy" method="POST">
                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700 mb-2">Application Name</label>
                        <input type="text" name="name" required
                               class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500"
                               placeholder="MyApp-Production">
                    </div>
                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700 mb-2">Provider Key</label>
                        <select name="provider_key_id" required
                                class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500">
                            {provider_key_options}
                        </select>
                        {provider_key_msg}
                    </div>
                    <div class="flex gap-2">
                        <button type="submit" class="flex-1 bg-green-600 text-white px-4 py-2 rounded-lg hover:bg-green-700">
                            Create Proxy Key
                        </button>
                        <button type="button" onclick="document.getElementById('add-proxy-modal').classList.add('hidden')"
                                class="flex-1 bg-gray-300 text-gray-700 px-4 py-2 rounded-lg hover:bg-gray-400">
                            Cancel
                        </button>
                    </div>
                </form>
            </div>
        </div>
    """
    breadcrumbs = render_breadcrumbs([("Dashboard", None)])
    sidebar = render_sidebar("dashboard")
    html = render_page(
        "LLM Observability Dashboard",
        sidebar,
        breadcrumbs,
        main_content,
        extra_head='<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>',
    )
    return html


@router.get("/requests", response_class=HTMLResponse)
async def list_requests(
    request: Request,
    db: DbSession,
    page: int = 1,
    app_id: Optional[str] = None,
    model: Optional[str] = None,
    status: Optional[str] = None,
    cron_task: Optional[str] = None
):
    """List all requests with pagination and filters."""
    from sqlalchemy import select, func

    per_page = settings.default_per_page
    offset = (page - 1) * per_page

    # Build base query with filters
    query = select(RequestLog).order_by(RequestLog.created_at.desc())

    if app_id:
        query = query.where(RequestLog.proxy_key_id == app_id)
    if model:
        query = query.where(RequestLog.model == model)
    if status:
        query = query.where(RequestLog.status_code == int(status))

    # Get total count
    count_query = select(func.count(RequestLog.id))
    if app_id:
        count_query = count_query.where(RequestLog.proxy_key_id == app_id)
    if model:
        count_query = count_query.where(RequestLog.model == model)
    if status:
        count_query = count_query.where(RequestLog.status_code == int(status))

    total_result = await db.execute(count_query)
    total_count = total_result.scalar()
    total_pages = (total_count + per_page - 1) // per_page

    # Get requests
    query = query.offset(offset).limit(per_page)
    result = await db.execute(query)
    requests_list = list(result.scalars().all())

    # Get proxy key names
    proxy_result = await db.execute(select(ProxyKey.id, ProxyKey.name))
    proxy_names = {pk.id: pk.name for pk in proxy_result.all()}

    # Get unique apps for filter dropdown
    apps_result = await db.execute(select(ProxyKey.id, ProxyKey.name))
    apps = list(apps_result.all())

    # Get unique models for filter dropdown
    models_result = await db.execute(select(RequestLog.model).distinct())
    models = [m[0] for m in models_result.all() if m[0]]

    app_options = "".join([f'<option value="{app.id}" {"selected" if app_id == app.id else ""}>{app.name}</option>' for app in apps])
    model_options = "".join([f'<option value="{m}" {"selected" if model == m else ""}>{m}</option>' for m in models])

    request_rows = "".join(render_request_table_row(req, proxy_names=proxy_names) for req in requests_list)
    empty_req_msg = '<tr><td colspan="10" class="px-6 py-4 text-center text-gray-500">No requests found</td></tr>' if not requests_list else ""

    prev_q = "&".join([f"app_id={app_id}" if app_id else "", f"model={model}" if model else "", f"status={status}" if status else ""])
    prev_q = "&" + prev_q.strip("&") if prev_q.strip() else ""
    next_q = prev_q
    prev_url = f"/requests?page={max(1, page - 1)}{prev_q}"
    next_url = f"/requests?page={min(total_pages, page + 1)}{next_q}"
    prev_cls = "opacity-50 cursor-not-allowed" if page == 1 else "hover:bg-gray-50"
    next_cls = "opacity-50 cursor-not-allowed" if page == total_pages else "hover:bg-gray-50"
    pagination_html = (
        f'<div class="flex justify-center mt-6"><nav class="flex gap-2">'
        f'<a href="{prev_url}" class="px-4 py-2 bg-white border border-gray-300 rounded-lg {prev_cls}"><i class="fas fa-chevron-left"></i> Previous</a>'
        f'<span class="px-4 py-2 bg-blue-600 text-white rounded-lg">Page {page} of {total_pages}</span>'
        f'<a href="{next_url}" class="px-4 py-2 bg-white border border-gray-300 rounded-lg {next_cls}">Next <i class="fas fa-chevron-right"></i></a>'
        f'</nav></div>'
    ) if total_pages > 1 else ""

    main_content = f"""
            <div class="flex justify-between items-center mb-6">
                <h1 class="text-2xl font-bold text-gray-900">All Requests</h1>
                <div class="text-sm text-gray-500">
                    Showing {len(requests_list)} of {total_count} requests
                </div>
            </div>

            <!-- Filters -->
            <div class="bg-white rounded-lg shadow p-4 mb-6">
                <form method="GET" action="/requests" class="flex flex-wrap gap-4">
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">Application</label>
                        <select name="app_id" class="px-3 py-2 border border-gray-300 rounded-md text-sm">
                            <option value="">All Applications</option>
                            {app_options}
                        </select>
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">Model</label>
                        <select name="model" class="px-3 py-2 border border-gray-300 rounded-md text-sm">
                            <option value="">All Models</option>
                            {model_options}
                        </select>
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">Status</label>
                        <select name="status" class="px-3 py-2 border border-gray-300 rounded-md text-sm">
                            <option value="">All Status</option>
                            <option value="200" {"selected" if status == "200" else ""}>200 OK</option>
                            <option value="400" {"selected" if status == "400" else ""}>400 Bad Request</option>
                            <option value="401" {"selected" if status == "401" else ""}>401 Unauthorized</option>
                            <option value="429" {"selected" if status == "429" else ""}>429 Too Many Requests</option>
                            <option value="500" {"selected" if status == "500" else ""}>500 Server Error</option>
                        </select>
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">Cron Task</label>
                        <input type="text" name="cron_task" value="{cron_task or ''}" placeholder="Task ID or name"
                               class="px-3 py-2 border border-gray-300 rounded-md text-sm"
                               title="Filter by cron task ID">
                    </div>
                    <div class="flex items-end">
                        <button type="submit" class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700">
                            <i class="fas fa-filter mr-2"></i>Filter
                        </button>
                        <a href="/requests" class="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300 ml-2">
                            <i class="fas fa-times"></i>
                        </a>
                    </div>
                </form>
            </div>

            <!-- Requests Table -->
            <div class="bg-white rounded-lg shadow">
                <table class="min-w-full divide-y divide-gray-200">
                    <thead class="bg-gray-50">
                        <tr>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Time</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Application</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Model</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Tokens</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Latency</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Cost</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Cache Read</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Cron Task</th>
                            <th class="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">Actions</th>
                        </tr>
                    </thead>
                    <tbody class="bg-white divide-y divide-gray-200">
                        {request_rows if request_rows else empty_req_msg}
                    </tbody>
                </table>
            </div>

            <!-- Pagination -->
            {pagination_html}
    """
    breadcrumbs = render_breadcrumbs([("Dashboard", "/dashboard"), ("Requests", None)])
    sidebar = render_sidebar("requests")
    html = render_page("All Requests", sidebar, breadcrumbs, main_content)
    return html


@router.post("/add-provider")
async def add_provider_key(
    name: str = Form(...),
    provider: str = Form(...),
    api_key: str = Form(...),
    base_url: Optional[str] = Form(None),
    supported_models: Optional[str] = Form(None),
    db: DbSession = None
):
    """Add a new provider key from the dashboard."""
    key_manager = KeyManager(db)

    try:
        provider_type = ProviderType(provider.lower())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid provider: {provider}")

    # Parse supported_models from comma-separated string to list
    models_list = None
    if supported_models:
        models_list = [m.strip() for m in supported_models.split(",") if m.strip()]

    await key_manager.create_provider_key(
        name=name,
        provider=provider_type,
        api_key=api_key,
        base_url=base_url,
        supported_models=models_list
    )

    return RedirectResponse(url="/dashboard?success=Provider+key+added+successfully", status_code=303)


@router.post("/add-proxy")
async def add_proxy_key(
    name: str = Form(...),
    provider_key_id: str = Form(...),
    db: DbSession = None
):
    """Add a new proxy key from the dashboard."""
    key_manager = KeyManager(db)

    # Verify provider key exists
    provider_key = await key_manager.get_provider_key(provider_key_id)
    if not provider_key:
        return RedirectResponse(url="/dashboard?error=Provider+key+not+found", status_code=303)

    # Create proxy key
    proxy_key, plain_key = await key_manager.create_proxy_key(
        name=name,
        provider_key_id=provider_key_id
    )

    # Show the key in a success message
    return RedirectResponse(
        url=f"/dashboard?success=Proxy+key+created:+{plain_key}",
        status_code=303
    )


@router.get("/delete-provider/{key_id}")
async def delete_provider_key(key_id: str, db: DbSession):
    """Delete a provider key."""
    key_manager = KeyManager(db)
    await key_manager.delete_provider_key(key_id)
    return RedirectResponse(url="/dashboard?success=Provider+key+deleted", status_code=303)


@router.get("/delete-proxy/{key_id}")
async def delete_proxy_key(key_id: str, db: DbSession):
    """Delete a proxy key."""
    key_manager = KeyManager(db)
    await key_manager.delete_proxy_key(key_id)
    return RedirectResponse(url="/dashboard?success=Proxy+key+deleted", status_code=303)


@router.get("/toggle-proxy/{key_id}")
async def toggle_proxy_key(key_id: str, db: DbSession):
    """Toggle proxy key active status."""
    key_manager = KeyManager(db)
    await key_manager.toggle_proxy_key(key_id)
    return RedirectResponse(url="/dashboard?success=Proxy+key+status+updated", status_code=303)


@router.get("/test-proxy/{key_id}")
async def test_proxy_key(key_id: str, db: DbSession):
    """Test proxy key connectivity by making a simple API call."""
    from sqlalchemy import select
    from src.models.proxy_key import ProxyKey
    from src.models.provider_key import ProviderKey
    import httpx

    # Get proxy key with provider info
    result = await db.execute(
        select(ProxyKey, ProviderKey)
        .join(ProviderKey)
        .where(ProxyKey.id == key_id)
    )
    proxy_result = result.one_or_none()

    if not proxy_result:
        return RedirectResponse(url="/dashboard?error=Proxy+key+not+found", status_code=303)

    proxy_key, provider_key = proxy_result

    if not proxy_key.is_active:
        return RedirectResponse(url="/dashboard?error=Proxy+key+is+inactive", status_code=303)

    # Get base URL
    if provider_key.base_url:
        base_url = provider_key.base_url
    else:
        base_urls = {
            "openai": "https://api.openai.com/v1",
            "anthropic": "https://api.anthropic.com/v1",
            "gemini": "https://generativelanguage.googleapis.com/v1beta",
        }
        base_url = base_urls.get(provider_key.provider.value)

    if not base_url:
        return RedirectResponse(url="/dashboard?error=No+base+URL+configured", status_code=303)

    # Build test request based on provider type
    headers = {}
    test_url = f"{base_url}/chat/completions"
    test_body = {}

    if provider_key.provider.value == "anthropic":
        headers = {
            "x-api-key": provider_key.encrypted_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        test_url = f"{base_url}/messages"
        test_body = {
            "model": "claude-3-haiku-20240307",
            "max_tokens": 10,
            "messages": [{"role": "user", "content": "Hi"}]
        }
    else:
        # OpenAI compatible (including Bailian)
        headers = {
            "Authorization": f"Bearer {provider_key.encrypted_key}",
            "content-type": "application/json"
        }
        # Determine model based on supported_models config or base_url
        supported_models = provider_key.supported_models or []
        if supported_models:
            # Use first model from supported_models list
            test_model = supported_models[0]
        elif "coding.dashscope" in base_url:
            # Bailian Coding Plan models
            test_model = "qwen3.5-plus"
        elif "dashscope" in base_url:
            # Alibaba Bailian standard
            test_model = "qwen-plus"
        else:
            # Default OpenAI
            test_model = "gpt-4o-mini"

        test_body = {
            "model": test_model,
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 10
        }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(test_url, headers=headers, json=test_body)

            if response.status_code < 400:
                return RedirectResponse(url="/dashboard?success=Proxy+key+test+PASSED", status_code=303)
            else:
                error_msg = f"Test+FAILED:+{response.status_code}"
                try:
                    error_data = response.json()
                    if "error" in error_data:
                        error_msg += f"+-+{str(error_data['error'])[:50]}"
                except:
                    error_msg += f"+-+{response.text[:50]}"
                return RedirectResponse(url=f"/dashboard?error={error_msg}", status_code=303)
    except httpx.TimeoutException:
        return RedirectResponse(url="/dashboard?error=Test+FAILED:+Request+timeout", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/dashboard?error=Test+FAILED:+{str(e)[:50]}", status_code=303)


@router.get("/requests/{request_id}", response_class=HTMLResponse)
async def view_request_detail(
    request_id: str,
    request: Request,
    db: DbSession,
    from_app: Optional[str] = None,
):
    """View detailed request information."""
    from sqlalchemy import select

    result = await db.execute(
        select(RequestLog).where(RequestLog.id == request_id)
    )
    req = result.scalar_one_or_none()

    if not req:
        raise HTTPException(status_code=404, detail="Request not found")

    # Get proxy key info
    proxy_result = await db.execute(
        select(ProxyKey).where(ProxyKey.id == req.proxy_key_id)
    )
    proxy_key = proxy_result.scalar_one_or_none()

    # Return to previous: when user came from an app page (from_app query param)
    return_to_app_name = None
    if from_app and proxy_key and from_app == proxy_key.id:
        return_to_app_name = proxy_key.name

    def json_preview(data, max_len=200):
        if not data:
            return "None"
        import json
        try:
            formatted = json.dumps(data, indent=2, ensure_ascii=False)
            if len(formatted) > max_len:
                return formatted[:max_len] + "..."
            return formatted
        except:
            return str(data)[:max_len]

    def json_full(data):
        if not data:
            return "None"
        import json
        try:
            return json.dumps(data, indent=2, ensure_ascii=False)
        except:
            return str(data)

    request_body_preview = json_preview(req.request_body)
    request_body_full = json_full(req.request_body)
    response_body_preview = json_preview(req.response_body)
    response_body_full = json_full(req.response_body)

    props_inner = (
        f'<div class="mt-4"><span class="text-sm text-gray-500">Properties:</span><div class="mt-2 bg-gray-50 p-3 rounded text-xs"><pre>{json_full(req.properties)}</pre></div></div>'
        if req.properties else ""
    )
    properties_section = (
        f'<div class="bg-white rounded-lg shadow mb-6"><div class="px-4 py-3 border-b border-gray-200 bg-gray-50">'
        f'<h3 class="font-semibold text-gray-800"><i class="fas fa-tags text-purple-500 mr-2"></i>Properties & Metadata</h3></div>'
        f'<div class="p-4"><div class="grid grid-cols-2 gap-4"><div><span class="text-sm text-gray-500">User ID:</span><span class="ml-2 text-gray-900">{req.user_id or "-"}</span></div>'
        f'<div><span class="text-sm text-gray-500">Session ID:</span><span class="ml-2 text-gray-900">{req.session_id or "-"}</span></div></div>{props_inner}</div></div>'
        if (req.user_id or req.session_id or req.properties) else ""
    )

    return_previous_html = ""
    if return_to_app_name and from_app:
        return_previous_html = f'''
            <div class="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
                <span class="text-sm text-gray-600">From application context:</span>
                <a href="/applications/{from_app}" class="ml-2 text-blue-600 hover:text-blue-800 font-medium">
                    <i class="fas fa-arrow-left mr-1"></i>Return to {return_to_app_name}
                </a>
            </div>
        '''
    back_links = '<div class="flex flex-wrap gap-2 mb-4"><a href="/requests" class="text-sm text-blue-600 hover:text-blue-800"><i class="fas fa-list mr-1"></i>Back to list</a>'
    if proxy_key:
        back_links += f'<span class="text-gray-400">|</span><a href="/applications/{proxy_key.id}" class="text-sm text-blue-600 hover:text-blue-800"><i class="fas fa-cube mr-1"></i>View in Application ({proxy_key.name})</a>'
    back_links += '</div>'

    main_content = f"""
            {return_previous_html}
            {back_links}
            <!-- Header -->
            <div class="bg-white rounded-lg shadow p-6 mb-6">
                <div class="flex items-center justify-between">
                    <div>
                        <h1 class="text-2xl font-bold text-gray-900">Request Details</h1>
                        <p class="text-sm text-gray-500 mt-1">ID: {req.id}</p>
                    </div>
                    <span class="px-4 py-2 rounded-full text-sm font-semibold {'bg-green-100 text-green-800' if req.status_code and req.status_code < 400 else 'bg-red-100 text-red-800'}">
                        {req.status_code or 'N/A'}
                    </span>
                </div>
            </div>

            <!-- Request Info Grid -->
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-sm text-gray-500">Model</div>
                    <div class="text-lg font-semibold text-gray-900">{req.model or '-'}</div>
                </div>
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-sm text-gray-500">Provider</div>
                    <div class="text-lg font-semibold text-gray-900">{req.provider or '-'}</div>
                </div>
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-sm text-gray-500">Path</div>
                    <div class="text-lg font-semibold text-gray-900 text-xs">{req.request_path or '-'}</div>
                </div>
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-sm text-gray-500">Method</div>
                    <div class="text-lg font-semibold text-gray-900">{req.method or '-'}</div>
                </div>
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-sm text-gray-500">Total Tokens</div>
                    <div class="text-lg font-semibold text-gray-900">{req.total_tokens or '-'}</div>
                </div>
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-sm text-gray-500">Prompt Tokens</div>
                    <div class="text-lg font-semibold text-gray-900">{req.prompt_tokens or '-'}</div>
                </div>
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-sm text-gray-500">Completion Tokens</div>
                    <div class="text-lg font-semibold text-gray-900">{req.completion_tokens or '-'}</div>
                </div>
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-sm text-gray-500">Cache Read Tokens</div>
                    <div class="text-lg font-semibold text-gray-900">{req.cache_read_tokens or '-'}</div>
                </div>
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-sm text-gray-500">Cache Creation Tokens</div>
                    <div class="text-lg font-semibold text-gray-900">{req.cache_creation_tokens or '-'}</div>
                </div>
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-sm text-gray-500">Latency</div>
                    <div class="text-lg font-semibold text-gray-900">{req.total_latency_ms or '-'}ms</div>
                </div>
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-sm text-gray-500">Time to First Token</div>
                    <div class="text-lg font-semibold text-gray-900">{req.time_to_first_token_ms or '-'}ms</div>
                </div>
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-sm text-gray-500">Cost</div>
                    <div class="text-lg font-semibold text-gray-900">${float(req.cost_usd or 0):.6f}</div>
                </div>
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-sm text-gray-500">Created At</div>
                    <div class="text-lg font-semibold text-gray-900">{req.created_at.strftime('%Y-%m-%d %H:%M:%S')}</div>
                </div>
                {f'''
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-sm text-gray-500">Application</div>
                    <div class="text-lg font-semibold text-gray-900">{proxy_key.name if proxy_key else "-"}</div>
                </div>
                ''' if proxy_key else ''}
            </div>

            <!-- Request/Response Body -->
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
                <!-- Request Body -->
                <div class="bg-white rounded-lg shadow">
                    <div class="px-4 py-3 border-b border-gray-200 bg-gray-50 flex justify-between items-center">
                        <h3 class="font-semibold text-gray-800">
                            <i class="fas fa-arrow-up text-blue-500 mr-2"></i>Request Body
                        </h3>
                        <button onclick="toggleFullView('request')" class="text-sm text-blue-600 hover:text-blue-800">
                            <i class="fas fa-expand"></i> Expand
                        </button>
                    </div>
                    <div class="p-4">
                        <div id="request-preview" class="json-preview bg-gray-900 text-green-400 p-4 rounded text-xs overflow-auto">
                            <pre>{request_body_preview}</pre>
                        </div>
                        <div id="request-full" class="hidden json-full bg-gray-900 text-green-400 p-4 rounded text-xs overflow-auto mt-4">
                            <pre>{request_body_full}</pre>
                        </div>
                    </div>
                </div>

                <!-- Response Body -->
                <div class="bg-white rounded-lg shadow">
                    <div class="px-4 py-3 border-b border-gray-200 bg-gray-50 flex justify-between items-center">
                        <h3 class="font-semibold text-gray-800">
                            <i class="fas fa-arrow-down text-green-500 mr-2"></i>Response Body
                        </h3>
                        <button onclick="toggleFullView('response')" class="text-sm text-blue-600 hover:text-blue-800">
                            <i class="fas fa-expand"></i> Expand
                        </button>
                    </div>
                    <div class="p-4">
                        <div id="response-preview" class="json-preview bg-gray-900 text-green-400 p-4 rounded text-xs overflow-auto">
                            <pre>{response_body_preview}</pre>
                        </div>
                        <div id="response-full" class="hidden json-full bg-gray-900 text-green-400 p-4 rounded text-xs overflow-auto mt-4">
                            <pre>{response_body_full}</pre>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Properties (if any) -->
            {properties_section}
    """
    breadcrumbs = render_breadcrumbs([
        ("Dashboard", "/dashboard"),
        ("Requests", "/requests"),
        (f"Request {req.id[:8]}", None),
    ])
    sidebar = render_sidebar("requests")
    extra_head = """<style>
            .json-preview { max-height: 200px; overflow-y: auto; }
            .json-full { max-height: 600px; overflow-y: auto; }
            pre { white-space: pre-wrap; word-wrap: break-word; }
        </style>
        <script>
            function toggleFullView(type) {
                var fullEl = document.getElementById(type + '-full');
                var previewEl = document.getElementById(type + '-preview');
                if (fullEl.classList.contains('hidden')) {
                    fullEl.classList.remove('hidden');
                    previewEl.classList.add('hidden');
                } else {
                    fullEl.classList.add('hidden');
                    previewEl.classList.remove('hidden');
                }
            }
        </script>"""
    html = render_page(
        f"Request Detail - {req.id[:8]}",
        sidebar,
        breadcrumbs,
        main_content,
        extra_head=extra_head,
    )
    return html


@router.get("/applications/{app_id}/analytics", response_class=HTMLResponse)
async def view_application_analytics(
    app_id: str,
    db: DbSession,
    days: int = None,
    limit: int = None,
    is_cron_task: Optional[str] = None,
    cron_task: Optional[str] = None,
):
    """View detailed application analytics with prompt analysis and full request history."""
    from sqlalchemy import select, func
    import json
    from datetime import timedelta

    # Use config defaults if not provided
    if days is None:
        days = settings.default_days
    if limit is None:
        limit = settings.default_limit

    # Get proxy key info
    result = await db.execute(
        select(ProxyKey, ProviderKey)
        .join(ProviderKey)
        .where(ProxyKey.id == app_id)
    )
    proxy_result = result.one_or_none()

    if not proxy_result:
        raise HTTPException(status_code=404, detail="Application not found")

    proxy_key, provider_key = proxy_result

    # Get all requests for this application with time range filter
    now = datetime.now()
    if days == 0:
        # All time - no filter
        cutoff_date = now - timedelta(days=365*10)  # Far past
    else:
        cutoff_date = now - timedelta(days=days)

    # Build query with filters
    query = (
        select(RequestLog)
        .where(RequestLog.proxy_key_id == app_id)
        .where(RequestLog.created_at >= cutoff_date)
        .order_by(RequestLog.created_at.desc())
    )

    # Cron task filter
    if is_cron_task == "yes":
        # Will filter in Python after fetching - need to check request body
        pass  # Fetch all, filter below
    elif is_cron_task == "no":
        pass  # Fetch all, filter below

    if cron_task:
        # Filter by specific cron task ID - will filter in Python
        pass  # Fetch all, filter below

    requests_result = await db.execute(query)
    all_requests = list(requests_result.scalars().all())

    # Apply cron task filters in Python (need to parse request body)
    if is_cron_task == "yes" or cron_task:
        filtered_requests = []
        for req in all_requests:
            task_id = extract_cron_task_info(req.request_body)
            if is_cron_task == "yes" and is_cron_task == "no":
                continue  # Both yes and no = no filter
            elif is_cron_task == "yes" and task_id is None:
                continue  # Only want cron tasks, this one has none
            elif is_cron_task == "no" and task_id is not None:
                continue  # Only want non-cron tasks, this one has task
            elif cron_task and task_id != cron_task:
                continue  # Specific task filter
            filtered_requests.append(req)
        all_requests = filtered_requests if filtered_requests else all_requests

    # Re-apply time filter for cron task filtered results
    if days == 0:
        cutoff_date = now - timedelta(days=365*10)
    else:
        cutoff_date = now - timedelta(days=days)
    all_requests = [r for r in all_requests if r.created_at >= cutoff_date]

    # Limit analysis to last 100 requests for performance
    analysis_limit = limit  # Store for display
    analysis_requests = all_requests[:limit]

    # Calculate basic statistics
    total_requests = len(all_requests)
    total_tokens = sum(r.total_tokens or 0 for r in all_requests)
    total_prompt_tokens = sum(r.prompt_tokens or 0 for r in all_requests)
    total_completion_tokens = sum(r.completion_tokens or 0 for r in all_requests)
    total_cost = sum(float(r.cost_usd or 0) for r in all_requests)

    # Calculate average latency
    latencies = [r.total_latency_ms for r in all_requests if r.total_latency_ms]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0

    # Calculate error rate
    error_count = sum(1 for r in all_requests if r.status_code and r.status_code >= 400)
    error_rate = (error_count / total_requests * 100) if total_requests > 0 else 0

    # Prompt Analysis - analyze message roles (limited to last 100)
    role_counts = {"system": 0, "user": 0, "assistant": 0, "tool": 0}
    tool_call_count = 0
    # system_prompts: dict mapping prompt content -> {"count": int, "last_seen": datetime}
    system_prompts = {}
    user_prompt_lengths = []
    messages_per_request = []
    tokens_per_request = []

    for req in analysis_requests:
        request_body = req.request_body or {}
        messages = request_body.get("messages", [])
        messages_per_request.append(len(messages))
        tokens_per_request.append(req.total_tokens or 0)

        for msg in messages:
            role = msg.get("role", "unknown")
            if role in role_counts:
                role_counts[role] += 1

            # Extract system prompts - track count and last seen time
            if role == "system" and msg.get("content"):
                content = msg.get("content", "")
                if isinstance(content, str):
                    if content not in system_prompts:
                        system_prompts[content] = {"count": 0, "last_seen": req.created_at}
                    system_prompts[content]["count"] += 1
                    # Update last_seen to the most recent
                    if req.created_at > system_prompts[content]["last_seen"]:
                        system_prompts[content]["last_seen"] = req.created_at

            # User message length analysis
            if role == "user" and msg.get("content"):
                content = msg.get("content", "")
                if isinstance(content, str):
                    user_prompt_lengths.append(len(content))

            # Tool call detection
            if role == "assistant":
                if msg.get("tool_calls") or msg.get("function_call"):
                    tool_call_count += 1

    # Tool usage analysis (limited to last 100)
    tool_names = {}
    for req in analysis_requests:
        response_body = req.response_body or {}
        choices = response_body.get("choices", [])
        for choice in choices:
            message = choice.get("message", {})
            tool_calls = message.get("tool_calls") or []
            for tc in tool_calls:
                func_info = tc.get("function", {})
                name = func_info.get("name", "")
                if name:
                    tool_names[name] = tool_names.get(name, 0) + 1

    # Calculate prompt characteristics
    avg_messages_per_request = sum(messages_per_request) / len(messages_per_request) if messages_per_request else 0
    avg_user_prompt_length = sum(user_prompt_lengths) / len(user_prompt_lengths) if user_prompt_lengths else 0
    avg_tokens_per_request = sum(tokens_per_request) / len(tokens_per_request) if tokens_per_request else 0

    # Cache Efficiency Analysis
    total_input_tokens = sum(r.prompt_tokens or 0 for r in all_requests)
    total_cache_read_tokens = sum(r.cache_read_tokens or 0 for r in all_requests)
    cache_hit_requests = sum(1 for r in all_requests if r.cache_read_tokens and r.cache_read_tokens > 0)
    cache_hit_rate = (cache_hit_requests / total_requests * 100) if total_requests > 0 else 0
    cache_token_hit_rate = (total_cache_read_tokens / total_input_tokens * 100) if total_input_tokens > 0 else 0

    # Cron Task analysis - collect all unique task IDs and names
    cron_tasks = {}  # {task_id: {"name": str, "count": int, "cache_hits": int}}
    for req in all_requests:
        task_id = extract_cron_task_info(req.request_body)
        if task_id:
            if task_id not in cron_tasks:
                # Extract task name from first request
                request_body = req.request_body or {}
                messages = request_body.get("messages", [])
                task_name = ""
                for msg in messages:
                    if msg.get("role") == "user":
                        content = msg.get("content", "")
                        if isinstance(content, str):
                            match = re.search(r'^\[cron:([a-f0-9-]+)\s+([^\]]+)\]', content, re.IGNORECASE)
                            if match:
                                task_name = match.group(2)
                                break
                cron_tasks[task_id] = {"name": task_name, "count": 0, "cache_hits": 0, "input_tokens": 0, "cache_read_tokens": 0}
            cron_tasks[task_id]["count"] += 1
            if req.cache_read_tokens and req.cache_read_tokens > 0:
                cron_tasks[task_id]["cache_hits"] += 1
            cron_tasks[task_id]["input_tokens"] += req.prompt_tokens or 0
            cron_tasks[task_id]["cache_read_tokens"] += req.cache_read_tokens or 0

    # Model usage distribution
    model_counts = {}
    for r in all_requests:
        model = r.model or "unknown"
        model_counts[model] = model_counts.get(model, 0) + 1

    # Status code distribution
    status_counts = {}
    for r in all_requests:
        status = str(r.status_code) if r.status_code else "N/A"
        status_counts[status] = status_counts.get(status, 0) + 1

    # Daily request counts for trend chart
    daily_counts = {}
    daily_tokens = {}
    for r in all_requests:
        date_str = r.created_at.strftime("%Y-%m-%d")
        daily_counts[date_str] = daily_counts.get(date_str, 0) + 1
        daily_tokens[date_str] = daily_tokens.get(date_str, 0) + (r.total_tokens or 0)
    sorted_dates = sorted(daily_counts.keys())

    # Build system prompts list for modal display
    # Sort by count descending, then by last_seen descending
    import html as html_lib
    system_prompts_sorted = sorted(
        system_prompts.items(),
        key=lambda x: (x[1]["count"], x[1]["last_seen"]),
        reverse=True
    )[:10]  # Top 10 by count

    system_prompts_html = ""
    for idx, (sp, info) in enumerate(system_prompts_sorted):
        prompt_id = f"sys-prompt-{idx}"
        preview = sp[:80] + "..." if len(sp) > 80 else sp
        escaped_sp = html_lib.escape(sp)
        preview_escaped = html_lib.escape(preview)
        count = info["count"]
        last_seen = info["last_seen"].strftime("%m-%d %H:%M") if info["last_seen"] else "N/A"
        system_prompts_html += f'''
            <div class="text-xs bg-gray-50 p-2 rounded border border-gray-200 mb-2">
                <div class="flex justify-between items-center mb-2">
                    <div class="flex items-center gap-2">
                        <span class="px-2 py-0.5 bg-blue-100 text-blue-700 rounded text-xs font-semibold">{count}次</span>
                        <span class="text-gray-500">最近：{last_seen}</span>
                    </div>
                    <button onclick="document.getElementById('modal-{prompt_id}').classList.remove('hidden')"
                            class="px-2 py-1 text-xs bg-blue-100 text-blue-700 rounded hover:bg-blue-200 flex-shrink-0">
                        <i class="fas fa-eye mr-1"></i>查看
                    </button>
                </div>
                <div class="truncate text-gray-600">
                    <i class="fas fa-quote-left text-gray-400 mr-1"></i>{preview_escaped}
                </div>
            </div>
            <div id="modal-{prompt_id}" class="hidden fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onclick="this.classList.add('hidden')">
                <div class="bg-white rounded-lg shadow-xl max-w-2xl max-h-[80vh] overflow-auto m-4" onclick="event.stopPropagation()">
                    <div class="p-4 border-b border-gray-200 flex justify-between items-center sticky top-0 bg-white">
                        <h3 class="text-lg font-semibold text-gray-800"><i class="fas fa-file-code text-purple-500 mr-2"></i>System Prompt #{idx + 1}</h3>
                        <button onclick="document.getElementById('modal-{prompt_id}').classList.add('hidden')" class="text-gray-400 hover:text-gray-600">
                            <i class="fas fa-times text-xl"></i>
                        </button>
                    </div>
                    <div class="p-4">
                        <div class="mb-3 flex gap-4 text-sm">
                            <span class="text-gray-600"><i class="fas fa-chart-bar text-blue-500 mr-1"></i>出现次数：<strong class="text-gray-900">{count}</strong></span>
                            <span class="text-gray-600"><i class="fas fa-clock text-green-500 mr-1"></i>最近出现：<strong class="text-gray-900">{last_seen}</strong></span>
                        </div>
                        <pre class="whitespace-pre-wrap text-sm text-gray-700 bg-gray-50 p-4 rounded border border-gray-200 overflow-x-auto">{escaped_sp}</pre>
                    </div>
                    <div class="p-4 border-t border-gray-200 bg-gray-50 flex justify-between items-center">
                        <span class="text-xs text-gray-500">{len(sp)} characters</span>
                        <span class="text-xs text-gray-500">唯一 ID: {idx + 1}</span>
                    </div>
                </div>
            </div>
        '''
    if not system_prompts_html:
        system_prompts_html = '<p class="text-sm text-gray-500">No system prompts found</p>'
    tool_names_html = "".join([
        f'<span class="px-3 py-1 bg-blue-100 text-blue-800 rounded-full text-sm"><i class="fas fa-wrench mr-1"></i>{name} ({count})</span>'
        for name, count in sorted(tool_names.items(), key=lambda x: -x[1])[:10]
    ])
    tool_usage_msg = '<p class="text-sm text-gray-500">No tool calls detected</p>' if not tool_names else ""
    tool_usage_section = (
        f'<div class="border-t border-gray-200 pt-4"><h3 class="text-sm font-medium text-gray-700 mb-3">Tool Usage</h3>'
        f'<div class="flex flex-wrap gap-2">{tool_names_html if tool_names_html else tool_usage_msg}</div></div>'
        if (tool_names or tool_call_count > 0) else ""
    )
    model_dist_html = "".join([
        f'<div class="flex items-center justify-between py-2 border-b border-gray-100"><span class="text-sm text-gray-700">{model}</span><span class="text-sm font-semibold text-gray-900">{count} ({count/total_requests*100:.1f}%)</span></div>'
        for model, count in sorted(model_counts.items(), key=lambda x: -x[1])
    ])
    status_dist_html = "".join([
        f'<div class="flex items-center justify-between py-2 border-b border-gray-100"><span class="text-sm text-gray-700">Status {status}</span><span class="px-2 py-1 rounded text-xs font-semibold {"bg-green-100 text-green-800" if (status.isdigit() and int(status) < 400) else "bg-red-100 text-red-800"}">{count}</span></div>'
        for status, count in sorted(status_counts.items())
    ])

    request_history_rows = "".join(render_request_table_row(req, app_id=app_id, style="compact") for req in all_requests)
    request_history_empty = '<tr><td colspan="9" class="px-4 py-4 text-center text-gray-500">No requests found</td></tr>' if not all_requests else ""

    app_tabs = render_app_tabs(app_id, proxy_key.name, "analytics")
    breadcrumbs = render_breadcrumbs([
        ("Dashboard", "/dashboard"),
        ("Applications", "/dashboard#proxy-keys"),
        (proxy_key.name, f"/applications/{app_id}"),
        ("Analytics", None),
    ])
    main_content = f"""
            <p class="text-sm text-gray-500 mb-4">Provider: {provider_key.name} ({provider_key.provider.value})</p>
            <!-- Time Range and Analysis Controls -->
            <div class="bg-white rounded-lg shadow p-4 mb-6">
                <form method="GET" class="flex flex-wrap items-end gap-4">
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">
                            <i class="fas fa-calendar mr-1"></i>Time Range
                        </label>
                        <select name="days" onchange="this.form.submit()" class="px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-blue-500 focus:border-blue-500">
                            <option value="1" {'selected' if days == 1 else ''}>Last 24 hours</option>
                            <option value="3" {'selected' if days == 3 else ''}>Last 3 days</option>
                            <option value="7" {'selected' if days == 7 else ''}>Last 7 days</option>
                            <option value="30" {'selected' if days == 30 else ''}>Last 30 days</option>
                            <option value="90" {'selected' if days == 90 else ''}>Last 90 days</option>
                            <option value="0" {'selected' if days == 0 else ''}>All time</option>
                        </select>
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">
                            <i class="fas fa-list mr-1"></i>Analysis Limit
                        </label>
                        <select name="limit" onchange="this.form.submit()" class="px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-blue-500 focus:border-blue-500">
                            <option value="100" {'selected' if limit == 100 else ''}>100 requests</option>
                            <option value="500" {'selected' if limit == 500 else ''}>500 requests</option>
                            <option value="1000" {'selected' if limit == 1000 else ''}>1000 requests</option>
                            <option value="5000" {'selected' if limit == 5000 else ''}>5000 requests</option>
                        </select>
                    </div>
                    <div class="flex-1 text-right">
                        <span class="text-sm text-gray-500">
                            <i class="fas fa-info-circle mr-1"></i>
                            Showing data for <span class="font-medium text-blue-600">{days if days > 0 else 'all'} days</span> / Analyzing last <span class="font-medium text-blue-600">{analysis_limit}</span> requests
                        </span>
                    </div>
                </form>
            </div>

            <!-- Summary Stats -->
            <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-4 mb-6">
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-xs text-gray-500">Requests</div>
                    <div class="text-xl font-bold text-gray-900">{total_requests}</div>
                </div>
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-xs text-gray-500">Tokens</div>
                    <div class="text-xl font-bold text-gray-900">{total_tokens:,}</div>
                </div>
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-xs text-gray-500">Avg Tokens/Req</div>
                    <div class="text-xl font-bold text-gray-900">{avg_tokens_per_request:.0f}</div>
                </div>
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-xs text-gray-500">Prompt Tokens</div>
                    <div class="text-xl font-bold text-gray-900">{total_prompt_tokens:,}</div>
                </div>
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-xs text-gray-500">Completion Tokens</div>
                    <div class="text-xl font-bold text-gray-900">{total_completion_tokens:,}</div>
                </div>
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-xs text-gray-500">Avg Latency</div>
                    <div class="text-xl font-bold text-gray-900">{avg_latency:.0f}ms</div>
                </div>
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-xs text-gray-500">Cost</div>
                    <div class="text-xl font-bold text-gray-900">${total_cost:.4f}</div>
                </div>
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-xs text-gray-500">Error Rate</div>
                    <div class="text-xl font-bold {'text-green-600' if error_rate < 5 else 'text-yellow-600' if error_rate < 20 else 'text-red-600'}">{error_rate:.1f}%</div>
                </div>
            </div>

            <!-- Cache Efficiency Analysis -->
            <div class="bg-white rounded-lg shadow p-6 mb-6">
                <h2 class="text-lg font-semibold text-gray-800 mb-4">
                    <i class="fas fa-bolt text-yellow-500 mr-2"></i>Cache Efficiency Analysis
                </h2>

                <!-- Cache Stats Summary -->
                <div class="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
                    <div class="bg-gradient-to-br from-blue-50 to-blue-100 rounded-lg p-4 border border-blue-200">
                        <div class="text-xs text-blue-600 font-medium">Total Input Tokens</div>
                        <div class="text-2xl font-bold text-blue-900 mt-1">{total_input_tokens:,}</div>
                    </div>
                    <div class="bg-gradient-to-br from-green-50 to-green-100 rounded-lg p-4 border border-green-200">
                        <div class="text-xs text-green-600 font-medium">Cache Read Tokens</div>
                        <div class="text-2xl font-bold text-green-900 mt-1">{total_cache_read_tokens:,}</div>
                    </div>
                    <div class="bg-gradient-to-br from-purple-50 to-purple-100 rounded-lg p-4 border border-purple-200">
                        <div class="text-xs text-purple-600 font-medium">Cache Token Hit Rate</div>
                        <div class="text-2xl font-bold text-purple-900 mt-1">{cache_token_hit_rate:.1f}%</div>
                    </div>
                    <div class="bg-gradient-to-br from-orange-50 to-orange-100 rounded-lg p-4 border border-orange-200">
                        <div class="text-xs text-orange-600 font-medium">Cache Hit Requests</div>
                        <div class="text-2xl font-bold text-orange-900 mt-1">{cache_hit_requests:,}</div>
                    </div>
                    <div class="bg-gradient-to-br from-pink-50 to-pink-100 rounded-lg p-4 border border-pink-200">
                        <div class="text-xs text-pink-600 font-medium">Request Cache Hit Rate</div>
                        <div class="text-2xl font-bold text-pink-900 mt-1">{cache_hit_rate:.1f}%</div>
                    </div>
                </div>

                <!-- Cron Task Filter -->
                <div class="border-t border-gray-200 pt-4">
                    <form method="GET" class="flex flex-wrap items-end gap-4">
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-1">
                                <i class="fas fa-robot mr-1"></i>Is Cron Task
                            </label>
                            <select name="is_cron_task" onchange="this.form.submit()" class="px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-blue-500 focus:border-blue-500">
                                <option value="">All</option>
                                <option value="yes" {'selected' if is_cron_task == 'yes' else ''}>Yes (Cron Tasks)</option>
                                <option value="no" {'selected' if is_cron_task == 'no' else ''}>No (Regular)</option>
                            </select>
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-1">
                                <i class="fas fa-tasks mr-1"></i>Select Cron Task
                            </label>
                            <select name="cron_task" onchange="this.form.submit()" class="px-3 py-2 border border-gray-300 rounded-md text-sm min-w-[250px] focus:ring-blue-500 focus:border-blue-500">
                                <option value="">All Tasks</option>
                                {"".join(f'<option value="{tid}" {"selected" if cron_task == tid else ""}>{tinfo["name"]} ({tid[:8]}...) - {tinfo["count"]} reqs</option>' for tid, tinfo in sorted(cron_tasks.items(), key=lambda x: -x[1]["count"]))}
                            </select>
                        </div>
                        <div class="flex-1">
                            <a href="/applications/{app_id}/analytics?days={days}&limit={limit}" class="inline-flex items-center px-4 py-2 bg-gray-100 text-gray-700 rounded-md text-sm hover:bg-gray-200">
                                <i class="fas fa-times mr-2"></i>Clear Filters
                            </a>
                        </div>
                    </form>
                </div>

                <!-- Cron Task Details Table -->
                {"".join(f'''
                <div class="mt-4">
                    <h4 class="text-sm font-medium text-gray-700 mb-2">Cron Task: {tinfo["name"]} ({tid[:8]}...)</h4>
                    <div class="grid grid-cols-4 gap-3">
                        <div class="bg-gray-50 rounded p-2 text-center">
                            <div class="text-xs text-gray-500">Requests</div>
                            <div class="font-semibold text-gray-900">{tinfo["count"]}</div>
                        </div>
                        <div class="bg-blue-50 rounded p-2 text-center">
                            <div class="text-xs text-blue-600">Input Tokens</div>
                            <div class="font-semibold text-blue-900">{tinfo["input_tokens"]:,}</div>
                        </div>
                        <div class="bg-green-50 rounded p-2 text-center">
                            <div class="text-xs text-green-600">Cache Read Tokens</div>
                            <div class="font-semibold text-green-900">{tinfo["cache_read_tokens"]:,}</div>
                        </div>
                        <div class="bg-purple-50 rounded p-2 text-center">
                            <div class="text-xs text-purple-600">Cache Hit Rate</div>
                            <div class="font-semibold text-purple-900">{(tinfo["cache_read_tokens"]/tinfo["input_tokens"]*100) if tinfo["input_tokens"] > 0 else 0:.1f}%</div>
                        </div>
                    </div>
                </div>''' for tid, tinfo in sorted(cron_tasks.items(), key=lambda x: -x[1]["count"])[:5]) if cron_tasks else '<p class="text-sm text-gray-500 text-center py-4">No cron tasks found</p>'}
            </div>

            <!-- Prompt Analysis Section -->
            <div class="bg-white rounded-lg shadow p-6 mb-6">
                <h2 class="text-lg font-semibold text-gray-800 mb-4">
                    <i class="fas fa-comment-alt text-purple-500 mr-2"></i>Prompt Analysis
                </h2>

                <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-6">
                    <!-- Message Role Distribution -->
                    <div>
                        <h3 class="text-sm font-medium text-gray-700 mb-3">Message Roles</h3>
                        <div class="space-y-2">
                            <div class="flex justify-between items-center">
                                <span class="text-sm text-gray-600"><i class="fas fa-cog text-blue-500 mr-1"></i>System</span>
                                <span class="text-sm font-semibold">{role_counts['system']}</span>
                            </div>
                            <div class="flex justify-between items-center">
                                <span class="text-sm text-gray-600"><i class="fas fa-user text-green-500 mr-1"></i>User</span>
                                <span class="text-sm font-semibold">{role_counts['user']}</span>
                            </div>
                            <div class="flex justify-between items-center">
                                <span class="text-sm text-gray-600"><i class="fas fa-robot text-yellow-500 mr-1"></i>Assistant</span>
                                <span class="text-sm font-semibold">{role_counts['assistant']}</span>
                            </div>
                            <div class="flex justify-between items-center">
                                <span class="text-sm text-gray-600"><i class="fas fa-tools text-gray-500 mr-1"></i>Tool</span>
                                <span class="text-sm font-semibold">{role_counts['tool']}</span>
                            </div>
                        </div>
                    </div>

                    <!-- Prompt Characteristics -->
                    <div>
                        <h3 class="text-sm font-medium text-gray-700 mb-3">Prompt Characteristics</h3>
                        <div class="space-y-2">
                            <div class="flex justify-between items-center">
                                <span class="text-sm text-gray-600">Avg Messages/Req</span>
                                <span class="text-sm font-semibold">{avg_messages_per_request:.2f}</span>
                            </div>
                            <div class="flex justify-between items-center">
                                <span class="text-sm text-gray-600">Avg User Prompt Length</span>
                                <span class="text-sm font-semibold">{avg_user_prompt_length:.0f} chars</span>
                            </div>
                            <div class="flex justify-between items-center">
                                <span class="text-sm text-gray-600">Avg Tokens/Req</span>
                                <span class="text-sm font-semibold">{avg_tokens_per_request:.0f}</span>
                            </div>
                            <div class="flex justify-between items-center">
                                <span class="text-sm text-gray-600">Tool Calls</span>
                                <span class="text-sm font-semibold">{tool_call_count}</span>
                            </div>
                        </div>
                    </div>

                    <!-- System Prompts -->
                    <div class="lg:col-span-2">
                        <div class="flex justify-between items-center mb-3">
                            <h3 class="text-sm font-medium text-gray-700">
                                System Prompts ({len(system_prompts)} unique, {sum(info['count'] for info in system_prompts.values())} total)
                            </h3>
                            <a href="/system-prompts" class="text-xs text-blue-600 hover:text-blue-800">
                                <i class="fas fa-external-link-alt mr-1"></i>Full Analysis
                            </a>
                        </div>
                        <div class="space-y-2 max-h-40 overflow-y-auto">
                            {system_prompts_html}
                        </div>
                    </div>
                </div>

                <!-- Tool Usage -->
                {tool_usage_section}
            </div>

            <!-- Charts Section -->
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
                <!-- Request Trend -->
                <div class="bg-white rounded-lg shadow p-6">
                    <h3 class="text-lg font-semibold text-gray-800 mb-4">
                        <i class="fas fa-chart-line text-blue-500 mr-2"></i>Request Trend
                    </h3>
                    <div class="h-64 min-h-[256px]" style="position:relative;">
                        <canvas id="trendChart" width="400" height="256"></canvas>
                    </div>
                </div>

                <!-- Role Distribution -->
                <div class="bg-white rounded-lg shadow p-6">
                    <h3 class="text-lg font-semibold text-gray-800 mb-4">
                        <i class="fas fa-chart-pie text-purple-500 mr-2"></i>Message Role Distribution
                    </h3>
                    <div class="h-64 min-h-[256px]" style="position:relative;">
                        <canvas id="roleChart" width="400" height="256"></canvas>
                    </div>
                </div>
            </div>

            <!-- Model and Status Distribution -->
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
                <!-- Model Distribution -->
                <div class="bg-white rounded-lg shadow p-6">
                    <h3 class="text-lg font-semibold text-gray-800 mb-4">
                        <i class="fas fa-chart-bar text-green-500 mr-2"></i>Model Usage
                    </h3>
                    <div class="space-y-2">
                        {model_dist_html}
                    </div>
                </div>

                <!-- Status Distribution -->
                <div class="bg-white rounded-lg shadow p-6">
                    <h3 class="text-lg font-semibold text-gray-800 mb-4">
                        <i class="fas fa-chart-bar text-yellow-500 mr-2"></i>Status Codes
                    </h3>
                    <div class="space-y-2">
                        {status_dist_html}
                    </div>
                </div>
            </div>

            <!-- Full Request History -->
            <div class="bg-white rounded-lg shadow mb-6">
                <div class="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
                    <h3 class="text-lg font-semibold text-gray-800">
                        <i class="fas fa-history text-gray-500 mr-2"></i>Full Request History
                    </h3>
                    <a href="/requests?app_id={app_id}" class="text-sm text-blue-600 hover:text-blue-800">
                        View with Filters <i class="fas fa-arrow-right ml-1"></i>
                    </a>
                </div>
                <div class="overflow-x-auto">
                    <table class="min-w-full divide-y divide-gray-200">
                        <thead class="bg-gray-50">
                            <tr>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Time</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Model</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Messages</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Tokens</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Latency</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Cache Read</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Cron Task</th>
                                <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Actions</th>
                            </tr>
                        </thead>
                        <tbody class="bg-white divide-y divide-gray-200">
                            {request_history_rows if request_history_rows else request_history_empty}
                        </tbody>
                    </table>
                </div>
            </div>
    """
    # Build chart configs as JSON to avoid f-string brace escaping errors
    trend_config = {
        "type": "line",
        "data": {
            "labels": sorted_dates,
            "datasets": [
                {"label": "Requests", "data": [daily_counts[d] for d in sorted_dates], "borderColor": "rgb(59, 130, 246)", "backgroundColor": "rgba(59, 130, 246, 0.1)", "fill": True, "tension": 0.4, "yAxisID": "y"},
                {"label": "Tokens (K)", "data": [round(daily_tokens[d] / 1000, 1) for d in sorted_dates], "borderColor": "rgb(34, 197, 94)", "backgroundColor": "rgba(34, 197, 94, 0.1)", "fill": True, "tension": 0.4, "yAxisID": "y1"},
            ],
        },
        "options": {
            "responsive": True,
            "maintainAspectRatio": False,
            "plugins": {"legend": {"display": True, "position": "top"}},
            "scales": {
                "x": {"grid": {"display": False}},
                "y": {"type": "linear", "display": True, "position": "left", "beginAtZero": True, "ticks": {"stepSize": 1}, "title": {"display": True, "text": "Requests"}},
                "y1": {"type": "linear", "display": True, "position": "right", "beginAtZero": True, "grid": {"drawOnChartArea": False}, "title": {"display": True, "text": "Tokens (K)"}},
            },
        },
    }
    role_config = {
        "type": "doughnut",
        "data": {
            "labels": ["System", "User", "Assistant", "Tool"],
            "datasets": [{"data": [role_counts["system"], role_counts["user"], role_counts["assistant"], role_counts["tool"]], "backgroundColor": ["rgb(59, 130, 246)", "rgb(34, 197, 94)", "rgb(251, 191, 36)", "rgb(107, 114, 128)"]}],
        },
        "options": {"responsive": True, "maintainAspectRatio": False, "plugins": {"legend": {"position": "bottom"}}},
    }
    # Inline config as JS variable (JSON is valid JS); escape </ to avoid closing script tag
    trend_js = json.dumps(trend_config).replace("</", "<\\/")
    role_js = json.dumps(role_config).replace("</", "<\\/")
    chart_head = '<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>'
    chart_footer = f"""
        <script>
            window._analyticsTrendConfig = {trend_js};
            window._analyticsRoleConfig = {role_js};
            function initAnalyticsCharts() {{
                if (typeof Chart === "undefined") {{ window.setTimeout(initAnalyticsCharts, 80); return; }}
                var trendEl = document.getElementById("trendChart");
                if (trendEl && window._analyticsTrendConfig) {{
                    try {{ new Chart(trendEl.getContext("2d"), window._analyticsTrendConfig); }} catch(e) {{ console.error("Trend chart:", e); }}
                    window._analyticsTrendConfig = null;
                }}
                var roleEl = document.getElementById("roleChart");
                if (roleEl && window._analyticsRoleConfig) {{
                    try {{ new Chart(roleEl.getContext("2d"), window._analyticsRoleConfig); }} catch(e) {{ console.error("Role chart:", e); }}
                    window._analyticsRoleConfig = null;
                }}
            }}
            window.addEventListener("load", initAnalyticsCharts);
        </script>
    """
    sidebar = render_sidebar("applications")
    html = render_page(
        f"Analytics: {proxy_key.name}",
        sidebar,
        breadcrumbs,
        main_content,
        extra_head=chart_head,
        app_tabs_html=app_tabs,
        extra_footer_script=chart_footer,
    )
    return html


@router.get("/applications/{app_id}", response_class=HTMLResponse)
async def view_application_detail(app_id: str, db: DbSession):
    """View detailed application analytics and request history."""
    from sqlalchemy import select, func

    # Get proxy key info
    result = await db.execute(
        select(ProxyKey, ProviderKey)
        .join(ProviderKey)
        .where(ProxyKey.id == app_id)
    )
    proxy_result = result.one_or_none()

    if not proxy_result:
        raise HTTPException(status_code=404, detail="Application not found")

    proxy_key, provider_key = proxy_result

    # Get all requests for this application
    requests_result = await db.execute(
        select(RequestLog)
        .where(RequestLog.proxy_key_id == app_id)
        .order_by(RequestLog.created_at.desc())
    )
    all_requests = list(requests_result.scalars().all())

    # Calculate statistics
    total_requests = len(all_requests)
    total_tokens = sum(r.total_tokens or 0 for r in all_requests)
    total_prompt_tokens = sum(r.prompt_tokens or 0 for r in all_requests)
    total_completion_tokens = sum(r.completion_tokens or 0 for r in all_requests)
    total_cost = sum(float(r.cost_usd or 0) for r in all_requests)

    # Calculate average latency
    latencies = [r.total_latency_ms for r in all_requests if r.total_latency_ms]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0

    # Calculate error rate
    error_count = sum(1 for r in all_requests if r.status_code and r.status_code >= 400)
    error_rate = (error_count / total_requests * 100) if total_requests > 0 else 0

    # Model usage distribution
    model_counts = {}
    for r in all_requests:
        model = r.model or "unknown"
        model_counts[model] = model_counts.get(model, 0) + 1

    # Status code distribution
    status_counts = {}
    for r in all_requests:
        status = str(r.status_code) if r.status_code else "N/A"
        status_counts[status] = status_counts.get(status, 0) + 1

    # Recent requests (last 20)
    recent_requests = all_requests[:20]

    app_model_dist_html = "".join([
        f'<div class="flex items-center justify-between py-2 border-b border-gray-100"><span class="text-sm text-gray-700">{model}</span><span class="text-sm font-semibold text-gray-900">{count} ({count/total_requests*100:.1f}%)</span></div>'
        for model, count in model_counts.items()
    ]) if model_counts else '<p class="text-sm text-gray-500 text-center py-4">No model data</p>'
    app_status_dist_html = "".join([
        f'<div class="flex items-center justify-between py-2 border-b border-gray-100"><span class="text-sm text-gray-700">Status {status}</span><span class="px-2 py-1 rounded text-xs font-semibold {"bg-green-100 text-green-800" if (status.isdigit() and int(status) < 400) else "bg-red-100 text-red-800"}">{count}</span></div>'
        for status, count in sorted(status_counts.items())
    ]) if status_counts else '<p class="text-sm text-gray-500 text-center py-4">No status data</p>'

    def _app_recent_row(req):
        status_cls = "bg-green-100 text-green-800" if (req.status_code and req.status_code < 400) else "bg-red-100 text-red-800"
        return (
            f'<tr><td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{req.created_at.strftime("%Y-%m-%d %H:%M:%S")}</td>'
            f'<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{req.model or "-"}</td>'
            f'<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{req.total_tokens or "-"}</td>'
            f'<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{req.total_latency_ms or "-"}ms</td>'
            f'<td class="px-6 py-4 whitespace-nowrap"><span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full {status_cls}">{req.status_code or "N/A"}</span></td>'
            f'<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">${float(req.cost_usd or 0):.4f}</td>'
            f'<td class="px-6 py-4 whitespace-nowrap text-right text-sm font-medium"><a href="/requests/{req.id}?from_app={app_id}" class="text-blue-600 hover:text-blue-900"><i class="fas fa-eye"></i> View</a></td></tr>'
        )
    app_recent_rows = "".join(_app_recent_row(req) for req in recent_requests)
    app_recent_empty = '<tr><td colspan="7" class="px-6 py-4 text-center text-gray-500">No requests yet</td></tr>' if not recent_requests else ""

    app_tabs = render_app_tabs(proxy_key.id, proxy_key.name, "overview")
    breadcrumbs = render_breadcrumbs([
        ("Dashboard", "/dashboard"),
        ("Applications", "/dashboard#proxy-keys"),
        (proxy_key.name, None),
    ])
    main_content = f"""
            <!-- Application Header -->
            <div class="bg-white rounded-lg shadow p-6 mb-6">
                <div class="flex items-center justify-between">
                    <div>
                        <div class="flex items-center gap-3">
                            <h1 class="text-2xl font-bold text-gray-900">{proxy_key.name}</h1>
                            <span class="px-3 py-1 rounded-full text-xs font-semibold {'bg-green-100 text-green-800' if proxy_key.is_active else 'bg-red-100 text-red-800'}">
                                {'Active' if proxy_key.is_active else 'Inactive'}
                            </span>
                        </div>
                        <p class="text-sm text-gray-500 mt-2">
                            <i class="fas fa-key mr-1"></i>Key: <code class="bg-gray-100 px-2 py-1 rounded text-xs">{proxy_key.proxy_key}</code>
                        </p>
                        <p class="text-sm text-gray-500 mt-1">
                            <i class="fas fa-cloud mr-1"></i>Provider: <span class="px-2 py-1 bg-blue-100 text-blue-800 rounded text-xs">{provider_key.provider.value}</span>
                            <span class="ml-2 text-gray-600">{provider_key.name}</span>
                        </p>
                    </div>
                    <div class="flex gap-2">
                        <a href="/toggle-proxy/{proxy_key.id}" class="px-4 py-2 {'bg-green-600 hover:bg-green-700' if not proxy_key.is_active else 'bg-yellow-600 hover:bg-yellow-700'} text-white rounded-lg">
                            {'Activate' if not proxy_key.is_active else 'Deactivate'}
                        </a>
                        <a href="/dashboard" onclick="if(confirm('Delete this application?')) window.location.href='/delete-proxy/{proxy_key.id}'" class="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg">
                            <i class="fas fa-trash"></i> Delete
                        </a>
                    </div>
                </div>
            </div>

            <!-- Summary Stats -->
            <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-6">
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-sm text-gray-500">Total Requests</div>
                    <div class="text-2xl font-bold text-gray-900">{total_requests}</div>
                </div>
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-sm text-gray-500">Total Tokens</div>
                    <div class="text-2xl font-bold text-gray-900">{total_tokens:,}</div>
                </div>
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-sm text-gray-500">Prompt Tokens</div>
                    <div class="text-2xl font-bold text-gray-900">{total_prompt_tokens:,}</div>
                </div>
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-sm text-gray-500">Completion Tokens</div>
                    <div class="text-2xl font-bold text-gray-900">{total_completion_tokens:,}</div>
                </div>
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-sm text-gray-500">Avg Latency</div>
                    <div class="text-2xl font-bold text-gray-900">{avg_latency:.0f}ms</div>
                </div>
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-sm text-gray-500">Total Cost</div>
                    <div class="text-2xl font-bold text-gray-900">${total_cost:.4f}</div>
                </div>
            </div>

            <!-- Analytics Grid -->
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
                <!-- Model Distribution -->
                <div class="bg-white rounded-lg shadow p-6">
                    <h3 class="text-lg font-semibold text-gray-800 mb-4">
                        <i class="fas fa-chart-pie text-blue-500 mr-2"></i>Model Usage
                    </h3>
                    <div class="space-y-2">
                        {app_model_dist_html}
                    </div>
                </div>

                <!-- Status Code Distribution -->
                <div class="bg-white rounded-lg shadow p-6">
                    <h3 class="text-lg font-semibold text-gray-800 mb-4">
                        <i class="fas fa-chart-bar text-green-500 mr-2"></i>Status Codes
                    </h3>
                    <div class="space-y-2">
                        {app_status_dist_html}
                    </div>
                </div>
            </div>

            <!-- Error Rate -->
            <div class="bg-white rounded-lg shadow p-6 mb-6">
                <h3 class="text-lg font-semibold text-gray-800 mb-4">
                    <i class="fas fa-exclamation-triangle text-yellow-500 mr-2"></i>Error Analysis
                </h3>
                <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div>
                        <div class="text-sm text-gray-500">Error Rate</div>
                        <div class="text-2xl font-bold {'text-green-600' if error_rate < 5 else 'text-yellow-600' if error_rate < 20 else 'text-red-600'}">{error_rate:.2f}%</div>
                    </div>
                    <div>
                        <div class="text-sm text-gray-500">Total Errors</div>
                        <div class="text-2xl font-bold text-gray-900">{error_count}</div>
                    </div>
                    <div>
                        <div class="text-sm text-gray-500">Successful Requests</div>
                        <div class="text-2xl font-bold text-green-600">{total_requests - error_count}</div>
                    </div>
                </div>
            </div>

            <!-- Recent Requests Table -->
            <div class="bg-white rounded-lg shadow mb-6">
                <div class="px-6 py-4 border-b border-gray-200">
                    <h3 class="text-lg font-semibold text-gray-800">
                        <i class="fas fa-history text-gray-500 mr-2"></i>Recent Requests (Last 20)
                    </h3>
                </div>
                <table class="min-w-full divide-y divide-gray-200">
                    <thead class="bg-gray-50">
                        <tr>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Time</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Model</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Tokens</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Latency</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Cost</th>
                            <th class="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">Actions</th>
                        </tr>
                    </thead>
                    <tbody class="bg-white divide-y divide-gray-200">
                        {app_recent_rows if app_recent_rows else app_recent_empty}
                    </tbody>
                </table>
            </div>
    """
    sidebar = render_sidebar("applications")
    html = render_page(
        f"Application: {proxy_key.name}",
        sidebar,
        breadcrumbs,
        main_content,
        extra_head='<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>',
        app_tabs_html=app_tabs,
    )
    return html


# =============================================================================
# System Prompts Analysis Routes
# =============================================================================

@router.get("/system-prompts", response_class=HTMLResponse)
async def list_system_prompts(
    request: Request,
    db: DbSession,
    app_id: Optional[str] = None,
    model: Optional[str] = None,
    status: Optional[str] = None,
    cron_task: Optional[str] = None,
    days: int = None,
    limit: int = None,
    page: int = 1,
):
    """List all system prompts with aggregation and filters."""
    from sqlalchemy import select, func
    import html as html_lib

    # Use config defaults if not provided
    if days is None:
        days = settings.default_days
    if limit is None:
        limit = settings.default_limit
    per_page = settings.system_prompts_per_page
    offset = (page - 1) * per_page

    # Build base query with filters
    query = select(RequestLog).order_by(RequestLog.created_at.desc())

    if app_id:
        query = query.where(RequestLog.proxy_key_id == app_id)
    if model:
        query = query.where(RequestLog.model == model)
    if status:
        query = query.where(RequestLog.status_code == int(status))

    # Time range filter
    now = datetime.now()
    if days > 0:
        cutoff = now - timedelta(days=days)
        query = query.where(RequestLog.created_at >= cutoff)

    # Get all requests for processing (no limit at query level for accurate aggregation)
    result = await db.execute(query)
    all_requests = list(result.scalars().all())

    # Apply cron task filter if specified (in Python since it's in JSON body)
    if cron_task:
        filtered_requests = []
        for req in all_requests:
            task_id = extract_cron_task_info(req.request_body)
            if task_id and (cron_task.lower() in task_id.lower() or cron_task.lower() in str(req.request_body).lower()):
                filtered_requests.append(req)
        all_requests = filtered_requests

    # Apply limit for processing (cap at max for performance)
    limit = min(limit, settings.max_analysis_limit)
    analysis_requests = all_requests[:limit]

    # Extract and aggregate system prompts
    system_prompts = extract_system_prompts(analysis_requests)

    # Calculate totals
    total_unique_prompts = len(system_prompts)
    total_requests_with_system = sum(sp["count"] for sp in system_prompts.values())

    # Sort prompts by count descending, then by last_seen descending
    sorted_prompts = sorted(
        system_prompts.items(),
        key=lambda x: (x[1]["count"], x[1]["last_seen"]),
        reverse=True
    )

    # Apply pagination
    total_pages = (total_unique_prompts + per_page - 1) // per_page
    paginated_prompts = sorted_prompts[offset:offset + per_page]

    # Get proxy key names for display
    proxy_result = await db.execute(select(ProxyKey.id, ProxyKey.name))
    proxy_names = {pk.id: pk.name for pk in proxy_result.all()}

    # Get unique apps for filter dropdown
    apps_result = await db.execute(select(ProxyKey.id, ProxyKey.name))
    apps = list(apps_result.all())

    # Get unique models for filter dropdown
    models_result = await db.execute(select(RequestLog.model).distinct())
    models = [m[0] for m in models_result.all() if m[0]]

    app_options = "".join([
        f'<option value="{app.id}" {"selected" if app_id == app.id else ""}>{app.name}</option>'
        for app in apps
    ])
    model_options = "".join([
        f'<option value="{m}" {"selected" if model == m else ""}>{m}</option>'
        for m in models
    ])

    # Build system prompts table rows
    def _prompt_row(prompt_hash, info, idx):
        preview = info["content"][:100].replace("\n", " ")
        preview = preview[:100] + "..." if len(info["content"]) > 100 else preview
        preview_escaped = html_lib.escape(preview)
        first_seen = info["first_seen"].strftime("%m-%d %H:%M") if info["first_seen"] else "N/A"
        last_seen = info["last_seen"].strftime("%m-%d %H:%M") if info["last_seen"] else "N/A"

        # Calculate days ago for last seen
        days_ago = ""
        if info["last_seen"]:
            delta = now - info["last_seen"]
            if delta.days == 0:
                days_ago = "Today"
            elif delta.days == 1:
                days_ago = "Yesterday"
            else:
                days_ago = f"{delta.days} days ago"

        return (
            f'<tr class="hover:bg-gray-50 cursor-pointer" onclick="window.location.href=\'/system-prompts/{prompt_hash}\'">'
            f'<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500 w-10">'
            f'<input type="checkbox" name="selected_prompts" value="{prompt_hash}" class="rounded border-gray-300" onclick="event.stopPropagation()">'
            f'</td>'
            f'<td class="px-6 py-4">'
            f'<div class="text-sm text-gray-900 line-clamp-2">{preview_escaped}</div>'
            f'<div class="text-xs text-gray-500 mt-1 font-mono">{prompt_hash[:8]}...</div>'
            f'</td>'
            f'<td class="px-6 py-4 whitespace-nowrap text-sm font-semibold text-blue-600">{info["count"]}</td>'
            f'<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{first_seen}</td>'
            f'<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">'
            f'<div>{last_seen}</div><div class="text-xs text-gray-400">{days_ago}</div>'
            f'</td>'
            f'<td class="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">'
            f'<a href="/system-prompts/{prompt_hash}" class="text-blue-600 hover:text-blue-900"><i class="fas fa-eye"></i> View</a>'
            f'</td></tr>'
        )

    prompt_rows = "".join(_prompt_row(h, info, i) for i, (h, info) in enumerate(paginated_prompts))
    empty_msg = '<tr><td colspan="6" class="px-6 py-4 text-center text-gray-500">No system prompts found</td></tr>' if not prompt_rows else ""

    # Pagination URLs
    prev_q = "&".join([
        f"app_id={app_id}" if app_id else "",
        f"model={model}" if model else "",
        f"status={status}" if status else "",
        f"cron_task={cron_task}" if cron_task else "",
        f"days={days}" if days else "",
        f"limit={limit}" if limit else "",
    ])
    prev_q = "&" + prev_q.strip("&") if prev_q.strip() else ""

    prev_url = f"/system-prompts?page={max(1, page - 1)}{prev_q}"
    next_url = f"/system-prompts?page={min(total_pages, page + 1)}{prev_q}"
    prev_cls = "opacity-50 cursor-not-allowed" if page == 1 else "hover:bg-gray-50"
    next_cls = "opacity-50 cursor-not-allowed" if page == total_pages else "hover:bg-gray-50"

    pagination_html = (
        f'<div class="flex justify-center mt-6"><nav class="flex gap-2">'
        f'<a href="{prev_url}" class="px-4 py-2 bg-white border border-gray-300 rounded-lg {prev_cls}"><i class="fas fa-chevron-left"></i> Previous</a>'
        f'<span class="px-4 py-2 bg-blue-600 text-white rounded-lg">Page {page} of {total_pages}</span>'
        f'<a href="{next_url}" class="px-4 py-2 bg-white border border-gray-300 rounded-lg {next_cls}">Next <i class="fas fa-chevron-right"></i></a>'
        f'</nav></div>'
    ) if total_pages > 1 else ""

    main_content = f"""
            <div class="flex justify-between items-center mb-6">
                <div>
                    <h1 class="text-2xl font-bold text-gray-900">
                        <i class="fas fa-file-code text-purple-500 mr-2"></i>System Prompts Analysis
                    </h1>
                    <p class="text-sm text-gray-500 mt-1">
                        Analyze and compare system prompts across your requests
                    </p>
                </div>
                <a href="/deep-analytics" class="text-sm text-purple-600 hover:text-purple-800">
                    <i class="fas fa-flask mr-1"></i>Deep Analytics
                </a>
            </div>

            <!-- Summary Stats -->
            <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-xs text-gray-500">Unique Prompts</div>
                    <div class="text-xl font-bold text-gray-900">{total_unique_prompts}</div>
                </div>
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-xs text-gray-500">Total Requests</div>
                    <div class="text-xl font-bold text-gray-900">{total_requests_with_system:,}</div>
                </div>
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-xs text-gray-500">Avg Requests/Prompt</div>
                    <div class="text-xl font-bold text-gray-900">{total_requests_with_system / max(1, total_unique_prompts):.1f}</div>
                </div>
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-xs text-gray-500">Time Range</div>
                    <div class="text-xl font-bold text-gray-900">{days if days > 0 else 'All'} days</div>
                </div>
            </div>

            <!-- Filters -->
            <div class="bg-white rounded-lg shadow p-4 mb-6">
                <form method="GET" action="/system-prompts" class="flex flex-wrap gap-4">
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">Application</label>
                        <select name="app_id" class="px-3 py-2 border border-gray-300 rounded-md text-sm">
                            <option value="">All Applications</option>
                            {app_options}
                        </select>
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">Model</label>
                        <select name="model" class="px-3 py-2 border border-gray-300 rounded-md text-sm">
                            <option value="">All Models</option>
                            {model_options}
                        </select>
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">Status</label>
                        <select name="status" class="px-3 py-2 border border-gray-300 rounded-md text-sm">
                            <option value="">All Status</option>
                            <option value="200" {"selected" if status == "200" else ""}>200 OK</option>
                            <option value="400" {"selected" if status == "400" else ""}>400 Bad Request</option>
                            <option value="401" {"selected" if status == "401" else ""}>401 Unauthorized</option>
                            <option value="429" {"selected" if status == "429" else ""}>429 Too Many Requests</option>
                            <option value="500" {"selected" if status == "500" else ""}>500 Server Error</option>
                        </select>
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">Cron Task</label>
                        <input type="text" name="cron_task" value="{cron_task or ''}" placeholder="Task ID or name"
                               class="px-3 py-2 border border-gray-300 rounded-md text-sm">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">Time Range</label>
                        <select name="days" class="px-3 py-2 border border-gray-300 rounded-md text-sm">
                            <option value="1" {"selected" if days == 1 else ""}>Last 24 hours</option>
                            <option value="3" {"selected" if days == 3 else ""}>Last 3 days</option>
                            <option value="7" {"selected" if days == 7 else ""}>Last 7 days</option>
                            <option value="30" {"selected" if days == 30 else ""}>Last 30 days</option>
                            <option value="90" {"selected" if days == 90 else ""}>Last 90 days</option>
                            <option value="0" {"selected" if days == 0 else ""}>All time</option>
                        </select>
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-1">Limit</label>
                        <select name="limit" class="px-3 py-2 border border-gray-300 rounded-md text-sm">
                            <option value="100" {"selected" if limit == 100 else ""}>100 requests</option>
                            <option value="500" {"selected" if limit == 500 else ""}>500 requests</option>
                            <option value="1000" {"selected" if limit == 1000 else ""}>1000 requests</option>
                            <option value="5000" {"selected" if limit == 5000 else ""}>5000 requests</option>
                        </select>
                    </div>
                    <div class="flex items-end gap-2">
                        <button type="submit" class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700">
                            <i class="fas fa-filter mr-2"></i>Filter
                        </button>
                        <a href="/system-prompts" class="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300">
                            <i class="fas fa-times"></i>
                        </a>
                    </div>
                </form>
            </div>

            <!-- Compare Selected Bar (hidden by default, shown when items selected) -->
            <div id="compare-bar" class="fixed bottom-0 left-0 right-0 bg-blue-600 text-white p-4 shadow-lg transform translate-y-full transition-transform duration-200 z-40">
                <div class="max-w-7xl mx-auto flex justify-between items-center">
                    <span class="text-sm"><span id="selected-count">0</span> prompts selected</span>
                    <div class="flex gap-2">
                        <button onclick="clearSelection()" class="px-4 py-2 bg-blue-700 rounded-lg hover:bg-blue-800 text-sm">
                            <i class="fas fa-times mr-1"></i>Clear
                        </button>
                        <button onclick="compareSelected()" class="px-4 py-2 bg-white text-blue-600 rounded-lg hover:bg-gray-100 text-sm font-semibold">
                            <i class="fas fa-columns mr-1"></i>Compare Selected
                        </button>
                    </div>
                </div>
            </div>

            <!-- System Prompts Table -->
            <div class="bg-white rounded-lg shadow">
                <table class="min-w-full divide-y divide-gray-200">
                    <thead class="bg-gray-50">
                        <tr>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase w-10">
                                <input type="checkbox" id="select-all" class="rounded border-gray-300" onclick="toggleSelectAll(this)">
                            </th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">System Prompt</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Count</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">First Seen</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Last Seen</th>
                            <th class="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">Actions</th>
                        </tr>
                    </thead>
                    <tbody class="bg-white divide-y divide-gray-200">
                        {prompt_rows if prompt_rows else empty_msg}
                    </tbody>
                </table>
            </div>

            <!-- Pagination -->
            {pagination_html}
    """

    breadcrumbs = render_breadcrumbs([
        ("Dashboard", "/dashboard"),
        ("System Prompts", None),
    ])
    sidebar = render_sidebar("system-prompts")

    extra_head = """<style>
        .line-clamp-2 {
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }
    </style>"""

    extra_footer_script = """<script>
        let selectedCount = 0;

        function toggleSelectAll(checkbox) {
            const checkboxes = document.querySelectorAll('input[name="selected_prompts"]');
            checkboxes.forEach(cb => cb.checked = checkbox.checked);
            updateSelectedCount();
        }

        function updateSelectedCount() {
            const checkboxes = document.querySelectorAll('input[name="selected_prompts"]:checked');
            selectedCount = checkboxes.length;
            const bar = document.getElementById('compare-bar');
            document.getElementById('selected-count').textContent = selectedCount;
            if (selectedCount > 0) {
                bar.classList.remove('translate-y-full');
            } else {
                bar.classList.add('translate-y-full');
            }
        }

        function clearSelection() {
            const checkboxes = document.querySelectorAll('input[name="selected_prompts"]');
            checkboxes.forEach(cb => cb.checked = false);
            document.getElementById('select-all').checked = false;
            updateSelectedCount();
        }

        function compareSelected() {
            const checkboxes = document.querySelectorAll('input[name="selected_prompts"]:checked');
            if (checkboxes.length < 2) {
                alert('Please select at least 2 prompts to compare');
                return;
            }
            const promptHashes = Array.from(checkboxes).map(cb => cb.value);
            window.location.href = '/system-prompts/compare?prompts=' + promptHashes.join(',');
        }

        // Attach change listeners to all checkboxes
        document.addEventListener('DOMContentLoaded', function() {
            const checkboxes = document.querySelectorAll('input[name="selected_prompts"]');
            checkboxes.forEach(cb => cb.addEventListener('change', updateSelectedCount));
        });
    </script>"""

    html = render_page(
        "System Prompts Analysis",
        sidebar,
        breadcrumbs,
        main_content,
        extra_head=extra_head,
        extra_footer_script=extra_footer_script,
    )
    return html


# =============================================================================
# System Prompts Compare Route (must be before detail route)
# =============================================================================
@router.get("/system-prompts/compare", response_class=HTMLResponse)
async def compare_system_prompts(
    request: Request,
    db: DbSession,
    prompts: str,  # Comma-separated prompt hashes
    app_id: Optional[str] = None,
    model: Optional[str] = None,
    days: int = None,
):
    """Compare multiple system prompts side by side."""
    import html as html_lib
    import json

    # Use config default if not provided
    if days is None:
        days = settings.default_days

    prompt_hashes = [h.strip() for h in prompts.split(",") if h.strip()]

    if len(prompt_hashes) < 2:
        raise HTTPException(status_code=400, detail="At least 2 prompts required for comparison")

    # Build base query with filters
    query = select(RequestLog).order_by(RequestLog.created_at.desc())

    if app_id:
        query = query.where(RequestLog.proxy_key_id == app_id)
    if model:
        query = query.where(RequestLog.model == model)

    # Time range filter
    now = datetime.now()
    if days > 0:
        cutoff = now - timedelta(days=days)
        query = query.where(RequestLog.created_at >= cutoff)

    result = await db.execute(query)
    all_requests = list(result.scalars().all())

    # Extract system prompts
    system_prompts = extract_system_prompts(all_requests)

    # Get requested prompts
    compare_prompts = []
    for hash_val in prompt_hashes:
        if hash_val in system_prompts:
            info = system_prompts[hash_val]
            compare_prompts.append({
                "hash": hash_val,
                "content": info["content"],
                "count": info["count"],
                "first_seen": info["first_seen"],
                "last_seen": info["last_seen"],
                "daily_counts": info["daily_counts"],
                "model_counts": info["model_counts"],
            })

    if len(compare_prompts) < 2:
        raise HTTPException(status_code=404, detail="Not enough prompts found for comparison")

    # Get all dates across all prompts
    all_dates = set()
    for prompt in compare_prompts:
        all_dates.update(prompt["daily_counts"].keys())
    sorted_dates = sorted(all_dates)

    # Build comparison data for chart
    chart_datasets = []
    colors = [
        {"bg": "rgba(59, 130, 246, 0.5)", "border": "rgb(59, 130, 246)"},
        {"bg": "rgba(34, 197, 94, 0.5)", "border": "rgb(34, 197, 94)"},
        {"bg": "rgba(251, 146, 60, 0.5)", "border": "rgb(251, 146, 60)"},
        {"bg": "rgba(168, 85, 247, 0.5)", "border": "rgb(168, 85, 247)"},
    ]

    for i, prompt in enumerate(compare_prompts):
        color = colors[i % len(colors)]
        chart_datasets.append({
            "label": f"Prompt {i + 1} ({prompt['hash'][:8]})",
            "data": [prompt["daily_counts"].get(d, 0) for d in sorted_dates],
            "backgroundColor": color["bg"],
            "borderColor": color["border"],
            "borderWidth": 2,
            "fill": False,
            "tension": 0.4,
        })

    # Build model comparison
    all_models = set()
    for prompt in compare_prompts:
        all_models.update(prompt["model_counts"].keys())

    model_comparison_html = ""
    for model in sorted(all_models):
        model_comparison_html += f'<div class="flex items-center justify-between py-2 border-b border-gray-100"><span class="text-sm text-gray-700">{model}</span>'
        for prompt in compare_prompts:
            count = prompt["model_counts"].get(model, 0)
            pct = (count / prompt["count"] * 100) if prompt["count"] > 0 else 0
            model_comparison_html += f'<span class="text-sm text-gray-500 w-24 text-right">{count} ({pct:.0f}%)</span>'
        model_comparison_html += '</div>'

    # Escape content for display
    for prompt in compare_prompts:
        prompt["content_escaped"] = html_lib.escape(prompt["content"])
        prompt["first_seen_str"] = prompt["first_seen"].strftime("%Y-%m-%d %H:%M")
        prompt["last_seen_str"] = prompt["last_seen"].strftime("%Y-%m-%d %H:%M")
        delta = now - prompt["last_seen"]
        prompt["days_ago"] = f"{delta.days} days ago"

    # Generate diff for first two prompts (for side-by-side comparison)
    import difflib
    diff_html = ""
    if len(compare_prompts) >= 2:
        text1 = compare_prompts[0]["content"]
        text2 = compare_prompts[1]["content"]

        # Split into lines for diff
        lines1 = text1.splitlines(keepends=True)
        lines2 = text2.splitlines(keepends=True)

        # Generate unified diff
        diff = difflib.unified_diff(lines1, lines2, lineterm='', n=10)
        diff_lines = list(diff)[2:]  # Skip header lines

        # Build colored diff HTML
        diff_output = []
        for line in diff_lines:
            if line.startswith('+') and not line.startswith('+++'):
                diff_output.append(f'<div class="bg-green-100 border-l-4 border-green-500 pl-2 py-0.5"><span class="text-green-800"><ins>{html_lib.escape(line)}</ins></span></div>')
            elif line.startswith('-') and not line.startswith('---'):
                diff_output.append(f'<div class="bg-red-100 border-l-4 border-red-500 pl-2 py-0.5"><span class="text-red-800"><del>{html_lib.escape(line)}</del></span></div>')
            else:
                diff_output.append(f'<div class="text-gray-500 pl-2 py-0.5">{html_lib.escape(line)}</div>')

        diff_html = ''.join(diff_output) if diff_output else '<p class="text-gray-500 text-center py-4">No differences found</p>'

    main_content = f"""
            <!-- Back Link -->
            <div class="mb-4">
                <a href="/system-prompts" class="text-sm text-blue-600 hover:text-blue-800">
                    <i class="fas fa-arrow-left mr-1"></i>Back to System Prompts
                </a>
            </div>

            <!-- Header -->
            <div class="bg-white rounded-lg shadow p-6 mb-6">
                <h1 class="text-2xl font-bold text-gray-900">
                    <i class="fas fa-columns text-purple-500 mr-2"></i>Compare System Prompts
                </h1>
                <p class="text-sm text-gray-500 mt-1">Comparing {len(compare_prompts)} prompts</p>
            </div>

            <!-- Prompt Cards -->
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
    """

    for i, prompt in enumerate(compare_prompts):
        main_content += f"""
                <div class="bg-white rounded-lg shadow p-4 border-2 border-purple-200">
                    <div class="flex justify-between items-start mb-2">
                        <h3 class="text-lg font-semibold text-gray-800">Prompt {i + 1}</h3>
                        <span class="px-2 py-1 bg-purple-100 text-purple-700 rounded text-xs font-mono">{prompt['hash'][:8]}</span>
                    </div>
                    <div class="space-y-2 mb-3">
                        <div class="flex justify-between text-sm">
                            <span class="text-gray-500">Occurrences</span>
                            <span class="font-semibold text-blue-600">{prompt['count']}</span>
                        </div>
                        <div class="flex justify-between text-sm">
                            <span class="text-gray-500">First Seen</span>
                            <span class="text-gray-900">{prompt['first_seen_str']}</span>
                        </div>
                        <div class="flex justify-between text-sm">
                            <span class="text-gray-500">Last Seen</span>
                            <span class="text-gray-900">{prompt['last_seen_str']} ({prompt['days_ago']})</span>
                        </div>
                    </div>
                    <div class="bg-gray-50 rounded p-3 border border-gray-200">
                        <pre class="text-xs text-gray-700 whitespace-pre-wrap overflow-x-auto" style="max-height: 200px; overflow-y: auto;">{prompt['content_escaped'][:500]}{'...' if len(prompt['content']) > 500 else ''}</pre>
                    </div>
                </div>
        """

    main_content += f"""
            </div>

            <!-- Usage Comparison Chart -->
            <div class="bg-white rounded-lg shadow p-6 mb-6">
                <h3 class="text-lg font-semibold text-gray-800 mb-4">
                    <i class="fas fa-chart-line text-blue-500 mr-2"></i>Daily Usage Comparison
                </h3>
                <div class="h-80" style="position:relative;">
                    <canvas id="compareChart"></canvas>
                </div>
            </div>

            <!-- Model Distribution Comparison -->
            <div class="bg-white rounded-lg shadow p-6 mb-6">
                <h3 class="text-lg font-semibold text-gray-800 mb-4">
                    <i class="fas fa-chart-pie text-green-500 mr-2"></i>Model Distribution Comparison
                </h3>
                <div class="overflow-x-auto">
                    <table class="min-w-full">
                        <thead class="bg-gray-50">
                            <tr>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Model</th>
    """

    for i, prompt in enumerate(compare_prompts):
        main_content += f'<th class="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">Prompt {i + 1}</th>'

    main_content += f"""
                            </tr>
                        </thead>
                        <tbody class="bg-white divide-y divide-gray-200">
    """ + model_comparison_html + f"""
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Prompt Content Diff -->
            <div class="bg-white rounded-lg shadow p-6 mb-6">
                <h3 class="text-lg font-semibold text-gray-800 mb-4">
                    <i class="fas fa-code-diff text-orange-500 mr-2"></i>Prompt Content Diff
                </h3>
                <div class="bg-gray-50 rounded-lg border border-gray-200 p-4 max-h-96 overflow-y-auto">
                    {diff_html}
                </div>
                <div class="mt-3 flex gap-4 text-xs">
                    <div class="flex items-center gap-1">
                        <span class="w-3 h-3 bg-green-100 border-l-4 border-green-500"></span>
                        <span class="text-gray-600">Added (Prompt 2)</span>
                    </div>
                    <div class="flex items-center gap-1">
                        <span class="w-3 h-3 bg-red-100 border-l-4 border-red-500"></span>
                        <span class="text-gray-600">Removed (from Prompt 1)</span>
                    </div>
                    <div class="flex items-center gap-1">
                        <span class="w-3 h-3 bg-gray-50"></span>
                        <span class="text-gray-600">Unchanged</span>
                    </div>
                </div>
            </div>
    """

    # Chart configuration
    compare_config = {
        "type": "line",
        "data": {
            "labels": sorted_dates,
            "datasets": chart_datasets,
        },
        "options": {
            "responsive": True,
            "maintainAspectRatio": False,
            "plugins": {"legend": {"position": "top"}},
            "scales": {"x": {"grid": {"display": False}}, "y": {"beginAtZero": True, "ticks": {"stepSize": 1}}},
        },
    }

    chart_head = '<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>'
    chart_footer = f"""
        <script>
            window._compareChartConfig = {json.dumps(compare_config).replace("</", "<\\/")};
            function initCompareChart() {{
                if (typeof Chart === "undefined") {{ window.setTimeout(initCompareChart, 80); return; }}
                var el = document.getElementById("compareChart");
                if (el && window._compareChartConfig) {{
                    try {{ new Chart(el.getContext("2d"), window._compareChartConfig); }} catch(e) {{ console.error("Compare chart:", e); }}
                    window._compareChartConfig = null;
                }}
            }}
            window.addEventListener("load", initCompareChart);
        </script>
    """

    breadcrumbs = render_breadcrumbs([
        ("Dashboard", "/dashboard"),
        ("System Prompts", "/system-prompts"),
        ("Compare", None),
    ])
    sidebar = render_sidebar("system-prompts")

    html = render_page(
        "Compare System Prompts",
        sidebar,
        breadcrumbs,
        main_content,
        extra_head=chart_head,
        extra_footer_script=chart_footer,
    )
    return html


@router.get("/system-prompts/{prompt_hash}", response_class=HTMLResponse)
async def view_system_prompt_detail(
    prompt_hash: str,
    request: Request,
    db: DbSession,
    app_id: Optional[str] = None,
    model: Optional[str] = None,
    days: int = None,
    limit: int = None,
):
    """View detailed information about a specific system prompt."""
    import html as html_lib
    import json

    # Use config defaults if not provided
    if days is None:
        days = settings.default_days
    if limit is None:
        limit = settings.default_limit

    # Build base query with filters
    query = select(RequestLog).order_by(RequestLog.created_at.desc())

    if app_id:
        query = query.where(RequestLog.proxy_key_id == app_id)
    if model:
        query = query.where(RequestLog.model == model)

    # Time range filter
    now = datetime.now()
    if days > 0:
        cutoff = now - timedelta(days=days)
        query = query.where(RequestLog.created_at >= cutoff)

    result = await db.execute(query)
    all_requests = list(result.scalars().all())

    # Extract system prompts and find the requested one
    system_prompts = extract_system_prompts(all_requests)

    if prompt_hash not in system_prompts:
        raise HTTPException(status_code=404, detail="System prompt not found")

    prompt_info = system_prompts[prompt_hash]

    # Get proxy key names
    proxy_result = await db.execute(select(ProxyKey.id, ProxyKey.name))
    proxy_names = {pk.id: pk.name for pk in proxy_result.all()}

    # Build daily distribution for chart
    sorted_dates = sorted(prompt_info["daily_counts"].keys())
    daily_data = [prompt_info["daily_counts"].get(d, 0) for d in sorted_dates]

    # Build model distribution
    model_dist = sorted(prompt_info["model_counts"].items(), key=lambda x: -x[1])

    # Get recent requests for this prompt
    recent_requests = prompt_info["requests"][:20]

    # Escape prompt content for display
    prompt_content_escaped = html_lib.escape(prompt_info["content"])

    # Build request rows
    request_rows = "".join(render_request_table_row(req, proxy_names=proxy_names, style="system-prompt") for req in recent_requests)
    empty_msg = '<tr><td colspan="9" class="px-4 py-4 text-center text-gray-500">No requests found</td></tr>' if not request_rows else ""

    # Model distribution HTML
    model_dist_html = "".join([
        f'<div class="flex items-center justify-between py-2 border-b border-gray-100">'
        f'<span class="text-sm text-gray-700">{model}</span>'
        f'<span class="text-sm font-semibold text-gray-900">{count} ({count/prompt_info["count"]*100:.1f}%)</span>'
        f'</div>'
        for model, count in model_dist
    ])

    main_content = f"""
            <!-- Back Link -->
            <div class="mb-4">
                <a href="/system-prompts" class="text-sm text-blue-600 hover:text-blue-800">
                    <i class="fas fa-arrow-left mr-1"></i>Back to System Prompts
                </a>
            </div>

            <!-- Prompt Content Card -->
            <div class="bg-white rounded-lg shadow p-6 mb-6">
                <div class="flex justify-between items-start mb-4">
                    <h1 class="text-2xl font-bold text-gray-900">
                        <i class="fas fa-file-code text-purple-500 mr-2"></i>System Prompt Details
                    </h1>
                    <span class="px-3 py-1 bg-purple-100 text-purple-700 rounded-full text-xs font-mono">
                        {prompt_hash[:12]}
                    </span>
                </div>

                <div class="bg-gray-50 rounded-lg p-4 border border-gray-200">
                    <pre class="whitespace-pre-wrap text-sm text-gray-700 overflow-x-auto">{prompt_content_escaped}</pre>
                </div>

                <div class="flex gap-6 mt-4 text-sm text-gray-500">
                    <span><i class="fas fa-signal text-blue-500 mr-1"></i>Length: {len(prompt_info["content"])} characters</span>
                    <span><i class="fas fa-clock text-green-500 mr-1"></i>First seen: {prompt_info["first_seen"].strftime("%Y-%m-%d %H:%M:%S")}</span>
                    <span><i class="fas fa-calendar text-yellow-500 mr-1"></i>Last seen: {prompt_info["last_seen"].strftime("%Y-%m-%d %H:%M:%S")}</span>
                </div>
            </div>

            <!-- Statistics Grid -->
            <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-xs text-gray-500">Total Occurrences</div>
                    <div class="text-2xl font-bold text-blue-600">{prompt_info["count"]}</div>
                </div>
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-xs text-gray-500">Days Active</div>
                    <div class="text-2xl font-bold text-gray-900">{len(prompt_info["daily_counts"])}</div>
                </div>
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-xs text-gray-500">Models Used</div>
                    <div class="text-2xl font-bold text-gray-900">{len(prompt_info["model_counts"])}</div>
                </div>
                <div class="bg-white rounded-lg shadow p-4">
                    <div class="text-xs text-gray-500">Avg Per Day</div>
                    <div class="text-2xl font-bold text-gray-900">{prompt_info["count"] / max(1, len(prompt_info["daily_counts"])):.1f}</div>
                </div>
            </div>

            <!-- Charts Grid -->
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
                <!-- Time Distribution Chart -->
                <div class="bg-white rounded-lg shadow p-6">
                    <h3 class="text-lg font-semibold text-gray-800 mb-4">
                        <i class="fas fa-chart-bar text-blue-500 mr-2"></i>Daily Usage
                    </h3>
                    <div class="h-64" style="position:relative;">
                        <canvas id="dailyChart"></canvas>
                    </div>
                </div>

                <!-- Model Distribution -->
                <div class="bg-white rounded-lg shadow p-6">
                    <h3 class="text-lg font-semibold text-gray-800 mb-4">
                        <i class="fas fa-chart-pie text-green-500 mr-2"></i>Model Distribution
                    </h3>
                    <div class="space-y-2">
                        {model_dist_html}
                    </div>
                </div>
            </div>

            <!-- Recent Requests -->
            <div class="bg-white rounded-lg shadow mb-6">
                <div class="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
                    <h3 class="text-lg font-semibold text-gray-800">
                        <i class="fas fa-history text-gray-500 mr-2"></i>Recent Requests
                    </h3>
                    <span class="text-sm text-gray-500">Showing {len(recent_requests)} of {prompt_info["count"]} requests</span>
                </div>
                <div class="overflow-x-auto">
                    <table class="min-w-full divide-y divide-gray-200">
                        <thead class="bg-gray-50">
                            <tr>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Time</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Application</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Model</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Tokens</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Latency</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Cache Read</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Cron Task</th>
                                <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Actions</th>
                            </tr>
                        </thead>
                        <tbody class="bg-white divide-y divide-gray-200">
                            {request_rows if request_rows else empty_msg}
                        </tbody>
                    </table>
                </div>
            </div>
    """

    # Chart configuration
    daily_config = {
        "type": "bar",
        "data": {
            "labels": sorted_dates,
            "datasets": [{"label": "Requests", "data": daily_data, "backgroundColor": "rgba(59, 130, 246, 0.5)", "borderColor": "rgb(59, 130, 246)", "borderWidth": 1}],
        },
        "options": {
            "responsive": True,
            "maintainAspectRatio": False,
            "plugins": {"legend": {"display": False}},
            "scales": {"x": {"grid": {"display": False}}, "y": {"beginAtZero": True, "ticks": {"stepSize": 1}}},
        },
    }

    chart_head = '<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>'
    chart_footer = f"""
        <script>
            window._dailyChartConfig = {json.dumps(daily_config).replace("</", "<\\/")};
            function initDailyChart() {{
                if (typeof Chart === "undefined") {{ window.setTimeout(initDailyChart, 80); return; }}
                var el = document.getElementById("dailyChart");
                if (el && window._dailyChartConfig) {{
                    try {{ new Chart(el.getContext("2d"), window._dailyChartConfig); }} catch(e) {{ console.error("Daily chart:", e); }}
                    window._dailyChartConfig = null;
                }}
            }}
            window.addEventListener("load", initDailyChart);
        </script>
    """

    breadcrumbs = render_breadcrumbs([
        ("Dashboard", "/dashboard"),
        ("System Prompts", "/system-prompts"),
        (f"Prompt {prompt_hash[:8]}...", None),
    ])
    sidebar = render_sidebar("system-prompts")

    html = render_page(
        f"System Prompt: {prompt_hash[:12]}",
        sidebar,
        breadcrumbs,
        main_content,
        extra_head=chart_head,
        extra_footer_script=chart_footer,
    )
    return html
