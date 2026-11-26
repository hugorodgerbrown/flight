"""The public pages, and robots.txt and sitemap.xml that point crawlers at them.

They sit outside the installed app's /app/ scope, so the service worker
never caches them and they never show inside the installed app. Every
view takes HEAD as well as GET, which uptime monitors and link checkers send.
"""

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_safe

from apps.core.shortcuts import render
from apps.public.connector import mcp_url


@require_safe
def home(request: HttpRequest) -> HttpResponse:
    """The front page (placeholder): what the app is, and the way in."""
    return render(request, "public/home.html", {"mcp_url": mcp_url()})


@require_safe
def terms(request: HttpRequest) -> HttpResponse:
    """The terms of service."""
    return render(request, "public/terms.html")


@require_safe
def privacy(request: HttpRequest) -> HttpResponse:
    """The privacy notice: what is kept, why, for how long, and your rights."""
    return render(request, "public/privacy.html", {"keeps_email": settings.ACCOUNTS_KEEP_EMAIL})


@require_safe
def help_page(request: HttpRequest) -> HttpResponse:
    """Help: signing in, passkeys, installing the app, offline (placeholder)."""
    return render(request, "public/help.html", {"mcp_url": mcp_url()})


# The public pages a search engine should list, in the sitemap's order.
SITEMAP_PAGES = ["public:home", "public:help", "public:terms", "public:privacy"]

# Paths crawlers should leave alone: the signed-in app, the admin, signing
# in, OAuth and the MCP endpoint. Each is useless to a search result, and
# a sign-in link's address is its token.
ROBOTS_DISALLOW = ["/app/", "/admin/", "/signin/", "/signout/", "/oauth/", "/mcp"]


@require_safe
@cache_control(public=True, max_age=60 * 60 * 24)
def robots_txt(request: HttpRequest) -> HttpResponse:
    """/robots.txt: read the public pages, skip the rest, and here's the sitemap."""
    lines = [
        "User-agent: *",
        *(f"Disallow: {path}" for path in ROBOTS_DISALLOW),
        "",
        f"Sitemap: {settings.SITE_URL}{reverse('public:sitemap')}",
    ]
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain; charset=utf-8")


@require_safe
@cache_control(public=True, max_age=60 * 60 * 24)
def sitemap_xml(request: HttpRequest) -> HttpResponse:
    """/sitemap.xml: the public pages, as absolute ``SITE_URL`` links."""
    xml = render_to_string(
        "public/sitemap.xml",
        {"urls": [settings.SITE_URL + reverse(name) for name in SITEMAP_PAGES]},
    )
    return HttpResponse(xml, content_type="application/xml; charset=utf-8")
