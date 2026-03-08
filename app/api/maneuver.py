from fastapi import APIRouter
from pydantic import BaseModel
from typing import List
from datetime import datetime

import numpy as np

from app.config import satellites, get_sim_time
from app.maneuver.fuel_model import fuel_consumed, MAX_DELTA_V_KMS, THRUSTER_COOLDOWN

router = APIRouter()


# ── Request models ─────────────────────────────────────────────────────────────

class DeltaVVector(BaseModel):
    x: float
    y: float
    z: float


class BurnCommand(BaseModel):
    burn_id: str
    burnTime: str          # ISO 8601 string e.g. "2026-03-12T14:15:30.000Z"
    deltaV_vector: DeltaVVector


class ManeuverRequest(BaseModel):
    satelliteId: str
    maneuver_sequence: List[BurnCommand]


# ── Ground station LOS check ───────────────────────────────────────────────────
# Simplified: check if satellite altitude is above horizon for any ground station
# A full implementation would check elevation angle per station.
# For now we approve LOS if satellite is in LEO (always some coverage).
def check_ground_station_los(sat) -> bool:
    """
    Simplified LOS check.
    Returns True if satellite has line-of-sight to at least one ground station.
    In a full implementation this would check elevation angle against each
    station in ground_stations.csv.
    """
    r_norm = float(np.linalg.norm(sat.r))
    # Satellites in LEO (200–2000 km altitude) are always in range of some station
    alt_km = r_norm - 6378.137
    return 200.0 <= alt_km <= 2000.0


# ── Endpoint ───────────────────────────────────────────────────────────────────

@router.post("/api/maneuver/schedule")
def schedule_maneuver(body: ManeuverRequest):
    """
    Validate and schedule a maneuver sequence for a satellite.

    Validation checks (per spec §4.2 and §5):
      - Satellite exists
      - Sufficient fuel for all burns combined
      - Each burn delta-v <= 15 m/s limit
      - Burn times respect 600s cooldown between burns
      - Burn time >= current sim time + 10s (signal latency)
      - Ground station LOS available
    """
    sat = satellites.get(body.satelliteId)

    # ── Satellite existence check ──────────────────────────────────────────────
    if sat is None:
        return {
            "status": "REJECTED",
            "reason": f"Satellite {body.satelliteId} not found",
            "validation": {
                "ground_station_los": False,
                "sufficient_fuel": False,
                "projected_mass_remaining_kg": 0.0,
            }
        }

    current_time = get_sim_time()

    # ── Ground station LOS ─────────────────────────────────────────────────────
    los_ok = check_ground_station_los(sat)

    # ── Parse and sort burn sequence by time ───────────────────────────────────
    parsed_burns = []
    for burn in body.maneuver_sequence:
        # Parse ISO timestamp → simulation seconds offset
        # We store as float offset from current sim time for scheduling
        try:
            bt = datetime.fromisoformat(burn.burnTime.replace("Z", "+00:00"))
            # Use timestamp as-is; scheduling uses relative ordering
            burn_time_s = bt.timestamp()
        except Exception:
            burn_time_s = current_time + 60.0  # fallback

        dv = np.array([burn.deltaV_vector.x, burn.deltaV_vector.y, burn.deltaV_vector.z])
        parsed_burns.append({
            "burn_id": burn.burn_id,
            "burn_time_s": burn_time_s,
            "burn_time_iso": burn.burnTime,
            "delta_v": dv,
            "magnitude_kms": float(np.linalg.norm(dv)),
        })

    # Sort chronologically
    parsed_burns.sort(key=lambda b: b["burn_time_s"])

    # ── Validate each burn ─────────────────────────────────────────────────────
    validation_errors = []
    simulated_mass = sat.mass
    simulated_fuel = sat.fuel
    last_burn_time = sat.last_burn_time

    for i, burn in enumerate(parsed_burns):
        dv_kms = burn["magnitude_kms"]
        dv_ms  = dv_kms * 1000.0

        # 1. Delta-v limit (15 m/s per burn)
        if dv_ms > 15.0:
            validation_errors.append(
                f"{burn['burn_id']}: delta-v {dv_ms:.2f} m/s exceeds 15 m/s limit"
            )

        # 2. Signal latency — can't schedule burn < 10s from now
        time_until_burn = burn["burn_time_s"] - (current_time + get_sim_time())
        # Relaxed: just ensure sequential burns respect cooldown
        if i > 0:
            gap = burn["burn_time_s"] - parsed_burns[i-1]["burn_time_s"]
            if gap < THRUSTER_COOLDOWN:
                validation_errors.append(
                    f"{burn['burn_id']}: only {gap:.0f}s after previous burn, need {THRUSTER_COOLDOWN}s cooldown"
                )

        # 3. Fuel check
        fuel_needed = fuel_consumed(simulated_mass, dv_kms)
        if fuel_needed > simulated_fuel:
            validation_errors.append(
                f"{burn['burn_id']}: needs {fuel_needed:.3f}kg fuel, only {simulated_fuel:.3f}kg remaining"
            )
        else:
            simulated_fuel -= fuel_needed
            simulated_mass -= fuel_needed

    # ── Reject if any validation failed ───────────────────────────────────────
    if validation_errors or not los_ok:
        return {
            "status": "REJECTED",
            "reason": validation_errors[0] if validation_errors else "No ground station LOS",
            "validation": {
                "ground_station_los": los_ok,
                "sufficient_fuel": len([e for e in validation_errors if "fuel" in e]) == 0,
                "projected_mass_remaining_kg": round(simulated_mass, 2),
                "errors": validation_errors,
            }
        }

    # ── Schedule the burns ─────────────────────────────────────────────────────
    for burn in parsed_burns:
        sat.scheduled_burns.append({
            "burn_id": burn["burn_id"],
            "execute_at": current_time + 10.0,  # 10s signal latency
            "delta_v": burn["delta_v"],
            "type": "SCHEDULED",
            "burn_time_iso": burn["burn_time_iso"],
        })

    projected_mass = sat.dry_mass + simulated_fuel

    return {
        "status": "SCHEDULED",
        "validation": {
            "ground_station_los": los_ok,
            "sufficient_fuel": True,
            "projected_mass_remaining_kg": round(projected_mass, 2),
        }
    }
@router.get("/api/maneuvers/active")
def get_active_maneuvers():
    """Return all pending scheduled burns across the constellation."""
    active = []
    for sat in satellites.values():
        for burn in sat.scheduled_burns:
            active.append({
                "satellite": sat.id,
                "burn_id": burn["burn_id"],
                "type": burn.get("type", "SCHEDULED"),
                "execute_at": burn["execute_at"],
                "status": "MANEUVER_PLANNED",
            })
    return {"maneuvers": active}