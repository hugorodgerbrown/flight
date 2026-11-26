"""Fixtures for the alerts tests: Flightradar24 from memory, push recorded not sent."""

from typing import Any

import pytest

from apps.alerts import push
from tests import fr24_fake

PUBLIC_KEY = "BPublicKeyForTests"
PRIVATE_KEY = "private-key-for-tests"


@pytest.fixture
def fr24(monkeypatch: Any, settings: Any, db: None) -> dict[str, Any]:
    """Flightradar24, answered from memory."""
    return fr24_fake.install(monkeypatch, settings)


@pytest.fixture
def pushes(monkeypatch: Any, settings: Any) -> list[dict[str, Any]]:
    """Turn push on with test keys; record each push instead of sending it."""
    settings.WEBPUSH_PUBLIC_KEY = PUBLIC_KEY
    settings.WEBPUSH_PRIVATE_KEY = PRIVATE_KEY
    settings.WEBPUSH_CONTACT = "https://flight.example.test"
    sent: list[dict[str, Any]] = []

    def webpush(**kwargs: Any) -> None:
        sent.append(kwargs)

    monkeypatch.setattr(push, "webpush", webpush)
    return sent
