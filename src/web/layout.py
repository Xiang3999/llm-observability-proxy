"""Shared layout components for Scheme C: sidebar, breadcrumbs, app tabs."""

from typing import List, Tuple, Optional

# current_section: "dashboard" | "requests" | "applications"
def render_sidebar(
    current_section: str,
    app_id: Optional[str] = None,
    app_name: Optional[str] = None,
) -> str:
    dash_cls = 'bg-blue-50 text-blue-700 border-l-4 border-blue-600' if current_section == "dashboard" else 'text-gray-700 hover:bg-gray-100'
    req_cls = 'bg-blue-50 text-blue-700 border-l-4 border-blue-600' if current_section == "requests" else 'text-gray-700 hover:bg-gray-100'
    app_cls = 'bg-blue-50 text-blue-700 border-l-4 border-blue-600' if current_section == "applications" else 'text-gray-700 hover:bg-gray-100'

    return f"""
    <aside id="sidebar" class="fixed left-0 top-0 z-30 h-screen w-64 flex flex-col bg-white shadow-lg border-r border-gray-200 transform transition-transform duration-200 -translate-x-full md:translate-x-0">
        <div class="p-4 border-b border-gray-200">
            <a href="/dashboard" class="text-xl font-bold text-gray-800 hover:text-blue-600 flex items-center">
                <i class="fas fa-chart-line text-blue-500 mr-2"></i>LLM Observability
            </a>
        </div>
        <nav class="flex-1 p-3 space-y-0.5 overflow-y-auto">
            <a href="/dashboard" class="flex items-center px-3 py-2.5 rounded-lg {dash_cls}">
                <i class="fas fa-tachometer-alt w-5 mr-3 text-center"></i>
                <span>Dashboard</span>
            </a>
            <a href="/requests" class="flex items-center px-3 py-2.5 rounded-lg {req_cls}">
                <i class="fas fa-list w-5 mr-3 text-center"></i>
                <span>Requests</span>
            </a>
            <a href="/dashboard#proxy-keys" class="flex items-center px-3 py-2.5 rounded-lg {app_cls}">
                <i class="fas fa-cubes w-5 mr-3 text-center"></i>
                <span>Applications</span>
            </a>
        </nav>
        <div class="p-3 border-t border-gray-200">
            <a href="/docs" class="flex items-center px-3 py-2 text-sm text-gray-600 hover:text-blue-600 rounded-lg">
                <i class="fas fa-book w-5 mr-3 text-center"></i>
                <span>API Docs</span>
            </a>
        </div>
        <button id="sidebar-close" type="button" class="md:hidden absolute top-2 right-2 p-2 text-gray-500 hover:text-gray-700" aria-label="Close menu">
            <i class="fas fa-times"></i>
        </button>
    </aside>
    <div id="sidebar-backdrop" class="fixed inset-0 z-20 bg-black/50 hidden md:hidden" aria-hidden="true"></div>
    <button id="sidebar-open" type="button" class="fixed bottom-4 left-4 z-40 md:hidden p-3 bg-blue-600 text-white rounded-full shadow-lg hover:bg-blue-700" aria-label="Open menu">
        <i class="fas fa-bars"></i>
    </button>
    """


def render_breadcrumbs(crumbs: List[Tuple[str, Optional[str]]]) -> str:
    """crumbs: list of (label, url). url=None means current page (not linked)."""
    parts = []
    for i, (label, url) in enumerate(crumbs):
        if url:
            parts.append(f'<a href="{url}" class="text-blue-600 hover:text-blue-800">{label}</a>')
        else:
            parts.append(f'<span class="text-gray-600 font-medium">{label}</span>')
    sep = '<span class="text-gray-400 mx-2">/</span>'
    return f'<nav class="text-sm text-gray-500 mb-4" aria-label="Breadcrumb">{sep.join(parts)}</nav>'


def render_app_tabs(app_id: str, app_name: str, active_tab: str) -> str:
    """active_tab: overview | analytics | deep-analytics | requests"""
    tabs = [
        ("overview", "Overview", f"/applications/{app_id}"),
        ("analytics", "Analytics", f"/applications/{app_id}/analytics"),
        ("deep-analytics", "Deep Analytics", f"/applications/{app_id}/deep-analytics"),
        ("requests", "Requests", f"/requests?app_id={app_id}"),
    ]
    items = []
    for key, label, href in tabs:
        if key == active_tab:
            items.append(f'<a href="{href}" class="px-4 py-2 rounded-t-lg bg-white border border-b-0 border-gray-200 font-medium text-blue-600 -mb-px"> {label}</a>')
        else:
            items.append(f'<a href="{href}" class="px-4 py-2 rounded-t-lg text-gray-600 hover:bg-gray-100 hover:text-gray-900"> {label}</a>')
    return f'''
    <div class="border-b border-gray-200 mb-6">
        <div class="flex items-center gap-2 mb-2">
            <h1 class="text-xl font-bold text-gray-900">{app_name}</h1>
        </div>
        <div class="flex flex-wrap gap-1">{''.join(items)}</div>
    </div>
    '''


COMMON_HEAD = """
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
"""


def render_page(
    title: str,
    sidebar_html: str,
    breadcrumbs_html: str,
    main_content: str,
    extra_head: str = "",
    app_tabs_html: str = "",
    extra_footer_script: str = "",
) -> str:
    """Full page with sidebar layout. main_content is the inner HTML of the main area.
    extra_head: injected in <head> (e.g. Chart.js script tag).
    extra_footer_script: injected before </body> so it runs after DOM is ready (use for chart init).
    """
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <title>{title}</title>
    {COMMON_HEAD}
    {extra_head}
</head>
<body class="bg-gray-100 min-h-screen">
    {sidebar_html}
    <div class="md:ml-64 min-h-screen flex flex-col">
        <div class="flex-1 p-4 md:p-6">
            {breadcrumbs_html}
            {app_tabs_html}
            <div class="mt-4">
                {main_content}
            </div>
        </div>
        <footer class="p-4 text-center text-sm text-gray-500 border-t border-gray-200 bg-white/50">
            LLM Observability Proxy · <a href="/docs" class="text-blue-600 hover:underline">API Docs</a>
        </footer>
    </div>
    {extra_footer_script}
    <script>
        (function() {{
            var sidebar = document.getElementById('sidebar');
            var backdrop = document.getElementById('sidebar-backdrop');
            var openBtn = document.getElementById('sidebar-open');
            var closeBtn = document.getElementById('sidebar-close');
            if (!sidebar) return;
            function openSidebar() {{
                sidebar.classList.remove('-translate-x-full');
                if (backdrop) backdrop.classList.remove('hidden');
            }}
            function closeSidebar() {{
                sidebar.classList.add('-translate-x-full');
                if (backdrop) backdrop.classList.add('hidden');
            }}
            if (openBtn) openBtn.addEventListener('click', openSidebar);
            if (closeBtn) closeBtn.addEventListener('click', closeSidebar);
            if (backdrop) backdrop.addEventListener('click', closeSidebar);
        }})();
    </script>
</body>
</html>"""
