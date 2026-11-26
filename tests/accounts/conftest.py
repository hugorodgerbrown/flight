"""Accounts tests run with the template's default, keeping no addresses.

Flight keeps them (ACCOUNTS_KEEP_EMAIL, for alerts: RAS-144), but these
tests come from the Titan template and check its default; the ones about
the setting set it themselves.
"""

from typing import Any

import pytest


@pytest.fixture(autouse=True)
def keep_no_email(settings: Any) -> None:
    """Run each test with ACCOUNTS_KEEP_EMAIL off unless it turns it on."""
    settings.ACCOUNTS_KEEP_EMAIL = False
