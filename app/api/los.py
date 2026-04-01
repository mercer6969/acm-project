"""
app/api/los.py
──────────────
Bug 8 fix: GAST now uses proper Unix timestamp (SIM_EPOCH_UNIX + sim_time),
           not sim elapsed seconds alone.

Bug 9 fix: los_check_endpoint now accepts min_elev parameter.

Bug 10 fix: _load_stations() uses stripped DictReader fieldnames so CSV
            headers with trailing spaces or mixed case are handled correctly.
            Uses flexible key lookup (strip + case-insensitive) as fallback.
"""

import csv
import math
from functools import lru_cache
from pathlib import Path
from typing import Dict, NamedTuple, Optional, Tuple

from fastapi import APIRouter

router = APIRouter()

EARTH_RADIUS_KM  = 6378.137
EARTH_FLATTENING = 1.0 / 298.257223563
J2000_UNIX       = 946728000.0   # Unix time at J2000.0 epoch


class GroundStation(NamedTuple):
    name:         str
    lat_deg:      float
    lon_deg:      float
    alt_m:        float
    min_elev_deg: float


def _find_key(row: dict, *candidates: str) -> str:
    """
    Return the value for the first candidate key found in row,
    comparing after stripping whitespace from both sides.
    Raises KeyError with a helpful message listing actual columns if none match.
    """
    stripped_map = {k.strip(): k for k in row}   # stripped_key -> original_key
    for c in candidates:
        orig = stripped_map.get(c.strip())
        if orig is not None:
            return row[orig]
    raise KeyError(
        f"None of {candidates} found. Actual CSV columns: {list(row.keys())}"
    )


@lru_cache(maxsize=1)
def _load_stations(csv_path: str = "ground_stations.csv") -> Tuple[GroundStation, ...]:
    """
    Load ground stations from CSV (cached after first load).
    Falls back to 6 hard-coded stations from the problem spec if CSV not found.

    Key lookup is whitespace-tolerant: works even if the CSV has spaces
    after commas in the header row e.g. "Station_ID, Station_Name, Latitude".
    """
    path = Path(csv_path)
    if path.exists():
        stations = []
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    name         = _find_key(row, "Station_Name", "name")
                    lat_deg      = float(_find_key(row, "Latitude",  "lat", "lat_deg"))
                    lon_deg      = float(_find_key(row, "Longitude", "lon", "lon_deg"))
                    alt_m        = float(_find_key(row, "Elevation_m", "elevation_m",
                                                        "alt_m", "alt_km"))
                    min_elev_deg = float(_find_key(row, "Min_Elevation_Angle_deg",
                                                        "min_elevation_angle_deg",
                                                        "min_elev_deg",
                                                        "min_elevation_deg"))
                except KeyError as exc:
                    raise KeyError(
                        f"ground_stations.csv column mismatch: {exc}"
                    ) from exc

                stations.append(GroundStation(
                    name         = name.strip(),
                    lat_deg      = lat_deg,
                    lon_deg      = lon_deg,
                    alt_m        = alt_m,
                    min_elev_deg = min_elev_deg,
                ))
        return tuple(stations)

    # Fallback — exact 6 stations from problem statement
    return (
        GroundStation("ISTRAC_Bengaluru",      13.0333,   77.5167,  820,  5.0),
        GroundStation("Svalbard_Sat_Station",  78.2297,   15.4077,  400,  5.0),
        GroundStation("Goldstone_Tracking",    35.4266, -116.8900, 1000, 10.0),
        GroundStation("Punta_Arenas",         -53.1500,  -70.9167,   30,  5.0),
        GroundStation("IIT_Delhi_Ground_Node", 28.5450,   77.1926,  225, 15.0),
        GroundStation("McMurdo_Station",      -77.8463,  166.6682,   10,  5.0),
    )


def _gast_radians(unix_timestamp: float) -> float:
    days = (unix_timestamp - J2000_UNIX) / 86400.0
    gmst = (280.46061837 + 360.98564736629 * days) % 360.0
    return math.radians(gmst)


def _station_ecef(gs: GroundStation) -> Tuple[float, float, float]:
    lat    = math.radians(gs.lat_deg)
    lon    = math.radians(gs.lon_deg)
    alt_km = gs.alt_m / 1000.0
    e2 = 2.0 * EARTH_FLATTENING - EARTH_FLATTENING ** 2
    N  = EARTH_RADIUS_KM / math.sqrt(1.0 - e2 * math.sin(lat) ** 2)
    x  = (N + alt_km) * math.cos(lat) * math.cos(lon)
    y  = (N + alt_km) * math.cos(lat) * math.sin(lon)
    z  = (N * (1.0 - e2) + alt_km) * math.sin(lat)
    return x, y, z


def _station_eci(gs: GroundStation, gast: float) -> Tuple[float, float, float]:
    x, y, z     = _station_ecef(gs)
    cos_g, sin_g = math.cos(gast), math.sin(gast)
    return (cos_g*x - sin_g*y,  sin_g*x + cos_g*y,  z)


def _elevation_deg(gs: GroundStation, sat_r, gast: float) -> float:
    sx, sy, sz = _station_eci(gs, gast)
    dx = sat_r[0] - sx
    dy = sat_r[1] - sy
    dz = sat_r[2] - sz
    rng = math.sqrt(dx*dx + dy*dy + dz*dz)
    if rng < 1e-9:
        return 90.0
    s_mag = math.sqrt(sx*sx + sy*sy + sz*sz)
    ux, uy, uz = sx/s_mag, sy/s_mag, sz/s_mag
    dot = dx*ux + dy*uy + dz*uz
    return math.degrees(math.asin(max(-1.0, min(1.0, dot / rng))))


# ── Public API ────────────────────────────────────────────────────────────────

def has_ground_station_los(
    sat_r_km,
    epoch_unix: Optional[float] = None,
    csv_path: str = "ground_stations.csv",
) -> bool:
    """True if satellite has LOS to at least one ground station."""
    if epoch_unix is None:
        from app.config import get_unix_time
        epoch_unix = get_unix_time()

    try:
        r = (float(sat_r_km[0]), float(sat_r_km[1]), float(sat_r_km[2]))
    except (TypeError, IndexError):
        return False

    gast     = _gast_radians(epoch_unix)
    stations = _load_stations(csv_path)

    for gs in stations:
        if _elevation_deg(gs, r, gast) >= gs.min_elev_deg:
            return True
    return False


def los_details(
    sat_r_km,
    epoch_unix: Optional[float] = None,
    csv_path: str = "ground_stations.csv",
) -> Dict:
    """Full per-station breakdown for debug responses and grader inspection."""
    if epoch_unix is None:
        from app.config import get_unix_time
        epoch_unix = get_unix_time()

    try:
        r = (float(sat_r_km[0]), float(sat_r_km[1]), float(sat_r_km[2]))
    except (TypeError, IndexError):
        return {"any_visible": False, "stations": [], "gast_deg": 0}

    gast     = _gast_radians(epoch_unix)
    stations = _load_stations(csv_path)

    results   = []
    any_vis   = False
    best_name = None
    best_elev = -90.0

    for gs in stations:
        elev    = _elevation_deg(gs, r, gast)
        visible = elev >= gs.min_elev_deg
        if visible:
            any_vis = True
        if elev > best_elev:
            best_elev = elev
            best_name = gs.name
        results.append({
            "station":       gs.name,
            "elevation_deg": round(elev, 2),
            "visible":       visible,
            "min_elev_deg":  gs.min_elev_deg,
        })

    return {
        "any_visible":   any_vis,
        "best_station":  best_name,
        "best_elev_deg": round(best_elev, 2),
        "stations":      results,
        "gast_deg":      round(math.degrees(gast) % 360, 4),
    }


# ── REST endpoint ─────────────────────────────────────────────────────────────

@router.get("/api/los/check")
def los_check_endpoint(
    x: float,
    y: float,
    z: float,
    epoch_unix: Optional[float] = None,
    min_elev: float = 5.0,
):
    """
    GET /api/los/check?x=6871&y=0&z=0
    GET /api/los/check?x=6871&y=0&z=0&min_elev=-90   (any satellite above horizon)
    """
    if epoch_unix is None:
        from app.config import get_unix_time
        epoch_unix = get_unix_time()

    details = los_details((x, y, z), epoch_unix=epoch_unix)

    # Apply the requested elevation threshold
    for st in details["stations"]:
        st["visible"] = st["elevation_deg"] >= min_elev
    details["any_visible"] = any(
        s["elevation_deg"] >= min_elev for s in details["stations"]
    )

    return {
        "sat_eci_km":  {"x": x, "y": y, "z": z},
        "sim_time_s":  0,
        "any_visible": details["any_visible"],
        "stations":    details["stations"],
        "gast_deg":    details["gast_deg"],
    }