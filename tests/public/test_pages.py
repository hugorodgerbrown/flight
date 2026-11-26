"""Tests for apps.public.pages: the public pages as Markdown."""

from html import unescape
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from apps.public import conf
from apps.public.pages import PAGES, page_as_markdown, to_markdown


@pytest.mark.parametrize("name", list(PAGES))
def test_each_page_has_a_markdown_version(name: str, settings: Any) -> None:
    """Title, absolute URL, and the page's own heading first in the text."""
    settings.SITE_URL = "https://example.test"
    page = page_as_markdown(name)
    assert page["title"] == PAGES[name].title
    assert page["url"] == "https://example.test" + reverse(PAGES[name].url_name)
    assert page["markdown"].startswith("# ") or "\n# " in page["markdown"]
    assert "<" not in page["markdown"]


@pytest.mark.django_db
@pytest.mark.parametrize("name", list(PAGES))
def test_markdown_carries_the_same_words_as_the_page(client: Client, name: str) -> None:
    """Every heading on the web page appears in the Markdown."""
    html = unescape(client.get(reverse(PAGES[name].url_name)).content.decode())
    markdown = page_as_markdown(name)["markdown"]
    for line in markdown.splitlines():
        if line.startswith("## "):
            assert f"<h2>{line[3:]}</h2>" in html


def test_to_markdown(settings: Any) -> None:
    """Headings, paragraphs, lists, bold and absolute links; other markup keeps its text.

    A button's label is dropped: "Copy" means nothing outside the page.
    """
    settings.SITE_URL = "https://example.test"
    html = """
      <h1>Title</h1>
      <p class="notice">A  note
        over lines.</p>
      <h2>List</h2>
      <ul><li><strong>One</strong>, first</li><li>Two <span>spans</span></li></ul>
      <p>See <a href="/help/">help</a> or <a href="https://other.test/x">elsewhere</a>.</p>
      <p class="copy-field"><code>https://example.test/mcp</code><button>Copy</button></p>
      <p></p>
      <div>loose text is dropped</div>
    """
    assert to_markdown(html) == (
        "# Title\n"
        "\n"
        "A note over lines.\n"
        "\n"
        "## List\n"
        "\n"
        "- **One**, first\n"
        "- Two spans\n"
        "\n"
        "See [help](https://example.test/help/) or [elsewhere](https://other.test/x).\n"
        "\n"
        "https://example.test/mcp\n"
    )


@pytest.mark.django_db
@pytest.mark.parametrize("keeps_email", [False, True])
def test_the_privacy_notice_says_what_is_kept(
    client: Client, settings: Any, keeps_email: bool
) -> None:
    """The page and the MCP text follow ACCOUNTS_KEEP_EMAIL: a key, or the address."""
    settings.ACCOUNTS_KEEP_EMAIL = keeps_email
    html = unescape(client.get(reverse("public:privacy")).content.decode())
    markdown = page_as_markdown("privacy")["markdown"]
    for text in (html, markdown):
        assert "A masked address" in text
        assert ("A key made from your email address" in text) is not keeps_email
        assert ("Your address itself is never stored" in text) is not keeps_email
        assert ("Your email address</strong>" in html) is keeps_email


@pytest.mark.django_db
@pytest.mark.parametrize("name", ["terms", "privacy"])
def test_legal_pages_are_flights_own(client: Client, name: str) -> None:
    """No template placeholder; they name who runs Flight, how to reach them and the date."""
    html = unescape(client.get(reverse(f"public:{name}")).content.decode())
    assert "Placeholder" not in html
    assert "Last updated: not yet" not in html
    assert f"run by {conf.OPERATOR}" in html
    assert f'href="mailto:{conf.CONTACT_EMAIL}"' in html
    assert f"Last updated: {conf.LEGAL_UPDATED}" in html


def test_the_terms_say_the_data_is_not_for_safety_use() -> None:
    """The one clause Flight must never lose: estimates, and not for operational use."""
    text = page_as_markdown("terms")["markdown"]
    assert "never use Flight for safety, navigation or operational decisions" in text
    assert "Positions can be estimated or out of date." in text
    assert "can't tell you whether a flight is delayed" in text
    assert "law of England and Wales" in text


@pytest.mark.parametrize("domain", ["", "flight.example"])
def test_the_privacy_notice_names_fivebar_only_when_counting(settings: Any, domain: str) -> None:
    """The notice names fivebar as a recipient only while FIVEBAR_DOMAIN is set."""
    settings.FIVEBAR_DOMAIN = domain
    text = page_as_markdown("privacy")["markdown"]
    assert ("**fivebar** counts visits" in text) is bool(domain)
    assert "Information Commissioner's Office" in text
    assert "Looking up a flight saves nothing about you." in text
