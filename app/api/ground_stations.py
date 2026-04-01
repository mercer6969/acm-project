import csv
from functools import lru_cache
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple
 
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
 
router = APIRouter()
 
# ---------------------------------------------------------------------------
# Earth constants
# ---------------------------------------------------------------------------
EARTH_RADIUS_KM = 6371.0
MU = 398600.4418          # km³/s²  (gravitational parameter)
J2 = 1.08262668e-3        # second zonal harmonic (oblateness)
 
# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class GroundStation:
    name: str
    lat_deg: float
    lon_deg: float
    alt_m: float
    min_elev_deg: float = 5.0
 
    @property
    def lat_rad(self) -> float:
        return math.radians(self.lat_deg)
 
    @property
    def lon_rad(self) -> float:
        return math.radians(self.lon_deg)
 
    def ecef(self) -> tuple[float, float, float]:
        """ECEF position of the station (km)."""
        r = EARTH_RADIUS_KM + self.alt_m / 1000.0
        x = r * math.cos(self.lat_rad) * math.cos(self.lon_rad)
        y = r * math.cos(self.lat_rad) * math.sin(self.lon_rad)
        z = r * math.sin(self.lat_rad)
        return x, y, z
 
 
@dataclass
class SatelliteState:
    """Minimal ECI state used for LOS computation."""
    sat_id: str
    x_km: float   # ECI X
    y_km: float   # ECI Y
    z_km: float   # ECI Z
    epoch_unix: float  # Unix timestamp (seconds)
 
 
@dataclass
class PassWindow:
    station: str
    sat_id: str
    start_unix: float
    end_unix: float
    max_elevation_deg: float
    duration_s: float
 
 
@dataclass
class BlackoutWindow:
    sat_id: str
    start_unix: float
    end_unix: float
    duration_s: float
    preceding_station: Optional[str] = None
    following_station: Optional[str] = None
 
 
# ---------------------------------------------------------------------------
# CSV loader
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _load_stations(csv_path: str = "ground_stations.csv") -> Tuple[GroundStation, ...]:
    path = Path(csv_path)
    if path.exists():
        stations = []
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Strip whitespace from all keys (CSV may have spaces after commas)
                row = {k.strip(): v.strip() for k, v in row.items()}
                stations.append(GroundStation(
                    name         = row["Station_Name"],
                    lat_deg      = float(row["Latitude"]),
                    lon_deg      = float(row["Longitude"]),
                    alt_m        = float(row["Elevation_m"]),
                    min_elev_deg = float(row.get("Min_Elevation_Angle_deg", 5.0)),
                ))
        return tuple(stations)
    # ... fallback unchanged
 
# ---------------------------------------------------------------------------
# LOS Checker
# ---------------------------------------------------------------------------
def elevation_angle_deg(station: GroundStation, sat: SatelliteState) -> float:
    """
    Compute the elevation angle (degrees) from a ground station to a satellite
    given the satellite's ECI coordinates and the station's ECEF position.
 
    NOTE: This assumes a non-rotating Earth approximation sufficient for short
    time windows. For full accuracy, rotate station ECEF by GAST.
    """
    sx, sy, sz = station.ecef()
    # Vector from station to satellite
    dx, dy, dz = sat.x_km - sx, sat.y_km - sy, sat.z_km - sz
    range_km = math.sqrt(dx*dx + dy*dy + dz*dz)
 
    # Station up-vector (normalised ECEF position)
    r_s = math.sqrt(sx*sx + sy*sy + sz*sz)
    ux, uy, uz = sx/r_s, sy/r_s, sz/r_s
 
    # Dot product gives component of range vector along up
    dot = dx*ux + dy*uy + dz*uz
    elev_rad = math.asin(dot / range_km)
    return math.degrees(elev_rad)
 
 
def has_los(station: GroundStation, sat: SatelliteState) -> bool:
    """Return True if the satellite is above the station's minimum elevation mask."""
    return elevation_angle_deg(station, sat) >= station.min_elev_deg
 
 
def best_elevation(stations: List[GroundStation], sat: SatelliteState) -> tuple[Optional[str], float]:
    """Return (station_name, elevation_deg) for the station with highest elevation."""
    best_name, best_elev = None, -90.0
    for st in stations:
        elev = elevation_angle_deg(st, sat)
        if elev > best_elev:
            best_elev = elev
            best_name = st.name
    return best_name, best_elev
 
 
# ---------------------------------------------------------------------------
# Blackout zone calculator
# ---------------------------------------------------------------------------
def compute_blackout_windows(
    stations: List[GroundStation],
    sat_track: List[SatelliteState],
    gap_threshold_s: float = 60.0,
) -> tuple[List[PassWindow], List[BlackoutWindow]]:
    """
    Given a list of SatelliteState snapshots (sorted by epoch_unix), return:
      - pass_windows: periods when at least one station has LOS
      - blackout_windows: gaps between passes (no station has LOS)
 
    gap_threshold_s: minimum gap length to qualify as a blackout (default 60 s)
    """
    if not sat_track:
        return [], []
 
    sat_id = sat_track[0].sat_id
    pass_windows: List[PassWindow] = []
    blackout_windows: List[BlackoutWindow] = []
 
    in_contact = False
    contact_start = 0.0
    contact_station = None
    contact_max_elev = -90.0
    last_contact_station = None
 
    for state in sat_track:
        visible_station = None
        max_elev = -90.0
        for st in stations:
            elev = elevation_angle_deg(st, state)
            if elev >= st.min_elev_deg and elev > max_elev:
                max_elev = elev
                visible_station = st.name
 
        currently_visible = visible_station is not None
 
        if currently_visible and not in_contact:
            # Contact acquired
            if in_contact is False and contact_station is None:
                # first ever contact - check if there was a blackout before it
                if len(sat_track) > 0 and state.epoch_unix > sat_track[0].epoch_unix:
                    gap = state.epoch_unix - sat_track[0].epoch_unix
                    if gap >= gap_threshold_s:
                        blackout_windows.append(BlackoutWindow(
                            sat_id=sat_id,
                            start_unix=sat_track[0].epoch_unix,
                            end_unix=state.epoch_unix,
                            duration_s=gap,
                            preceding_station=None,
                            following_station=visible_station,
                        ))
            in_contact = True
            contact_start = state.epoch_unix
            contact_station = visible_station
            contact_max_elev = max_elev
 
        elif currently_visible and in_contact:
            # Ongoing contact — track best elevation and handover
            if max_elev > contact_max_elev:
                contact_max_elev = max_elev
            if visible_station != contact_station:
                contact_station = visible_station  # handover
 
        elif not currently_visible and in_contact:
            # Contact lost
            duration = state.epoch_unix - contact_start
            pass_windows.append(PassWindow(
                station=contact_station or "unknown",
                sat_id=sat_id,
                start_unix=contact_start,
                end_unix=state.epoch_unix,
                max_elevation_deg=round(contact_max_elev, 2),
                duration_s=round(duration, 1),
            ))
            last_contact_station = contact_station
            in_contact = False
            blackout_start = state.epoch_unix
 
        elif not currently_visible and not in_contact:
            # Ongoing blackout — will be closed when contact resumes
            pass
 
    # Close any open blackout at end of track
    if not in_contact and len(sat_track) > 1:
        gap = sat_track[-1].epoch_unix - (
            pass_windows[-1].end_unix if pass_windows else sat_track[0].epoch_unix
        )
        if gap >= gap_threshold_s:
            blackout_windows.append(BlackoutWindow(
                sat_id=sat_id,
                start_unix=sat_track[-1].epoch_unix - gap,
                end_unix=sat_track[-1].epoch_unix,
                duration_s=round(gap, 1),
                preceding_station=last_contact_station,
                following_station=None,
            ))
 
    return pass_windows, blackout_windows
 
 
# ---------------------------------------------------------------------------
# FastAPI endpoints
# ---------------------------------------------------------------------------
class SatStateIn(BaseModel):
    sat_id: str
    x_km: float
    y_km: float
    z_km: float
    epoch_unix: float
 
 
class LOSRequest(BaseModel):
    states: List[SatStateIn]
    csv_path: str = "ground_stations.csv"
    gap_threshold_s: float = 60.0
 
 
class LOSResponse(BaseModel):
    sat_id: str
    pass_windows: list
    blackout_windows: list
    total_passes: int
    total_blackouts: int
    total_blackout_duration_s: float
    coverage_percent: float
 
 
@router.post("/los-check", response_model=LOSResponse)
def los_check(req: LOSRequest):
    """
    POST /api/ground-stations/los-check
 
    Body:
    {
      "states": [{"sat_id": "SAT-001", "x_km": ..., "y_km": ..., "z_km": ..., "epoch_unix": ...}, ...],
      "csv_path": "ground_stations.csv",
      "gap_threshold_s": 60
    }
 
    Returns pass windows, blackout windows, and coverage statistics.
    """
    try:
        stations = _load_stations(req.csv_path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
 
    track = [SatelliteState(**s.dict()) for s in req.states]
    track.sort(key=lambda s: s.epoch_unix)
 
    passes, blackouts = compute_blackout_windows(stations, track, req.gap_threshold_s)
 
    total_time = track[-1].epoch_unix - track[0].epoch_unix if len(track) > 1 else 1
    total_blackout_s = sum(b.duration_s for b in blackouts)
    coverage = max(0.0, 100.0 * (1 - total_blackout_s / total_time)) if total_time > 0 else 0.0
 
    return LOSResponse(
        sat_id=track[0].sat_id,
        pass_windows=[vars(p) for p in passes],
        blackout_windows=[vars(b) for b in blackouts],
        total_passes=len(passes),
        total_blackouts=len(blackouts),
        total_blackout_duration_s=round(total_blackout_s, 1),
        coverage_percent=round(coverage, 2),
    )
 
 
@router.get("/list")
def list_stations(csv_path: str = "ground_stations.csv"):
    """GET /api/ground-stations/list  — return all stations from CSV."""
    try:
        stations = _load_stations(csv_path)
        return [vars(s) for s in stations]
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))