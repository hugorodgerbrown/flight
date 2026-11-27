"""The picture a chat shows when a share link is pasted: 1200 by 630, in the Route style (RAS-145).

Drawn with Pillow from the link's card: the app's icon and name, the flight
number, its state in words, and the route as the logo draws it (a hollow
ring at each airport, a solid line flown, the plane's dot with its halo, a
dashed line still to fly). Chats keep the first picture they fetch, so it
says what was true then; the page itself is always live.

Colours are the light scheme's tokens in static/css/app.css; a chat shows
the picture on its own background, so it carries its own white.
"""

from __future__ import annotations

import io
import logging
from functools import cache
from pathlib import Path
from typing import Any

from django.conf import settings
from PIL import Image, ImageDraw, ImageFont

from apps.pwa import conf
from apps.shares.shares import ENDED, LANDED

logger = logging.getLogger(__name__)

WIDTH, HEIGHT = 1200, 630
FONTS = Path(__file__).resolve().parent / "fonts"
ICON = Path(settings.BASE_DIR) / "static" / "icons" / "icon-192.png"
# static/css/app.css, light scheme: --card, --text-1, --text-2, --brand.
CARD = "#ffffff"
TEXT_1 = "#14171a"
TEXT_2 = "#4b5563"
BRAND = "#1d4ed8"
HALO = "#d2dcf7"  # --brand at 20% on white
LEFT = 72
LINE_Y = 470


@cache
def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Return Liberation Sans (bundled, OFL) at ``size`` pixels."""
    name = "LiberationSans-Bold.ttf" if bold else "LiberationSans-Regular.ttf"
    return ImageFont.truetype(str(FONTS / name), size)


def duration(minutes: int) -> str:
    """Return ``minutes`` as "2 h 32 m", "2 h" or "25 m"."""
    hours, mins = divmod(max(0, minutes), 60)
    return " ".join(p for p in (f"{hours} h" if hours else "", f"{mins} m" if mins else "") if p)


def status_line(state: str, flight: dict[str, Any]) -> tuple[str, str]:
    """Return the state in a word or two, and what follows it."""
    if state == ENDED:
        return "Link ended", "This share link has stopped"
    if state == LANDED or flight.get("status") == LANDED:
        when = flight.get("arrives_local")
        return "Landed", f"at {flight['destination']['code']}" + (f" at {when}" if when else "")
    minutes = flight.get("minutes_to_go")
    parts = []
    if minutes:
        parts.append(f"{duration(int(minutes))} to go")
    if flight.get("arrives_local"):
        parts.append(f"lands {flight['arrives_local']}")
    return "In the air", " · ".join(parts)


def render(state: str, flight: dict[str, Any]) -> bytes:
    """Return the picture for a link showing ``flight`` in ``state``, as PNG bytes."""
    image = Image.new("RGB", (WIDTH, HEIGHT), CARD)
    draw = ImageDraw.Draw(image)
    live = state not in (ENDED, LANDED) and flight.get("status") != LANDED

    try:
        icon = Image.open(ICON).convert("RGBA").resize((56, 56), Image.Resampling.LANCZOS)
        image.paste(icon, (LEFT, 64), icon)
    except OSError:
        logger.warning("No icon at %s for the share picture", ICON)
    draw.text((LEFT + 72, 92), conf.APP_NAME, font=font(34, bold=True), fill=TEXT_1, anchor="lm")
    if live:
        label = font(28)
        right = WIDTH - LEFT
        text_left = right - draw.textlength("Live", font=label)
        draw.text((right, 92), "Live", font=label, fill=TEXT_2, anchor="rm")
        dot = (text_left - 22, 92)
        draw.ellipse(box(dot, 15), fill=HALO)
        draw.ellipse(box(dot, 7), fill=BRAND)

    draw.text((LEFT, 170), str(flight.get("flight", "")), font=font(120, bold=True), fill=TEXT_1)
    word, rest = status_line(state, flight)
    status_font = font(40, bold=True)
    draw.text((LEFT, 335), word, font=status_font, fill=BRAND if live else TEXT_2)
    if rest:
        x = LEFT + draw.textlength(word, font=status_font)
        draw.text((x, 335), f" · {rest}", font=font(40), fill=TEXT_2)

    route(draw, flight, live)
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def route(draw: ImageDraw.ImageDraw, flight: dict[str, Any], live: bool) -> None:
    """Draw the route line: origin ring, flown, plane, way ahead, destination ring."""
    start, end = LEFT + 20, WIDTH - LEFT - 20
    progress = 1.0 if not live else max(0.0, min(1.0, float(flight.get("progress") or 0)))
    plane = start + (end - start) * progress
    if live:
        dash = start
        while dash < end - 24:
            if dash > plane + 34:
                draw.ellipse(box((dash, LINE_Y), 3), fill=TEXT_2)
            dash += 20
    draw.line(
        [(start + 18, LINE_Y), (max(start + 18, plane - (30 if live else 18)), LINE_Y)],
        fill=BRAND,
        width=10,
    )
    for x in (start, end):
        draw.ellipse(box((x, LINE_Y), 15), outline=TEXT_2, width=5, fill=CARD)
    if live:
        draw.ellipse(box((plane, LINE_Y), 30), fill=HALO)
        draw.ellipse(box((plane, LINE_Y), 15), fill=BRAND)
    codes = font(40, bold=True)
    draw.text((LEFT, LINE_Y + 50), flight["origin"]["code"], font=codes, fill=TEXT_1)
    draw.text(
        (WIDTH - LEFT, LINE_Y + 50),
        flight["destination"]["code"],
        font=codes,
        fill=TEXT_1,
        anchor="ra",
    )


def box(centre: tuple[float, float], radius: float) -> tuple[float, float, float, float]:
    """Return the bounding box of a circle."""
    x, y = centre
    return (x - radius, y - radius, x + radius, y + radius)
