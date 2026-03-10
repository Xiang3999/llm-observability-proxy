"""Web Dashboard routes."""

from typing import Annotated, Optional
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

    def _recent_req_row(req):
        status_cls = "bg-green-100 text-green-800" if (req.status_code and req.status_code < 400) else "bg-red-100 text-red-800"
        return (
            f'<tr><td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{req.created_at.strftime("%Y-%m-%d %H:%M:%S")}</td>'
            f'<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{proxy_names.get(req.proxy_key_id, "Unknown")}</td>'
            f'<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{req.model or "-"}</td>'
            f'<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{req.total_tokens or "-"}</td>'
            f'<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{req.total_latency_ms or "-"}ms</td>'
            f'<td class="px-6 py-4 whitespace-nowrap"><span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full {status_cls}">{req.status_code or "N/A"}</span></td>'
            f'<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">${float(req.cost_usd or 0):.4f}</td>'
            f'<td class="px-6 py-4 whitespace-nowrap text-right text-sm font-medium"><a href="/requests/{req.id}" class="text-blue-600 hover:text-blue-900"><i class="fas fa-eye"></i> View</a></td></tr>'
        )
    recent_requests_rows = "".join(_recent_req_row(req) for req in recent_requests)
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
                            <th class="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">Actions</th>
                        </tr>
                    </thead>
                    <tbody class="bg-white divide-y divide-gray-200">
                        {recent_requests_rows if recent_requests_rows else '<tr><td colspan="8" class="px-6 py-4 text-center text-gray-500">No requests yet</td></tr>'}
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
    status: Optional[str] = None
):
    """List all requests with pagination and filters."""
    from sqlalchemy import select, func

    per_page = 50
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

    def _req_row(req):
        status_cls = "bg-green-100 text-green-800" if (req.status_code and req.status_code < 400) else "bg-red-100 text-red-800"
        return (
            f'<tr><td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{req.created_at.strftime("%Y-%m-%d %H:%M:%S")}</td>'
            f'<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{proxy_names.get(req.proxy_key_id, "Unknown")}</td>'
            f'<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{req.model or "-"}</td>'
            f'<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{req.total_tokens or "-"}</td>'
            f'<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{req.total_latency_ms or "-"}ms</td>'
            f'<td class="px-6 py-4 whitespace-nowrap"><span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full {status_cls}">{req.status_code or "N/A"}</span></td>'
            f'<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">${float(req.cost_usd or 0):.4f}</td>'
            f'<td class="px-6 py-4 whitespace-nowrap text-right text-sm font-medium"><a href="/requests/{req.id}" class="text-blue-600 hover:text-blue-900"><i class="fas fa-eye"></i> View</a></td></tr>'
        )
    request_rows = "".join(_req_row(req) for req in requests_list)
    empty_req_msg = '<tr><td colspan="8" class="px-6 py-4 text-center text-gray-500">No requests found</td></tr>' if not requests_list else ""

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
    days: int = 7,
    limit: int = 100
):
    """View detailed application analytics with prompt analysis and full request history."""
    from sqlalchemy import select, func
    import json
    from datetime import timedelta

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

    requests_result = await db.execute(
        select(RequestLog)
        .where(RequestLog.proxy_key_id == app_id)
        .where(RequestLog.created_at >= cutoff_date)
        .order_by(RequestLog.created_at.desc())
    )
    all_requests = list(requests_result.scalars().all())

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
    system_prompts = set()
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

            # Extract system prompts
            if role == "system" and msg.get("content"):
                content = msg.get("content", "")
                if isinstance(content, str):
                    system_prompts.add(content[:200])  # First 200 chars

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

    system_prompts_html = "".join([
        f'<div class="text-xs bg-gray-50 p-2 rounded border border-gray-200 truncate" title="{sp}"><i class="fas fa-quote-left text-gray-400 mr-1"></i>{sp[:100]}...</div>'
        for sp in list(system_prompts)[:5]
    ])
    system_prompts_msg = '<p class="text-sm text-gray-500">No system prompts found</p>' if not system_prompts else ""
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

    def _analytics_req_row(req):
        status_cls = "bg-green-100 text-green-800" if (req.status_code and req.status_code < 400) else "bg-red-100 text-red-800"
        n_msg = len(req.request_body.get("messages", [])) if req.request_body else 0
        return (
            f'<tr class="hover:bg-gray-50"><td class="px-4 py-3 whitespace-nowrap text-xs text-gray-500">{req.created_at.strftime("%m-%d %H:%M")}</td>'
            f'<td class="px-4 py-3 whitespace-nowrap text-xs text-gray-900">{req.model or "-"}</td>'
            f'<td class="px-4 py-3 whitespace-nowrap text-xs text-gray-500">{n_msg}</td>'
            f'<td class="px-4 py-3 whitespace-nowrap text-xs text-gray-500">{req.total_tokens or "-"}</td>'
            f'<td class="px-4 py-3 whitespace-nowrap text-xs text-gray-500">{req.total_latency_ms or "-"}ms</td>'
            f'<td class="px-4 py-3 whitespace-nowrap text-xs"><span class="px-2 py-1 rounded-full text-xs font-semibold {status_cls}">{req.status_code or "N/A"}</span></td>'
            f'<td class="px-4 py-3 whitespace-nowrap text-right text-xs font-medium"><a href="/requests/{req.id}?from_app={app_id}" class="text-blue-600 hover:text-blue-900">View</a></td></tr>'
        )
    request_history_rows = "".join(_analytics_req_row(req) for req in all_requests)
    request_history_empty = '<tr><td colspan="7" class="px-4 py-4 text-center text-gray-500">No requests found</td></tr>' if not all_requests else ""

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
                        <h3 class="text-sm font-medium text-gray-700 mb-3">System Prompts ({len(system_prompts)} unique)</h3>
                        <div class="space-y-2 max-h-40 overflow-y-auto">
                            {system_prompts_html if system_prompts_html else system_prompts_msg}
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
                {"label": "Tokens (÷100)", "data": [daily_tokens[d] // 100 for d in sorted_dates], "borderColor": "rgb(34, 197, 94)", "backgroundColor": "rgba(34, 197, 94, 0.1)", "fill": True, "tension": 0.4, "yAxisID": "y1"},
            ],
        },
        "options": {
            "responsive": True,
            "maintainAspectRatio": False,
            "plugins": {"legend": {"display": True, "position": "top"}},
            "scales": {
                "x": {"grid": {"display": False}},
                "y": {"type": "linear", "display": True, "position": "left", "beginAtZero": True, "ticks": {"stepSize": 1}, "title": {"display": True, "text": "Requests"}},
                "y1": {"type": "linear", "display": True, "position": "right", "beginAtZero": True, "grid": {"drawOnChartArea": False}, "title": {"display": True, "text": "Tokens (÷100)"}},
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
