import csv
import math
import time as _time
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple
 
# ── FastAPI (already in your requirements.txt) ────────────────────────────────
from fastapi import APIRouter
 
router = APIRouter()
 
# ── Earth / astronomy constants ───────────────────────────────────────────────
EARTH_RADIUS_KM   = 6378.137          # WGS-84 equatorial radius (km)
EARTH_FLATTENING  = 1.0 / 298.257223563
J2000_UNIX        = 946728000.0       # Unix time at J2000.0 epoch
OMEGA_EARTH_RAD_S = 7.2921150e-5      # Earth rotation rate (rad/s)
 
 
# ── GroundStation data class ──────────────────────────────────────────────────
 
class GroundStation(NamedTuple):
    name:         str
    lat_deg:      float
    lon_deg:      float
    alt_m:        float
    min_elev_deg: float
 
 
# ── CSV loader — reads file once, then caches forever ────────────────────────
 
@lru_cache(maxsize=1)
def _load_stations(csv_path: str = "ground_stations.csv") -> Tuple[GroundStation, ...]:
    """
    Load ground stations from CSV. Returns a tuple so it is hashable
    and compatible with lru_cache.
 
    Expected CSV columns: name, lat, lon, alt_m, min_elevation_deg
 
    If the file is not found, falls back to the 6 hard-coded stations
    that match the problem statement's ground station network.
    """
    path = Path(csv_path)
 
    if path.exists():
        stations = []
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                stations.append(GroundStation(
                    name         = row["name"].strip(),
                    lat_deg      = float(row["lat"]),
                    lon_deg      = float(row["lon"]),
                    alt_m        = float(row["alt_m"]),
                    min_elev_deg = float(row.get("min_elevation_deg", 5.0)),
                ))
        return tuple(stations)
 
    # Fallback — 6 stations from the problem statement
    return (
        GroundStation("Svalbard",        78.23,   15.39,  474,  5.0),
        GroundStation("Fairbanks",       64.97, -147.72,  138,  5.0),
        GroundStation("Maspalomas",      27.76,  -15.63,  205,  5.0),
        GroundStation("Canberra",       -35.40,  148.98,  812,  5.0),
        GroundStation("Kourou",           5.25,  -52.80,   14,  5.0),
        GroundStation("Hartebeesthoek", -25.89,   27.71, 1415,  5.0),
    )
 
 
# ── Greenwich Apparent Sidereal Time ─────────────────────────────────────────
 
def _gast_radians(epoch_unix: float) -> float:
    """
    Compute Greenwich Apparent Sidereal Time (radians) for a Unix timestamp.
    Uses the IAU 1982 GMST model — accurate to ~0.01° for elevation checks.
    """
    days_since_j2000 = (epoch_unix - J2000_UNIX) / 86400.0
    gmst_degrees = (280.46061837 + 360.98564736629 * days_since_j2000) % 360.0
    return math.radians(gmst_degrees)
 
 
# ── Coordinate helpers ────────────────────────────────────────────────────────
 
def _station_ecef(gs: GroundStation) -> Tuple[float, float, float]:
    """
    Convert geodetic (lat, lon, alt) to ECEF (km) using WGS-84 ellipsoid.
    """
    lat    = math.radians(gs.lat_deg)
    lon    = math.radians(gs.lon_deg)
    alt_km = gs.alt_m / 1000.0
 
    e2 = 2.0 * EARTH_FLATTENING - EARTH_FLATTENING ** 2
    N  = EARTH_RADIUS_KM / math.sqrt(1.0 - e2 * math.sin(lat) ** 2)
 
    x = (N + alt_km) * math.cos(lat) * math.cos(lon)
    y = (N + alt_km) * math.cos(lat) * math.sin(lon)
    z = (N * (1.0 - e2) + alt_km)   * math.sin(lat)
    return x, y, z
 
 
def _station_eci(gs: GroundStation, gast: float) -> Tuple[float, float, float]:
    """
    Rotate station ECEF → ECI by the Greenwich sidereal angle (Z-axis rotation).
    """
    x_ecef, y_ecef, z_ecef = _station_ecef(gs)
    cos_g = math.cos(gast)
    sin_g = math.sin(gast)
    return (
         cos_g * x_ecef - sin_g * y_ecef,
         sin_g * x_ecef + cos_g * y_ecef,
         z_ecef,
    )
 
 
# ── Core geometry ─────────────────────────────────────────────────────────────
 
def _elevation_angle_deg(
    gs: GroundStation,
    sat_r: Tuple[float, float, float],
    gast: float,
) -> float:
    """
    Compute elevation angle (degrees) from a ground station to a satellite.
 
    gs:    GroundStation
    sat_r: satellite ECI position (x, y, z) in km
    gast:  Greenwich Apparent Sidereal Time in radians
    """
    sx, sy, sz = _station_eci(gs, gast)
 
    # Range vector: station → satellite
    dx, dy, dz = sat_r[0] - sx, sat_r[1] - sy, sat_r[2] - sz
    rng = math.sqrt(dx*dx + dy*dy + dz*dz)
    if rng < 1e-9:
        return 90.0  # satellite is at the station (shouldn't happen)
 
    # Up-vector at station (unit vector along station ECEF position)
    s_mag = math.sqrt(sx*sx + sy*sy + sz*sz)
    ux, uy, uz = sx / s_mag, sy / s_mag, sz / s_mag
 
    # Elevation = arcsin( dot(range_hat, up) )
    dot = dx*ux + dy*uy + dz*uz
    sin_elev = max(-1.0, min(1.0, dot / rng))   # clamp for float safety
    return math.degrees(math.asin(sin_elev))
 
 
# ── Public functions (called from maneuver.py) ────────────────────────────────
 
def has_ground_station_los(
    sat_r_km,
    epoch_unix: Optional[float] = None,
    csv_path: str = "ground_stations.csv",
) -> bool:
    """
    Returns True if the satellite has LOS to at least one ground station.
 
    sat_r_km:   satellite ECI position — list, tuple, or numpy array [x, y, z] km
    epoch_unix: simulation time as Unix timestamp (uses wall clock if None)
    csv_path:   path to ground_stations.csv (relative to where uvicorn runs)
 
    This is the only function you need to call from schedule_maneuver().
    """
    if epoch_unix is None:
        epoch_unix = _time.time()
 
    # Convert numpy array to plain tuple if needed (numpy not required here)
    try:
        r = (float(sat_r_km[0]), float(sat_r_km[1]), float(sat_r_km[2]))
    except (TypeError, IndexError):
        return False
 
    gast     = _gast_radians(epoch_unix)
    stations = _load_stations(csv_path)
 
    for gs in stations:
        if _elevation_angle_deg(gs, r, gast) >= gs.min_elev_deg:
            return True
 
    return False
 
 
def los_details(
    sat_r_km,
    epoch_unix: Optional[float] = None,
    csv_path: str = "ground_stations.csv",
) -> Dict:
    """
    Returns full per-station breakdown — useful for debug responses
    and the grader's blind-conjunction pre-upload scenario.
 
    Returns:
    {
      "any_los": bool,
      "best_station": "Svalbard",
      "best_elev_deg": 23.4,
      "stations": [
        {"station": "Svalbard", "elevation_deg": 23.4, "visible": true,  "min_elev_mask": 5.0},
        {"station": "Kourou",   "elevation_deg": -8.1, "visible": false, "min_elev_mask": 5.0},
        ...
      ]
    }
    """
    if epoch_unix is None:
        epoch_unix = _time.time()
 
    try:
        r = (float(sat_r_km[0]), float(sat_r_km[1]), float(sat_r_km[2]))
    except (TypeError, IndexError):
        return {"any_los": False, "best_station": None, "best_elev_deg": -90.0, "stations": []}
 
    gast     = _gast_radians(epoch_unix)
    stations = _load_stations(csv_path)
 
    results    = []
    any_los    = False
    best_name  = None
    best_elev  = -90.0
 
    for gs in stations:
        elev    = _elevation_angle_deg(gs, r, gast)
        visible = elev >= gs.min_elev_deg
        if visible:
            any_los = True
        if elev > best_elev:
            best_elev = elev
            best_name = gs.name
        results.append({
            "station":       gs.name,
            "elevation_deg": round(elev, 2),
            "visible":       visible,
            "min_elev_mask": gs.min_elev_deg,
        })
 
    return {
        "any_los":       any_los,
        "best_station":  best_name,
        "best_elev_deg": round(best_elev, 2),
        "stations":      results,
    }
 
 
# ── FastAPI endpoint (bonus — exposes LOS check via REST) ─────────────────────
 
@router.get("/api/los/check")
def los_check_endpoint(
    x: float, y: float, z: float,
    epoch_unix: Optional[float] = None,
):
    """
    GET /api/los/check?x=6871&y=0&z=0&epoch_unix=1234567890
 
    Quick REST check — useful for testing from browser or curl:
      curl "http://localhost:8000/api/los/check?x=6871&y=0&z=0"
    """
    details = los_details((x, y, z), epoch_unix=epoch_unix)
    return details