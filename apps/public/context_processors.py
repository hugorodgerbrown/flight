"""Template context for the public pages' shared facts (apps/public/conf.py)."""

from django.http import HttpRequest

from apps.public import conf


def site_facts() -> dict[str, str]:
    """Who runs the site and how to reach them, as templates see them."""
    return {"contact_email": conf.CONTACT_EMAIL}


def site(request: HttpRequest) -> dict[str, dict[str, str]]:
    """Expose the site's facts to every template as ``site``."""
    return {"site": site_facts()}
