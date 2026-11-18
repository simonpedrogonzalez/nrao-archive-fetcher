"""Check that an observed field is the requested calibrator, by position.

Field names cannot be trusted alone: historical inputs and the "most-observed phase calibrator"
heuristic produced entries whose field was another source (e.g. 1407+284 -> J1125+2610). Names
can also differ legitimately (J1227+3635_S, "J0958+6533 CG", J2139+143), so the decisive test is
the field position against the catalog position of the requested source.

Plain Python (no astropy) so CASA's interpreter can import it during extraction.
"""
from __future__ import annotations

import math
import re

# Same radius as the archive cone search that found the observations.
MATCH_RADIUS_ARCSEC = 5.0

_JNAME = re.compile(r"^J(\d{2})(\d{2})(\d{2}(?:\.\d+)?)?([+-])(\d{2})(\d{0,4})(?!\d)")


def _sexagesimal(text):
    text = str(text).strip()
    sign = -1.0 if text.startswith("-") else 1.0
    parts = [float(p) for p in re.split(r"[:\s]+", text.lstrip("+-")) if p]
    if not parts or len(parts) > 3:
        raise ValueError("bad sexagesimal value %r" % text)
    return sign * sum(value / 60.0 ** index for index, value in enumerate(parts))


def sky_degrees(ra, dec):
    """(ra, dec) in degrees from 'HH:MM:SS' / '±DD:MM:SS' strings or numbers in degrees."""
    if isinstance(ra, str) and re.search(r"[:\s]", ra.strip()):
        ra_deg = _sexagesimal(ra) * 15.0
    else:
        ra_deg = float(ra)
    dec_deg = _sexagesimal(dec) if isinstance(dec, str) and re.search(r"[:\s]", dec.strip()) else float(dec)
    if not (math.isfinite(ra_deg) and math.isfinite(dec_deg) and -90.0 <= dec_deg <= 90.0):
        raise ValueError("bad position %r %r" % (ra, dec))
    return ra_deg % 360.0, dec_deg


def separation_arcsec(ra1, dec1, ra2, dec2):
    """Great-circle separation of two positions given in degrees."""
    ra1, dec1, ra2, dec2 = map(math.radians, (ra1, dec1, ra2, dec2))
    h = (math.sin((dec2 - dec1) / 2) ** 2
         + math.cos(dec1) * math.cos(dec2) * math.sin((ra2 - ra1) / 2) ** 2)
    return math.degrees(2 * math.asin(min(1.0, math.sqrt(h)))) * 3600.0


def jname_consistent(name, ra_deg, dec_deg):
    """True/False when a J2000 name (JHHMM[SS]±DD[d|MM|MMSS], suffixes allowed) does/does not
    match the position; None when the name does not encode a position."""
    match = _JNAME.match(str(name or "").strip())
    if not match:
        return None
    hh, mm, ss, sign, dd, rest = match.groups()
    ra_name, ra_unit = int(hh) + int(mm) / 60.0, 1 / 60.0
    if ss:
        ra_name, ra_unit = ra_name + float(ss) / 3600.0, 1 / 3600.0
    dec_name = float(dd)
    dec_unit = {0: 1.0, 1: 0.1, 2: 1 / 60.0, 4: 1 / 3600.0}.get(len(rest))
    if dec_unit is None:
        return None
    if len(rest) == 1:
        dec_name += int(rest) / 10.0
    elif len(rest) >= 2:
        dec_name += int(rest[:2]) / 60.0 + (int(rest[2:]) / 3600.0 if len(rest) == 4 else 0.0)
    # Names truncate (or round) the position, so allow one unit around the named cell.
    ra_hours = (ra_deg / 15.0) % 24.0
    ra_diff = abs((ra_hours - (ra_name + ra_unit / 2) + 12.0) % 24.0 - 12.0)
    signed = (-1.0 if sign == "-" else 1.0) * (dec_name + dec_unit / 2)
    return ra_diff <= ra_unit and abs(dec_deg - signed) <= dec_unit


def position_problem(field_ra_deg, field_dec_deg, ra, dec, radius_arcsec=MATCH_RADIUS_ARCSEC):
    """None when the field lies within radius of the requested position, else the reason."""
    if not str(ra or "").strip() or not str(dec or "").strip():
        return "requested source has no catalog position"
    ra_deg, dec_deg = sky_degrees(ra, dec)
    separation = separation_arcsec(field_ra_deg, field_dec_deg, ra_deg, dec_deg)
    if separation > radius_arcsec:
        return "field is %.1f arcsec from the requested source (limit %.1f)" % (separation, radius_arcsec)
    return None
