"""The installed app's home: how to ask Claude about a flight.

Flight is used from Claude (apps/mcp); the app itself is where a signed-in
person finds the connector's address, and where followed flights will be
listed once alerts ship.
"""

import logging

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


@require_GET
@login_required
def home(request: HttpRequest) -> HttpResponse:
    """The app's first page and the manifest's start_url."""
    return render(
        request,
        "flights/home.html",
        {"mcp_url": mcp_url(), "example_asks": EXAMPLE_ASKS},
    )
