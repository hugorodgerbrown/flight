"""Check followed flights for take-offs and landings, and send their alerts (RAS-144).

Render runs ``python manage.py watch_flights --commit`` every two minutes.
Without ``--commit`` it lists the follows that are due and makes no calls
(each check spends Flightradar24 credits). ``--commit`` checks them, saves
what changed, sends the alerts and deletes follows that finished over a
day ago. ``-v 2`` narrates each call and each event.
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from apps.alerts import watch
from apps.alerts.models import Follow
from apps.flights.fr24 import Fr24Api, Fr24Error, plural

logger = logging.getLogger(__name__)

# The cron job's runs are two minutes apart; it isn't waited on, so calls
# are paced a little and a rate-limited call gets one short retry.
GAP_SECONDS = 1.0
RETRY_SECONDS = 10.0


class Command(BaseCommand):
    """Check followed flights and send take-off and landing alerts."""

    help = "Check followed flights for take-offs and landings and send alerts (needs --commit)."

    def add_arguments(self, parser: CommandParser) -> None:
        """Add --commit."""
        parser.add_argument(
            "--commit", action="store_true", help="Check the flights (costs credits) and send."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """List what's due, or (with --commit) check it and send."""
        verbosity = int(options["verbosity"])
        now = timezone.now()
        due = list(Follow.objects.due(now))
        if not options["commit"]:
            self.stdout.write(f"{plural(len(due), 'follow')} due for a check.")
            for item in due:
                self.stdout.write(f"  {item.to_string()} ({item.state})")
            self.stdout.write("Nothing checked. Run with --commit to check them and send alerts.")
            return
        cleared, _ = Follow.objects.cleared(now).delete()
        if not due:
            if verbosity >= 1:
                self.stdout.write(f"Nothing due. Cleared {plural(cleared, 'finished follow')}.")
            return
        if not settings.FR24_API_KEY:
            raise CommandError("FR24_API_KEY isn't set, so no flight can be checked.")
        api = Fr24Api(
            settings.FR24_API_KEY,
            self.say if verbosity >= 2 else (lambda text: None),
            verbosity,
            gap=GAP_SECONDS,
            retry=RETRY_SECONDS,
        )
        try:
            run = watch.watch(api, now, say=self.say if verbosity >= 2 else lambda text: None)
        except Fr24Error as exc:
            logger.error("watch_flights: Flightradar24 failed: %s", exc)
            raise CommandError(f"Flightradar24 failed: {exc}") from exc
        summary = (
            f"Checked {plural(run.checked, 'follow')} in {plural(run.calls, 'call')}: "
            f"{plural(len(run.events), 'alert')} sent, {len(run.ended)} given up, "
            f"{cleared} cleared."
        )
        logger.info("watch_flights: %s", summary)
        if verbosity >= 1:
            self.stdout.write(summary)

    def say(self, text: str) -> None:
        """Print one progress line."""
        self.stdout.write(text)
