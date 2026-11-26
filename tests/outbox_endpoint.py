"""A stand-in outbox endpoint, for tests of the outbox's server side.

Flight has no offline write yet (the template's notes sample, which was the
outbox's example, is gone), but the idempotency middleware and the CSRF
pages still guard every write the outbox will send. These tests post to
this endpoint, mounted only in their own URLconf, as a real one would be.
"""

import json
import logging

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.urls import include, path
from django.views.decorators.http import require_POST

from apps.core.decorators import login_required_json

logger = logging.getLogger(__name__)

URL = "/app/test-outbox/"

# Every write the endpoint ran, so a test can count them.
WRITES: list[str] = []


@require_POST
@login_required_json
def write(request: HttpRequest) -> HttpResponse:
    """Save ``text`` from JSON or a form post, as an outbox endpoint does."""
    if request.content_type == "application/json":
        try:
            data = json.loads(request.body)
        except ValueError:
            return JsonResponse({"errors": {"__all__": ["Not JSON."]}}, status=400)
        text = data.get("text") if isinstance(data, dict) else None
    else:
        text = request.POST.get("text")
    if not text:
        return JsonResponse({"errors": {"text": ["Required."]}}, status=400)
    WRITES.append(text)
    return JsonResponse({"text": text, "count": len(WRITES)}, status=201)


urlpatterns = [
    path("app/test-outbox/", write, name="test-outbox"),
    path("", include("config.urls")),
]
