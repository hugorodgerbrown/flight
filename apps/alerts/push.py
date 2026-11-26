"""Web Push: sending a notification to each of a person's browsers (RAS-144).

Messages are encrypted for each browser and signed with the app's VAPID
key (``WEBPUSH_PRIVATE_KEY``; its public half, ``WEBPUSH_PUBLIC_KEY``, is
what a browser subscribes with). Without the keys, push is off: nothing
is offered and nothing is sent. A browser the push service says is gone
(404 or 410) is deleted.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from django.conf import settings
from django.utils import timezone
from pywebpush import WebPushException, webpush

from apps.alerts.models import PushSubscription

logger = logging.getLogger(__name__)

# How long a push service keeps trying to deliver an alert: after an hour it's old news.
TTL_SECONDS = 3600
GONE = {404, 410}


def enabled() -> bool:
    """True when the VAPID keys are set, so browsers can subscribe and alerts can be pushed."""
    return bool(settings.WEBPUSH_PUBLIC_KEY and settings.WEBPUSH_PRIVATE_KEY)


def send_to_user(user: Any, words: dict[str, str]) -> int:
    """Push ``words`` to each of ``user``'s browsers; return how many took it."""
    if not enabled():
        return 0
    data = json.dumps({k: words[k] for k in ("title", "body", "url", "tag")})
    sent = 0
    for subscription in PushSubscription.objects.for_user(user):
        if send(subscription, data):
            sent += 1
    return sent


def send(subscription: PushSubscription, data: str) -> bool:
    """Push ``data`` to one browser; return whether the push service took it."""
    try:
        webpush(
            subscription_info=subscription.as_info(),
            data=data,
            vapid_private_key=settings.WEBPUSH_PRIVATE_KEY,
            vapid_claims={"sub": settings.WEBPUSH_CONTACT},
            ttl=TTL_SECONDS,
            timeout=10,
        )
    except WebPushException as exc:
        status = getattr(exc.response, "status_code", None)
        if status in GONE:
            logger.info("alerts.push %s is gone (%s): deleted", subscription.to_string(), status)
            subscription.delete()
        else:
            logger.warning("alerts.push to %s failed: %s", subscription.to_string(), status)
        return False
    except Exception:
        logger.exception("alerts.push to %s failed", subscription.to_string())
        return False
    subscription.last_sent_at = timezone.now()
    subscription.save(update_fields=["last_sent_at", "updated_at"])
    return True
