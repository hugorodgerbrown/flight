"""Tests for the app's home at /app/ (RAS-139)."""

from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from apps.flights import views

pytestmark = pytest.mark.django_db


def test_home_needs_sign_in(client: Client) -> None:
    """Signed out, /app/ sends you to sign in and back."""
    response = client.get(reverse("flights:home"))
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("accounts:sign_in"))


def test_home_is_the_app_root(signed_in: Client) -> None:
    """The app's first page sits at the scope's root, as the manifest's start_url."""
    assert reverse("flights:home") == "/app/"
    assert signed_in.get("/app/").status_code == 200


def test_home_says_how_to_ask(signed_in: Client, monkeypatch: Any) -> None:
    """It gives the questions to try and the connector's address to copy."""
    monkeypatch.setattr(views, "mcp_url", lambda: "https://flight.example/mcp")
    content = signed_in.get(reverse("flights:home")).content.decode()
    assert "<h1>Ask Claude where your flight is</h1>" in content
    for ask in views.EXAMPLE_ASKS:
        assert f'<li class="ask">{ask}</li>' in content
    assert 'data-copy="https://flight.example/mcp"' in content
    assert f'href="{reverse("public:help")}#use-with-ai"' in content


def test_home_without_mcp_leaves_out_the_connector(signed_in: Client, monkeypatch: Any) -> None:
    """An app with no connector has no address to show."""
    monkeypatch.setattr(views, "mcp_url", lambda: "")
    content = signed_in.get(reverse("flights:home")).content.decode()
    assert 'id="connect"' not in content
