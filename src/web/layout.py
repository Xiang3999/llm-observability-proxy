"""Shared layout components with modern, refined aesthetic."""


# Enhanced color palette and theme system
THEME = {
    # Primary brand colors
    "primary": "blue",
    "primary-50": "effeffff",
    "primary-100": "e8f4ff",
    "primary-200": "d1e8ff",
    "primary-300": "a8d4ff",
    "primary-400": "6eb5ff",
    "primary-500": "2997ff",
    "primary-600": "0073e6",
    "primary-700": "0059b3",

    # Semantic colors
    "success": "emerald",
    "warning": "amber",
    "danger": "rose",
    "purple": "violet",
}


def get_active_nav_class(is_active: bool) -> str:
    """Return navigation item classes based on active state."""
    if is_active:
        return 'group flex items-center px-3 py-2.5 rounded-lg bg-gradient-to-r from-blue-500/10 to-blue-500/5 text-blue-700 font-medium border-l-3 border-blue-500 shadow-sm'
    return 'group flex items-center px-3 py-2.5 rounded-lg text-gray-600 hover:text-gray-900 hover:bg-gray-50/80 transition-all duration-200 border-l-3 border-transparent'


def render_sidebar(
    current_section: str,
    app_id: str | None = None,
    app_name: str | None = None,
) -> str:
    """Modern sidebar with refined aesthetics and smooth interactions."""

    # Main navigation items
    main_nav_items = [
        ("dashboard", "Dashboard", "fa-tachometer-alt", "/dashboard"),
        ("requests", "All Requests", "fa-list", "/requests"),
        ("applications", "Applications", "fa-cubes", "/dashboard#proxy-keys"),
        ("system-prompts", "System Prompts", "fa-file-code", "/system-prompts"),
    ]

    # Analytics submenu items
    analytics_items = [
        ("page-views", "Page Views", "fa-eye", "/analytics/page-views"),
    ]

    def render_nav_item(label: str, icon: str, href: str, is_active: bool, is_subitem: bool = False):
        """Render a single navigation item."""
        base_classes = "group flex items-center px-3 py-2.5 rounded-lg transition-all duration-200"
        if is_active:
            active_classes = " bg-gradient-to-r from-blue-500/10 to-blue-500/5 text-blue-700 font-medium border-l-[3px] border-blue-500 shadow-sm"
            icon_color = "text-blue-500"
        else:
            active_classes = " text-gray-600 hover:text-gray-900 hover:bg-gray-50/80 border-l-[3px] border-transparent"
            icon_color = "text-gray-400 group-hover:text-gray-600"

        indent = "ml-4 w-4" if is_subitem else "w-5"
        active_dot = '<span class="ml-auto w-2 h-2 rounded-full bg-blue-500"></span>' if is_active and not is_subitem else ''

        return f'''
        <a href="{href}" class="{base_classes}{active_classes}">
            <i class="fas {icon} {indent} mr-3 text-center transition-colors duration-200 {icon_color}"></i>
            <span class="text-sm">{label}</span>
            {active_dot}
        </a>
        '''

    # Render main navigation
    nav_html = ""
    for section, label, icon, href in main_nav_items:
        is_active = current_section == section
        nav_html += render_nav_item(label, icon, href, is_active)

    # Render Analytics section with submenu
    analytics_header = '''
    <div class="pt-4 pb-2 px-3">
        <div class="flex items-center justify-between">
            <span class="text-xs font-semibold text-gray-400 uppercase tracking-wider">Analytics</span>
        </div>
    </div>
    '''

    nav_html += analytics_header

    for key, label, icon, href in analytics_items:
        # For analytics, check if it's the current page or if analytics section is active
        is_active = current_section == key
        nav_html += render_nav_item(label, icon, href, is_active, is_subitem=True)

    return f"""
    <aside id="sidebar" class="fixed left-0 top-0 z-40 h-screen w-72 flex flex-col bg-white/95 backdrop-blur-xl border-r border-gray-200/60 transform transition-transform duration-300 ease-out -translate-x-full md:translate-x-0 shadow-xl shadow-gray-200/40">
        <!-- Sidebar Header -->
        <div class="p-5 border-b border-gray-100/80 bg-gradient-to-r from-gray-50/50 to-transparent">
            <a href="/dashboard" class="flex items-center group">
                <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500 to-blue-600 flex items-center justify-center shadow-lg shadow-blue-500/30 group-hover:shadow-blue-500/40 transition-shadow duration-300">
                    <i class="fas fa-chart-line text-white text-lg"></i>
                </div>
                <div class="ml-3">
                    <h1 class="text-lg font-bold bg-gradient-to-r from-gray-900 to-gray-600 bg-clip-text text-transparent">LLM Observability</h1>
                    <p class="text-xs text-gray-500 font-medium">Analytics Dashboard</p>
                </div>
            </a>
        </div>

        <!-- Navigation -->
        <nav class="flex-1 p-4 overflow-y-auto custom-scrollbar">
            <div class="space-y-1">
                {nav_html}
            </div>
        </nav>

        <!-- Footer Actions -->
        <div class="p-4 border-t border-gray-100/80 bg-gradient-to-t from-gray-50/50 to-transparent">
            <a href="/docs" class="flex items-center px-3 py-2.5 text-sm text-gray-600 hover:text-gray-900 hover:bg-gray-50/80 rounded-lg transition-all duration-200 group">
                <i class="fas fa-book w-5 h-5 mr-3 text-center text-gray-400 group-hover:text-gray-600 transition-colors"></i>
                <span class="font-medium">API Documentation</span>
            </a>
            <div class="mt-3 px-3 py-2 bg-gradient-to-r from-blue-50 to-indigo-50/50 rounded-lg border border-blue-100">
                <div class="flex items-center justify-between">
                    <span class="text-xs font-medium text-blue-700">System Status</span>
                    <span class="flex h-2 w-2 relative">
                        <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                        <span class="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                    </span>
                </div>
                <p class="text-xs text-blue-600 mt-1 font-medium">All systems operational</p>
            </div>
        </div>

        <!-- Mobile Close Button -->
        <button id="sidebar-close" type="button" class="md:hidden absolute top-3 right-3 p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-all duration-200" aria-label="Close menu">
            <i class="fas fa-times"></i>
        </button>
    </aside>
    <div id="sidebar-backdrop" class="fixed inset-0 z-30 bg-gray-900/40 backdrop-blur-sm hidden md:hidden transition-opacity duration-300" aria-hidden="true"></div>
    <button id="sidebar-open" type="button" class="fixed bottom-5 left-5 z-40 md:hidden p-3.5 bg-gradient-to-br from-blue-500 to-blue-600 text-white rounded-xl shadow-lg shadow-blue-500/40 hover:shadow-blue-500/50 transition-all duration-300 hover:scale-105" aria-label="Open menu">
        <i class="fas fa-bars text-lg"></i>
    </button>
    """


def render_breadcrumbs(crumbs: list[tuple[str, str | None]]) -> str:
    """Modern breadcrumbs with improved visual hierarchy."""
    parts = []
    for i, (label, url) in enumerate(crumbs):
        if i == len(crumbs) - 1:
            # Current page - not linked, highlighted
            parts.append(f'''
            <span class="flex items-center">
                <i class="fas fa-chevron-right text-gray-300 mx-2 text-xs"></i>
                <span class="px-3 py-1 rounded-lg bg-gradient-to-r from-blue-50 to-indigo-50 text-blue-700 font-medium text-sm border border-blue-100">{label}</span>
            </span>
            ''')
        elif url:
            parts.append(f'''
            <a href="{url}" class="flex items-center text-gray-500 hover:text-gray-700 transition-colors duration-200 font-medium text-sm group">
                {'<i class="fas fa-chevron-right text-gray-300 mx-2 text-xs"></i>' if i > 0 else ''}
                <span class="group-hover:text-gray-900">{label}</span>
            </a>
            ''')

    return f'<nav class="flex items-center text-sm mb-6 pb-4 border-b border-gray-100" aria-label="Breadcrumb">{"".join(parts)}</nav>'


def render_app_tabs(app_id: str, app_name: str, active_tab: str) -> str:
    """Modern tab navigation with smooth transitions."""
    tabs = [
        ("overview", "Overview", f"/applications/{app_id}", "fa-chart-pie"),
        ("analytics", "Analytics", f"/applications/{app_id}/analytics", "fa-chart-line"),
        ("deep-analytics", "Deep Analytics", f"/applications/{app_id}/deep-analytics", "fa-microscope"),
        ("requests", "Requests", f"/requests?app_id={app_id}", "fa-list"),
    ]
    items = []
    for key, label, href, icon in tabs:
        if key == active_tab:
            items.append(f'''
            <a href="{href}" class="group relative px-4 py-2.5 rounded-lg bg-gradient-to-r from-blue-500 to-blue-600 text-white font-medium text-sm shadow-md shadow-blue-500/25 hover:shadow-blue-500/30 transition-all duration-200">
                <i class="fas {icon} mr-2 opacity-80"></i>{label}
                <span class="absolute -bottom-1 left-1/2 transform -translate-x-1/2 w-8 h-0.5 bg-white/60 rounded-full"></span>
            </a>
            ''')
        else:
            items.append(f'''
            <a href="{href}" class="group px-4 py-2.5 rounded-lg text-gray-600 hover:text-gray-900 hover:bg-gray-50 font-medium text-sm transition-all duration-200 flex items-center">
                <i class="fas {icon} mr-2 text-gray-400 group-hover:text-gray-600 transition-colors"></i>{label}
            </a>
            ''')

    return f'''
    <div class="bg-white/60 backdrop-blur-sm rounded-xl p-2 mb-6 border border-gray-200/60 shadow-sm">
        <div class="flex items-center gap-2">
            <div class="w-10 h-10 rounded-lg bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center shadow-md shadow-blue-500/25">
                <i class="fas fa-cube text-white text-sm"></i>
            </div>
            <div>
                <h1 class="text-lg font-bold text-gray-900">{app_name}</h1>
                <p class="text-xs text-gray-500 font-medium">Application Overview</p>
            </div>
        </div>
        <div class="flex flex-wrap gap-1 mt-4 pt-4 border-t border-gray-100">{"".join(items)}</div>
    </div>
    '''


# Enhanced common head with custom styles
COMMON_HEAD = """
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    fontFamily: {
                        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
                        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
                    },
                    animation: {
                        'fade-in': 'fadeIn 0.5s ease-out',
                        'slide-up': 'slideUp 0.4s ease-out',
                        'scale-in': 'scaleIn 0.3s ease-out',
                        'shimmer': 'shimmer 2s linear infinite',
                    },
                    keyframes: {
                        fadeIn: {
                            '0%': { opacity: '0' },
                            '100%': { opacity: '1' },
                        },
                        slideUp: {
                            '0%': { transform: 'translateY(10px)', opacity: '0' },
                            '100%': { transform: 'translateY(0)', opacity: '1' },
                        },
                        scaleIn: {
                            '0%': { transform: 'scale(0.95)', opacity: '0' },
                            '100%': { transform: 'scale(1)', opacity: '1' },
                        },
                        shimmer: {
                            '0%': { backgroundPosition: '-200% 0' },
                            '100%': { backgroundPosition: '200% 0' },
                        },
                    },
                }
            }
        }
    </script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');

        /* Custom scrollbar */
        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }
        ::-webkit-scrollbar-track {
            background: #f1f5f9;
            border-radius: 4px;
        }
        ::-webkit-scrollbar-thumb {
            background: #cbd5e1;
            border-radius: 4px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: #94a3b8;
        }

        /* Custom scrollbar for containers */
        .custom-scrollbar::-webkit-scrollbar {
            width: 6px;
            height: 6px;
        }
        .custom-scrollbar::-webkit-scrollbar-track {
            background: rgba(0, 0, 0, 0.05);
            border-radius: 3px;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb {
            background: rgba(0, 0, 0, 0.2);
            border-radius: 3px;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb:hover {
            background: rgba(0, 0, 0, 0.3);
        }

        /* Glass morphism utilities */
        .glass {
            background: rgba(255, 255, 255, 0.7);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.5);
        }
        .glass-dark {
            background: rgba(15, 23, 42, 0.8);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.1);
        }

        /* Gradient borders */
        .gradient-border {
            position: relative;
            background: linear-gradient(white, white) padding-box,
                        linear-gradient(135deg, #e2e8f0, #cbd5e1) border-box;
            border: 1px solid transparent;
        }

        /* Smooth transitions */
        * {
            transition-timing-function: cubic-bezier(0.4, 0, 0.2, 1);
        }

        /* Table row hover effect */
        .table-row-hover {
            transition: all 0.2s ease;
        }
        .table-row-hover:hover {
            transform: translateX(2px);
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
        }
    </style>
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
    """Full page with modern layout and enhanced visual design."""
    return f"""<!DOCTYPE html>
<html lang="en" class="scroll-smooth">
<head>
    <title>{title}</title>
    {COMMON_HEAD}
    {extra_head}
</head>
<body class="bg-gradient-to-br from-slate-50 via-gray-50 to-blue-50/30 min-h-screen antialiased">
    {sidebar_html}
    <div class="md:ml-72 min-h-screen flex flex-col">
        <div class="flex-1 p-6 md:p-8">
            {breadcrumbs_html}
            {app_tabs_html}
            <main class="animate-fade-in">
                {main_content}
            </main>
        </div>
        <footer class="py-6 px-8 text-center text-sm text-gray-500 border-t border-gray-200/60 bg-white/40 backdrop-blur-sm">
            <div class="flex items-center justify-center gap-2">
                <i class="fas fa-shield-halved text-blue-500"></i>
                <span>LLM Observability Proxy</span>
                <span class="text-gray-300">•</span>
                <a href="/docs" class="text-blue-600 hover:text-blue-700 font-medium transition-colors">API Docs</a>
                <span class="text-gray-300">•</span>
                <span class="text-gray-400">v2.0</span>
            </div>
        </footer>
    </div>
    {extra_footer_script}
    <script>
        // Sidebar toggle functionality
        (function() {{
            var sidebar = document.getElementById('sidebar');
            var backdrop = document.getElementById('sidebar-backdrop');
            var openBtn = document.getElementById('sidebar-open');
            var closeBtn = document.getElementById('sidebar-close');
            if (!sidebar) return;
            function openSidebar() {{
                sidebar.classList.remove('-translate-x-full');
                if (backdrop) backdrop.classList.remove('hidden');
                document.body.style.overflow = 'hidden';
            }}
            function closeSidebar() {{
                sidebar.classList.add('-translate-x-full');
                if (backdrop) backdrop.classList.add('hidden');
                document.body.style.overflow = '';
            }}
            if (openBtn) openBtn.addEventListener('click', openSidebar);
            if (closeBtn) closeBtn.addEventListener('click', closeSidebar);
            if (backdrop) backdrop.addEventListener('click', closeSidebar);
        }})();

        // Add smooth reveal animations on scroll - optimized for performance
        document.addEventListener('DOMContentLoaded', function() {{
            // Only animate elements that are not immediately visible
            // Skip animation for better perceived performance on initial load
            const animatedElements = document.querySelectorAll('.card, .stat-card, .table-container');

            // If few elements, skip animation for instant display
            if (animatedElements.length <= 5) {{
                animatedElements.forEach(el => el.style.opacity = '1');
                return;
            }}

            const observer = new IntersectionObserver((entries) => {{
                entries.forEach(entry => {{
                    if (entry.isIntersecting) {{
                        entry.target.classList.add('animate-slide-up');
                        entry.target.style.opacity = '1';
                    }}
                }});
            }}, {{ threshold: 0.1, rootMargin: '50px' }});

            animatedElements.forEach(el => {{
                el.style.opacity = '1'; // Show immediately, animation class will handle the rest
                observer.observe(el);
            }});
        }});
    </script>
</body>
</html>"""
