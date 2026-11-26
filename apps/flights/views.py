"""The installed app's home: how to ask Claude about a flight, and the flights you follow.

Flight is used from Claude (apps/mcp); the app itself is where a signed-in
person finds the connector's address, and follows flights for their
take-off and landing alerts (apps/alerts, RAS-144).
"""

import logging
from typing import Any

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.views.decorators.http import require_GET

from apps.core.shortcuts import render
from apps.public.connector import mcp_url

logger = logging.getLogger(__name__)

# What to try first, shown as examples. Operating flight numbers only:
# Flightradar24 doesn't know codeshare numbers.
EXAMPLE_ASKS = [
    "Where is BA117?",
    "When does EZY8461 land?",
    "Has QF1 taken off yet?",
]


def home_context() -> dict[str, Any]:
    """Return what the home page shows besides the Following list."""
    return {"mcp_url": mcp_url(), "example_asks": EXAMPLE_ASKS}


@require_GET
@login_required
def home(request: HttpRequest) -> HttpResponse:
    """The app's first page and the manifest's start_url."""
    from apps.alerts.views import following_context

    return render(request, "flights/home.html", home_context() | following_context(request))
