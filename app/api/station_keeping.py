"""
app/api/station_keeping.py
──────────────────────────
Station-keeping monitor and recovery burn trigger.

Checks each satellite's distance from its nominal orbital slot and
fires corrective burns when the satellite drifts outside the
10 km spherical keep-out zone defined in the problem spec.

Fix history:
  Update-1 (shreya)   — initial RTN box implementation
  Update-5 (shreyansh)— REPLACED RTN box limits with Euclidean 10 km
                         sphere check to match problem spec exactly.
                         RTN box was too restrictive on radial axis
                         (±1 km vs 10 km sphere) causing excess burns,
                         and missed some true violations on combined axes.
"""

import uuid
import math
import numpy as np
from fastapi import APIRouter
from app.config import satellites, get_sim_time

router = APIRouter()

# ── Constants ─────────────────────────────────────────────────────────────────
STATION_KEEP_RADIUS_KM: float = 10.0     # problem spec: 10 km sphere
WARNING_FRACTION:       float = 0.80     # warn at 80% of limit (8 km)
BURN_SCHEDULE_DELAY_S:  float = 300.0    # schedule burn 5 min from detection
RECOVERY_DV_MS:         float = 2.0      # m/s per axis for recovery burn

# In-memory burn queue: { sat_id: [ burn_dict, ... ] }
_burn_queue: dict[str, list] = {}


# ── Core geometry ─────────────────────────────────────────────────────────────

def _distance_to_slot_km(sat) -> float:
    """
    Euclidean distance between satellite's current ECI position and
    its nominal slot ECI position (km).

    Both sat.r and sat.nominal_r must be in km (ECI).
    """
    dr = np.array(sat.r) - np.array(sat.nominal_r)
    return float(np.linalg.norm(dr))


def _station_keep_status(sat) -> dict:
    """
    Returns station-keeping status for a satellite.

    Status tiers:
      OK       — within 10 km sphere
      WARNING  — between 8 km and 10 km (80% threshold)
      VIOLATED — beyond 10 km → recovery burn needed
    """
    dist_km = _distance_to_slot_km(sat)
    warning_km = STATION_KEEP_RADIUS_KM * WARNING_FRACTION

    if dist_km <= warning_km:
        status = "OK"
    elif dist_km <= STATION_KEEP_RADIUS_KM:
        status = "WARNING"
    else:
        status = "VIOLATED"

    return {
        "satellite_id":    sat.sat_id,
        "distance_km":     round(dist_km, 4),
        "limit_km":        STATION_KEEP_RADIUS_KM,
        "warning_km":      warning_km,
        "status":          status,
        "within_box":      dist_km <= STATION_KEEP_RADIUS_KM,
    }


# ── Recovery burn planner ─────────────────────────────────────────────────────

def _compute_recovery_dv(sat) -> np.ndarray:
    """
    Compute a corrective ΔV in ECI frame to push the satellite back
    toward its nominal slot.

    Strategy: burn directly toward the nominal slot position.
    Magnitude capped at RECOVERY_DV_MS (2 m/s) to stay fuel-efficient.
    """
    dr = np.array(sat.nominal_r) - np.array(sat.r)   # vector toward slot
    dist = np.linalg.norm(dr)
    if dist < 1e-9:
        return np.zeros(3)
    direction = dr / dist
    magnitude_kms = RECOVERY_DV_MS / 1000.0           # m/s → km/s
    return direction * magnitude_kms


def _schedule_recovery_burn(sat, sim_time: float) -> dict:
    """
    Build a recovery burn dict and add it to the queue.
    Returns the burn dict.
    """
    dv_eci = _compute_recovery_dv(sat)
    burn_id = f"SK_RECOVERY_{sat.sat_id}_{uuid.uuid4().hex[:6].upper()}"
    burn_time = sim_time + BURN_SCHEDULE_DELAY_S

    burn = {
        "burn_id":     burn_id,
        "satellite_id":sat.sat_id,
        "burn_time_s": burn_time,
        "dv_eci_kms":  dv_eci.tolist(),
        "dv_mag_ms":   round(float(np.linalg.norm(dv_eci)) * 1000.0, 4),
        "reason":      "station_keeping_violation",
        "distance_km": round(_distance_to_slot_km(sat), 4),
    }

    if sat.sat_id not in _burn_queue:
        _burn_queue[sat.sat_id] = []

    # Avoid duplicate queuing — only add if no pending SK burn for this sat
    existing = [b for b in _burn_queue[sat.sat_id]
                if b["reason"] == "station_keeping_violation"]
    if not existing:
        _burn_queue[sat.sat_id].append(burn)

    return burn


# ── API endpoints ─────────────────────────────────────────────────────────────

@router.post("/check")
async def check_station_keeping(body: dict | None = None):
    """
    POST /api/station-keeping/check

    Checks all satellites (or a specific one if satellite_id provided).
    Automatically schedules recovery burns for VIOLATED satellites.

    Body (optional):
      { "satellite_id": "SAT-001" }
    """
    sim_time = get_sim_time()
    target_id = (body or {}).get("satellite_id")

    sats_to_check = (
        {target_id: satellites[target_id]}
        if target_id and target_id in satellites
        else satellites
    )

    results = []
    burns_scheduled = []

    for sat_id, sat in sats_to_check.items():
        # Skip satellites without a nominal slot
        if not hasattr(sat, "nominal_r") or sat.nominal_r is None:
            continue

        status = _station_keep_status(sat)

        if status["status"] == "VIOLATED":
            # Check cooldown before scheduling burn
            if not sat.is_on_cooldown(sim_time):
                burn = _schedule_recovery_burn(sat, sim_time)
                status["recovery_burn_scheduled"] = burn["burn_id"]
                burns_scheduled.append(burn)
            else:
                status["recovery_burn_scheduled"] = None
                status["note"] = "cooldown_active_burn_deferred"

        results.append(status)

    return {
        "checked":          len(results),
        "violations":       sum(1 for r in results if r["status"] == "VIOLATED"),
        "warnings":         sum(1 for r in results if r["status"] == "WARNING"),
        "ok":               sum(1 for r in results if r["status"] == "OK"),
        "burns_scheduled":  len(burns_scheduled),
        "results":          results,
    }


@router.get("/burn-queue")
async def get_burn_queue():
    """
    GET /api/station-keeping/burn-queue
    View all pending station-keeping recovery burns.
    """
    all_burns = []
    for burns in _burn_queue.values():
        all_burns.extend(burns)

    return {
        "total_pending": len(all_burns),
        "burns":         all_burns,
    }


@router.delete("/burn-queue/{satellite_id}")
async def clear_burn_queue(satellite_id: str):
    """
    DELETE /api/station-keeping/burn-queue/{satellite_id}
    Clear all pending burns for a satellite.
    """
    cleared = len(_burn_queue.pop(satellite_id, []))
    return {
        "satellite_id": satellite_id,
        "burns_cleared": cleared,
    }


@router.get("/status/{satellite_id}")
async def get_satellite_status(satellite_id: str):
    """
    GET /api/station-keeping/status/{satellite_id}
    Get station-keeping status for a single satellite.
    """
    if satellite_id not in satellites:
        return {"error": f"Satellite {satellite_id} not found"}

    sat = satellites[satellite_id]
    if not hasattr(sat, "nominal_r") or sat.nominal_r is None:
        return {"error": f"Satellite {satellite_id} has no nominal slot"}

    return _station_keep_status(sat)


# ── Helper used by planner.py ─────────────────────────────────────────────────

def get_burn_queue_for_sat(sat_id: str) -> list:
    """Used by planner to check pending SK burns before scheduling."""
    return _burn_queue.get(sat_id, [])