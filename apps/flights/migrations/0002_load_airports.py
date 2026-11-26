"""Load the bundled airports (apps/flights/data/airports.json) into Airport.

Flightradar24's flights name airports only by code, and its airport
endpoint isn't on the Explorer plan, so names, places and time zones come
from mwgg/Airports (MIT): every airport with an IATA code.
"""

import json
from pathlib import Path
from typing import Any

from django.db import migrations

DATA = Path(__file__).resolve().parent.parent / "data" / "airports.json"


def load(apps: Any, schema_editor: Any) -> None:
    """Add every bundled airport not already stored."""
    airport = apps.get_model("flights", "Airport")
    data = json.loads(DATA.read_text())
    fields = data["fields"]
    known = set(airport.objects.values_list("icao", flat=True))
    airport.objects.bulk_create(
        airport(**dict(zip(fields, row, strict=True)))
        for row in data["airports"]
        if row[0] not in known
    )


def unload(apps: Any, schema_editor: Any) -> None:
    """Remove every airport, bundled or fetched."""
    apps.get_model("flights", "Airport").objects.all().delete()


class Migration(migrations.Migration):
    """Load the bundled airports."""

    dependencies = [("flights", "0001_initial")]

    operations = [migrations.RunPython(load, unload)]
