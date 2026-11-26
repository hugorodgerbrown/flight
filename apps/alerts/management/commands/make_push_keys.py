"""Make a VAPID key pair for Web Push alerts (RAS-144).

``python manage.py make_push_keys`` prints a new pair, to set once as
``WEBPUSH_PUBLIC_KEY`` and ``WEBPUSH_PRIVATE_KEY``. It saves nothing.
Changing the pair later stops every browser's subscription working, so
each person has to turn notifications on again.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


def b64url(data: bytes) -> str:
    """Return ``data`` as unpadded base64url, as browsers and pywebpush take keys."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_pair() -> tuple[str, str]:
    """Return a new (public, private) VAPID key pair: a P-256 point and its raw secret."""
    key = ec.generate_private_key(ec.SECP256R1())
    secret = key.private_numbers().private_value.to_bytes(32, "big")
    point = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return b64url(point), b64url(secret)


class Command(BaseCommand):
    """Print a new VAPID key pair."""

    help = "Print a new VAPID key pair for WEBPUSH_PUBLIC_KEY and WEBPUSH_PRIVATE_KEY."

    def handle(self, *args: Any, **options: Any) -> None:
        """Print the pair; nothing is stored."""
        public, private = make_pair()
        self.stdout.write(f"WEBPUSH_PUBLIC_KEY={public}")
        self.stdout.write(f"WEBPUSH_PRIVATE_KEY={private}")
        logger.info("make_push_keys: made a new pair (not stored)")
