"""Advanced analytics routes for deep LLM API analysis."""

from typing import Annotated
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import json

from src.models.database import get_db
from src.models.request_log import RequestLog
from src.models.proxy_key import ProxyKey
from src.models.provider_key import ProviderKey
from src.web.layout import render_sidebar, render_breadcrumbs, render_app_tabs, render_page

router = APIRouter(tags=["Advanced Analytics"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.get("/applications/{app_id}/deep-analytics", response_class=HTMLResponse)
async def deep_application_analytics(app_id: str, request: Request, db: DbSession):
    """Deep analytics view for analyzing LLM API communication patterns.

    This page provides insights similar to the Claude Code API analysis article:
    - Token breakdown (tools, system, user messages)
    - Cache efficiency (cache_read vs cache_creation)
    - Prompt caching breakpoints
    - System-reminder detection
    - Tool usage patterns
    - Context window analysis
    """
    from sqlalchemy import select

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

    # Get all requests for this application (limit to 200 for performance)
    requests_result = await db.execute(
        select(RequestLog)
        .where(RequestLog.proxy_key_id == app_id)
        .order_by(RequestLog.created_at.desc())
        .limit(200)
    )
    all_requests = list(requests_result.scalars().all())

    # ===== Deep Analysis =====

    # 1. Cache Metrics Analysis
    total_cache_read = sum(r.cache_read_tokens or 0 for r in all_requests)
    total_cache_creation = sum(r.cache_creation_tokens or 0 for r in all_requests)
    total_input_tokens = sum((r.usage_breakdown or {}).get("input_tokens", 0) for r in all_requests)

    cache_hit_rate = (total_cache_read / (total_cache_read + total_cache_creation) * 100) \
        if (total_cache_read + total_cache_creation) > 0 else 0

    # 2. Anthropic Metadata Analysis (cch, cc_version, etc.)
    cch_values = {}
    cc_versions = {}
    cc_entrypoints = {}

    for req in all_requests:
        meta = req.anthropic_metadata or {}
        cch = meta.get("cch", "")
        cc_version = meta.get("cc_version", "")
        cc_entrypoint = meta.get("cc_entrypoint", "")

        if cch:
            cch_values[cch] = cch_values.get(cch, 0) + 1
        if cc_version:
            cc_versions[cc_version] = cc_versions.get(cc_version, 0) + 1
        if cc_entrypoint:
            cc_entrypoints[cc_entrypoint] = cc_entrypoints.get(cc_entrypoint, 0) + 1

    # 3. Token Breakdown Analysis (per-request) - limited to last 30 for performance
    token_breakdown_data = []
    for req in all_requests[:30]:  # Last 30 requests
        request_body = req.request_body or {}
        messages = request_body.get("messages", [])

        # Count tokens by role (approximation based on message structure)
        system_tokens = 0
        user_tokens = 0
        assistant_tokens = 0
        tool_tokens = 0

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            content_len = len(content) if isinstance(content, str) else 0

            # Rough token estimation (4 chars ≈ 1 token)
            estimated = content_len // 4

            if role == "system":
                system_tokens += estimated
            elif role == "user":
                user_tokens += estimated
            elif role == "assistant":
                assistant_tokens += estimated
            elif role == "tool":
                tool_tokens += estimated

        token_breakdown_data.append({
            "id": req.id[:8],
            "system": system_tokens,
            "user": user_tokens,
            "assistant": assistant_tokens,
            "tool": tool_tokens,
            "total": req.total_tokens or 0,
            "cache_read": req.cache_read_tokens or 0,
            "cache_creation": req.cache_creation_tokens or 0,
        })

    # 4. System-reminder Detection
    system_reminder_patterns = ["<system-reminder>", "system-reminder"]
    system_reminder_count = 0
    system_reminder_types = {}

    for req in all_requests:
        request_body = req.request_body or {}
        messages = request_body.get("messages", [])

        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                for pattern in system_reminder_patterns:
                    if pattern.lower() in content.lower():
                        system_reminder_count += 1
                        # Try to identify type
                        if "SKILLS" in content:
                            system_reminder_types["SKILLS"] = system_reminder_types.get("SKILLS", 0) + 1
                        if "CLAUDE.md" in content:
                            system_reminder_types["CLAUDE.md"] = system_reminder_types.get("CLAUDE.md", 0) + 1
                        if "TodoWrite" in content:
                            system_reminder_types["Tool Reminder"] = system_reminder_types.get("Tool Reminder", 0) + 1
                        if "modified" in content.lower():
                            system_reminder_types["File Change"] = system_reminder_types.get("File Change", 0) + 1

    # 5. Tool Usage Analysis
    tool_calls_by_name = {}
    total_tool_calls = 0

    for req in all_requests:
        # From request body
        request_body = req.request_body or {}
        tools = request_body.get("tools", [])
        for tool in tools:
            if isinstance(tool, dict):
                tool_name = tool.get("name", "")
                if tool_name:
                    # Count tool definitions
                    pass  # We count actual calls, not definitions

        # From response body (actual tool calls)
        response_body = req.response_body or {}
        choices = response_body.get("choices", [])
        for choice in choices:
            message = choice.get("message", {})
            tool_calls = message.get("tool_calls", [])
            if tool_calls:
                for tc in tool_calls:
                    func_info = tc.get("function", {})
                    name = func_info.get("name", "")
                    if name:
                        tool_calls_by_name[name] = tool_calls_by_name.get(name, 0) + 1
                        total_tool_calls += 1

    # 6. Request/Response Headers Analysis
    beta_features = {}
    anthropic_versions = set()

    for req in all_requests:
        req_headers = req.request_headers or {}
        resp_headers = req.response_headers or {}

        # Extract beta features from request headers
        for key in req_headers:
            if "beta" in key.lower() or "anthropic" in key.lower():
                beta_features[key] = beta_features.get(key, 0) + 1

        # Extract anthropic version
        if "anthropic-version" in req_headers:
            anthropic_versions.add(req_headers["anthropic-version"])

    # 7. Calculate "fixed assets" vs "variable" tokens
    # Fixed assets = tools + system prompt (relatively stable)
    # Variable = user messages
    fixed_assets_estimate = 0
    variable_estimate = 0

    if all_requests:
        # Look at first few requests to estimate
        for req in all_requests[:10]:
            request_body = req.request_body or {}
            messages = request_body.get("messages", [])

            for msg in messages:
                role = msg.get("role", "")
                content = msg.get("content", "")
                content_len = len(content) if isinstance(content, str) else 0
                estimated = content_len // 4

                if role == "system":
                    fixed_assets_estimate += estimated
                elif role == "tool":
                    fixed_assets_estimate += estimated
                elif role == "user":
                    variable_estimate += estimated

    # Basic stats
    total_requests = len(all_requests)
    total_tokens = sum(r.total_tokens or 0 for r in all_requests)
    total_cost = sum(float(r.cost_usd or 0) for r in all_requests)

    # Precompute join() HTML to avoid f-string nesting (Python 3.9 compat)
    cch_html = "".join([
        f'<div class="flex justify-between items-center text-xs"><code class="bg-gray-100 px-2 py-1 rounded">{cch}</code><span class="text-gray-600">{count}</span></div>'
        for cch, count in list(cch_values.items())[:10]
    ])
    cc_versions_html = "".join([
        f'<div class="flex justify-between items-center text-xs"><span>{ver}</span><span class="text-gray-600">{count}</span></div>'
        for ver, count in cc_versions.items()
    ])
    cc_entrypoints_html = "".join([
        f'<div class="flex justify-between items-center text-xs"><span>{entry}</span><span class="text-gray-600">{count}</span></div>'
        for entry, count in cc_entrypoints.items()
    ])
    token_breakdown_rows = "".join([
        f'<tr class="border-t"><td class="px-4 py-2 font-mono">{item["id"]}</td><td class="px-4 py-2 text-right">{item["system"]:,}</td><td class="px-4 py-2 text-right">{item["user"]:,}</td><td class="px-4 py-2 text-right">{item["assistant"]:,}</td><td class="px-4 py-2 text-right">{item["tool"]:,}</td><td class="px-4 py-2 text-right">{item["total"]:,}</td><td class="px-4 py-2 text-right text-blue-600">{item["cache_read"]:,}</td><td class="px-4 py-2 text-right text-orange-600">{item["cache_creation"]:,}</td></tr>'
        for item in token_breakdown_data
    ])
    system_reminder_types_html = "".join([
        f'<div class="flex items-center justify-between"><span class="text-sm text-gray-600">{stype}</span><span class="px-2 py-1 bg-yellow-100 text-yellow-800 rounded text-xs">{count}</span></div>'
        for stype, count in system_reminder_types.items()
    ])
    system_reminder_samples_html = "".join([
        f'<div class="text-xs bg-gray-50 p-2 rounded border">{content[:200]}...</div>'
        for content in list(system_reminder_types.keys())[:5]
    ])
    tool_calls_html = "".join([
        f'<div class="flex items-center justify-between"><span class="text-sm text-gray-600">{name}</span><span class="px-2 py-1 bg-blue-100 text-blue-800 rounded text-xs">{count}</span></div>'
        for name, count in sorted(tool_calls_by_name.items(), key=lambda x: -x[1])[:15]
    ])
    beta_features_html = "".join([
        f'<div class="flex justify-between items-center text-xs"><code class="bg-gray-100 px-2 py-1 rounded">{header}</code><span class="text-gray-600">{count}</span></div>'
        for header, count in sorted(beta_features.items(), key=lambda x: -x[1])[:20]
    ])
    anthropic_versions_html = "".join([f'<div class="text-sm text-gray-600">{ver}</div>' for ver in anthropic_versions])

    app_tabs = render_app_tabs(app_id, proxy_key.name, "deep-analytics")
    breadcrumbs = render_breadcrumbs([
        ("Dashboard", "/dashboard"),
        ("Applications", "/dashboard#proxy-keys"),
        (proxy_key.name, f"/applications/{app_id}"),
        ("Deep Analytics", None),
    ])
    main_content = f"""
            <p class="text-sm text-gray-500 mb-6">
                Provider: {provider_key.name} ({provider_key.provider.value}) |
                Total Requests: {total_requests} |
                Total Tokens: {total_tokens:,}
            </p>

            <!-- Cache Efficiency -->
            <div class="bg-white rounded-lg shadow p-6 mb-6">
                <h2 class="text-lg font-semibold text-gray-800 mb-4">
                    <i class="fas fa-database text-blue-500 mr-2"></i>Cache Efficiency Analysis
                </h2>
                <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
                    <div class="bg-blue-50 rounded-lg p-4">
                        <div class="text-sm text-gray-600">Cache Read Tokens</div>
                        <div class="text-2xl font-bold text-blue-600">{total_cache_read:,}</div>
                        <div class="text-xs text-gray-500 mt-1">Saved by cache hits</div>
                    </div>
                    <div class="bg-orange-50 rounded-lg p-4">
                        <div class="text-sm text-gray-600">Cache Creation Tokens</div>
                        <div class="text-2xl font-bold text-orange-600">{total_cache_creation:,}</div>
                        <div class="text-xs text-gray-500 mt-1">Cost for new content</div>
                    </div>
                    <div class="bg-green-50 rounded-lg p-4">
                        <div class="text-sm text-gray-600">Cache Hit Rate</div>
                        <div class="text-2xl font-bold text-green-600">{cache_hit_rate:.1f}%</div>
                        <div class="text-xs text-gray-500 mt-1">Higher is better</div>
                    </div>
                    <div class="bg-purple-50 rounded-lg p-4">
                        <div class="text-sm text-gray-600">Est. Savings</div>
                        <div class="text-2xl font-bold text-purple-600">${(total_cache_read * 0.0000015):.4f}</div>
                        <div class="text-xs text-gray-500 mt-1">vs. no cache</div>
                    </div>
                </div>

                <!-- Cache Trend -->
                <div class="h-64">
                    <canvas id="cacheChart"></canvas>
                </div>
            </div>

            <!-- Anthropic Metadata -->
            <div class="bg-white rounded-lg shadow p-6 mb-6">
                <h2 class="text-lg font-semibold text-gray-800 mb-4">
                    <i class="fas fa-fingerprint text-purple-500 mr-2"></i>Anthropic Metadata Analysis
                </h2>
                <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
                    <div>
                        <h3 class="text-sm font-medium text-gray-700 mb-2">CCH Values (Cache Checksum Hash)</h3>
                        <div class="text-xs text-gray-500 mb-2">Unique values: {len(cch_values)}</div>
                        <div class="space-y-1 max-h-32 overflow-y-auto">
                            {cch_html if cch_html else '<p class="text-xs text-gray-400">No CCH data</p>'}
                        </div>
                        <p class="text-xs text-gray-400 mt-2">
                            <i class="fas fa-info-circle mr-1"></i>
                            Different CCH per request indicates dynamic billing header
                        </p>
                    </div>

                    <div>
                        <h3 class="text-sm font-medium text-gray-700 mb-2">CC Versions</h3>
                        <div class="space-y-1">
                            {cc_versions_html if cc_versions_html else '<p class="text-xs text-gray-400">No version data</p>'}
                        </div>
                    </div>

                    <div>
                        <h3 class="text-sm font-medium text-gray-700 mb-2">CC Entrypoints</h3>
                        <div class="space-y-1">
                            {cc_entrypoints_html if cc_entrypoints_html else '<p class="text-xs text-gray-400">No entrypoint data</p>'}
                        </div>
                    </div>
                </div>
            </div>

            <!-- Token Breakdown -->
            <div class="bg-white rounded-lg shadow p-6 mb-6">
                <h2 class="text-lg font-semibold text-gray-800 mb-4">
                    <i class="fas fa-chart-pie text-green-500 mr-2"></i>Token Breakdown by Role
                </h2>
                <div class="h-64 mb-4">
                    <canvas id="tokenBreakdownChart"></canvas>
                </div>
                <div class="overflow-x-auto">
                    <table class="min-w-full text-sm">
                        <thead class="bg-gray-50">
                            <tr>
                                <th class="px-4 py-2 text-left">Request ID</th>
                                <th class="px-4 py-2 text-right">System</th>
                                <th class="px-4 py-2 text-right">User</th>
                                <th class="px-4 py-2 text-right">Assistant</th>
                                <th class="px-4 py-2 text-right">Tool</th>
                                <th class="px-4 py-2 text-right">Total</th>
                                <th class="px-4 py-2 text-right">Cache Read</th>
                                <th class="px-4 py-2 text-right">Cache Create</th>
                            </tr>
                        </thead>
                        <tbody>
                            {token_breakdown_rows}
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- System-Reminder Detection -->
            <div class="bg-white rounded-lg shadow p-6 mb-6">
                <h2 class="text-lg font-semibold text-gray-800 mb-4">
                    <i class="fas fa-bell text-yellow-500 mr-2"></i>System-Reminder Detection
                </h2>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div>
                        <div class="text-sm text-gray-600 mb-2">Total Detected</div>
                        <div class="text-3xl font-bold text-gray-900">{system_reminder_count}</div>
                        <div class="mt-4">
                            <h4 class="text-sm font-medium text-gray-700 mb-2">Types Detected</h4>
                            <div class="space-y-2">
                                {system_reminder_types_html if system_reminder_types_html else '<p class="text-sm text-gray-400">No system-reminders detected</p>'}
                            </div>
                        </div>
                    </div>
                    <div>
                        <h4 class="text-sm font-medium text-gray-700 mb-2">Sample Content</h4>
                        <div class="space-y-2 max-h-48 overflow-y-auto">
                            {system_reminder_samples_html if system_reminder_samples_html else '<p class="text-sm text-gray-400">No samples available</p>'}
                        </div>
                    </div>
                </div>
            </div>

            <!-- Tool Usage -->
            <div class="bg-white rounded-lg shadow p-6 mb-6">
                <h2 class="text-lg font-semibold text-gray-800 mb-4">
                    <i class="fas fa-wrench text-gray-500 mr-2"></i>Tool Call Analysis
                </h2>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div>
                        <div class="text-sm text-gray-600 mb-2">Total Tool Calls</div>
                        <div class="text-3xl font-bold text-gray-900">{total_tool_calls}</div>
                        <div class="mt-4">
                            <h4 class="text-sm font-medium text-gray-700 mb-2">Tools by Usage</h4>
                            <div class="space-y-2 max-h-48 overflow-y-auto">
                                {tool_calls_html if tool_calls_html else '<p class="text-sm text-gray-400">No tool calls detected</p>'}
                            </div>
                        </div>
                    </div>
                    <div>
                        <h4 class="text-sm font-medium text-gray-700 mb-2">Tool Distribution</h4>
                        <div class="h-48">
                            <canvas id="toolChart"></canvas>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Headers Analysis -->
            <div class="bg-white rounded-lg shadow p-6 mb-6">
                <h2 class="text-lg font-semibold text-gray-800 mb-4">
                    <i class="fas fa-heading text-indigo-500 mr-2"></i>Request Headers Analysis
                </h2>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div>
                        <h4 class="text-sm font-medium text-gray-700 mb-2">Beta Features / Headers</h4>
                        <div class="space-y-1 max-h-48 overflow-y-auto">
                            {beta_features_html if beta_features_html else '<p class="text-xs text-gray-400">No special headers detected</p>'}
                        </div>
                    </div>
                    <div>
                        <h4 class="text-sm font-medium text-gray-700 mb-2">Anthropic Versions</h4>
                        <div class="space-y-1">
                            {anthropic_versions_html if anthropic_versions_html else '<p class="text-xs text-gray-400">No version data</p>'}
                        </div>
                    </div>
                </div>
            </div>
    """
    # Build chart configs as JSON to avoid f-string escaping and fix layout
    rev = list(token_breakdown_data)[::-1]
    cache_labels = [item["id"] for item in rev]
    cache_config = {
        "type": "bar",
        "data": {
            "labels": cache_labels,
            "datasets": [
                {"label": "Cache Read", "data": [item["cache_read"] for item in rev], "backgroundColor": "rgba(59, 130, 246, 0.6)", "borderColor": "rgb(59, 130, 246)", "borderWidth": 1},
                {"label": "Cache Creation", "data": [item["cache_creation"] for item in rev], "backgroundColor": "rgba(249, 115, 22, 0.6)", "borderColor": "rgb(249, 115, 22)", "borderWidth": 1},
            ],
        },
        "options": {
            "responsive": True,
            "maintainAspectRatio": False,
            "scales": {"x": {"stacked": True, "grid": {"display": False}, "ticks": {"maxRotation": 45, "maxTicksLimit": 20}}, "y": {"stacked": True, "beginAtZero": True}},
            "plugins": {"legend": {"position": "top"}},
        },
    }
    token_totals = [sum(item[k] for item in token_breakdown_data) for k in ("system", "user", "assistant", "tool")]
    token_config = {
        "type": "doughnut",
        "data": {
            "labels": ["System", "User", "Assistant", "Tool"],
            "datasets": [{"data": token_totals, "backgroundColor": ["rgb(59, 130, 246)", "rgb(34, 197, 94)", "rgb(251, 191, 36)", "rgb(107, 114, 128)"]}],
        },
        "options": {"responsive": True, "maintainAspectRatio": False, "plugins": {"legend": {"position": "right"}}},
    }
    tool_labels = list(tool_calls_by_name.keys())[:10]
    tool_values = list(tool_calls_by_name.values())[:10]
    tool_config = {
        "type": "pie",
        "data": {
            "labels": tool_labels,
            "datasets": [{"data": tool_values, "backgroundColor": ["rgb(59, 130, 246)", "rgb(34, 197, 94)", "rgb(251, 191, 36)", "rgb(107, 114, 128)", "rgb(239, 68, 68)", "rgb(139, 92, 246)", "rgb(236, 72, 153)", "rgb(14, 165, 233)", "rgb(168, 85, 247)", "rgb(251, 146, 60)"]}],
        },
        "options": {"responsive": True, "maintainAspectRatio": False, "plugins": {"legend": {"position": "right", "labels": {"boxWidth": 10}}}},
    }
    cache_json = json.dumps(cache_config).replace("</", "<\\/")
    token_json = json.dumps(token_config).replace("</", "<\\/")
    tool_json = json.dumps(tool_config).replace("</", "<\\/")
    chart_head = '<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>'
    chart_footer = f"""
        <script type="application/json" id="deepCacheConfig">{cache_json}</script>
        <script type="application/json" id="deepTokenConfig">{token_json}</script>
        <script type="application/json" id="deepToolConfig">{tool_json}</script>
        <script>
            document.addEventListener("DOMContentLoaded", function() {{
                if (typeof Chart === "undefined") return;
                var el = document.getElementById("cacheChart");
                if (el) new Chart(el.getContext("2d"), JSON.parse(document.getElementById("deepCacheConfig").textContent));
                el = document.getElementById("tokenBreakdownChart");
                if (el) new Chart(el.getContext("2d"), JSON.parse(document.getElementById("deepTokenConfig").textContent));
                el = document.getElementById("toolChart");
                if (el) new Chart(el.getContext("2d"), JSON.parse(document.getElementById("deepToolConfig").textContent));
            }});
        </script>
    """
    sidebar = render_sidebar("applications")
    html = render_page(
        f"Deep Analytics: {proxy_key.name}",
        sidebar,
        breadcrumbs,
        main_content,
        extra_head=chart_head,
        app_tabs_html=app_tabs,
        extra_footer_script=chart_footer,
    )
    return html
