# Flight's logo

The Route mark is the map card in miniature: a hollow ring where the flight
left, a solid line for the way flown, the plane as a dot with its halo, a
dotted line for the way still to go, and a ring where it lands. It always
climbs from bottom left to top right. Chosen by Hugo on 26 November 2026
(RAS-139) over two other directions, Contrail and Horizon.

These SVGs are the source. `bin/make-icons` draws `static/icons/` from
them. Below 48px, `favicon.svg` drops the halo and the dots so the mark
stays readable.

| File | Use |
| --- | --- |
| flight-icon.svg | The app icon: the brand blue (#1d4ed8) tile |
| flight-icon-dark.svg | The tile on dark backgrounds (#2f6fde, the map's accent) |
| flight-icon-maskable.svg | Full-bleed, for Android's masks and iOS |
| favicon.svg | The simplified mark, for 16 to 32px |
| flight-mark*.svg | The mark without a tile: blue, dark, white, ink |
| flight-wordmark*.svg | "Flight" in Inter Display SemiBold, outlined |
| flight-lockup*.svg | The mark and wordmark together |

The marketing kit (brand sheet, social images and copy) is kept outside the
repository, in the project's files.
