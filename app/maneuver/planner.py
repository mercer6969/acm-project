"""
app/maneuver/planner.py
────────────────────────
Bug fixes in this version:
  Bug 5: sat.cooldown_remaining(t) → sat.cooldown_remaining_at(t)
          cooldown_remaining is a property (returns 0.0 always),
          cooldown_remaining_at(sim_time) is the correct method.
  Bug 6: sat.r/sat.v are Python lists — wrap with np.array() before
          any vector arithmetic. list / scalar fails; np.array / scalar works.
  Bug 7: sat.is_critical_fuel → sat.is_eol (correct property name on disk)

Issues 4,5,6,7 preserved from previous sessions.
"""

import numpy as np

from app.config import debris, get_sim_time, satellites
from app.logger import (
    log_eol_triggered,
    log_graveyard_executed,
    log_maneuver_executed,
    log_maneuver_planned,
    log_recovery_executed,
    log_recovery_scheduled,
)
from app.maneuver.fuel_model import THRUSTER_COOLDOWN, fuel_consumed

EVASION_DV_KMS            = 0.010
RECOVERY_DV_KMS           = 0.010
GRAVEYARD_DV_KMS          = 0.012
SAFE_DISTANCE_KM          = 0.5
RECOVERY_CHECK_INTERVAL_S = 300.0
SIGNAL_LATENCY_S          = 10.0


# ── numpy safety helper ───────────────────────────────────────────────────────

def _arr(x):
    """
    Convert any vector (Python list or numpy array) to float64 numpy array.
    All sat.r / sat.v / deb.r / deb.v must go through this before math.
    """
    return np.array(x, dtype=float)


# ── RTN frame ─────────────────────────────────────────────────────────────────

def compute_rtn_axes(r, v):
    r = _arr(r)
    v = _arr(v)
    r_hat = r / np.linalg.norm(r)
    n_hat = np.cross(r_hat, v / np.linalg.norm(v))
    n_hat = n_hat / np.linalg.norm(n_hat)
    t_hat = np.cross(n_hat, r_hat)
    return r_hat, t_hat, n_hat


# ── Geometry-aware evasion (Issue 4) ─────────────────────────────────────────

def compute_evasion_dv(sat_r, sat_v, deb_r, deb_v,
                       magnitude_kms=EVASION_DV_KMS):
    """
    Compute evasion ΔV in ECI that maximises miss distance.

    Classifies approach direction in RTN frame at linear TCA:
      Mostly transverse (head-on/tail-on) → burn radial
      Mostly radial (above/below)         → burn transverse
      Mostly normal (out-of-plane)        → burn transverse (cheaper than plane change)

    Bug 6 fix: _arr() converts lists to numpy before any division/cross-product.
    """
    sat_r = _arr(sat_r)
    sat_v = _arr(sat_v)
    deb_r = _arr(deb_r)
    deb_v = _arr(deb_v)

    r_hat, t_hat, n_hat = compute_rtn_axes(sat_r, sat_v)

    rel_r = sat_r - deb_r
    rel_v = sat_v - deb_v

    v_norm_sq = float(np.dot(rel_v, rel_v))
    t_ca = (max(0.0, -float(np.dot(rel_r, rel_v)) / v_norm_sq)
            if v_norm_sq > 1e-12 else 0.0)

    rel_at_tca = rel_r + rel_v * t_ca
    rel_R = float(np.dot(rel_at_tca, r_hat))
    rel_T = float(np.dot(rel_at_tca, t_hat))
    rel_N = float(np.dot(rel_at_tca, n_hat))

    abs_R, abs_T, abs_N = abs(rel_R), abs(rel_T), abs(rel_N)

    if abs_T >= abs_R and abs_T >= abs_N:
        burn_axis = r_hat
        burn_sign = 1.0 if rel_R >= 0 else -1.0
    elif abs_R >= abs_T and abs_R >= abs_N:
        burn_axis = t_hat
        burn_sign = 1.0 if rel_T >= 0 else -1.0
    else:
        burn_axis = t_hat
        burn_sign = 1.0 if rel_T >= 0 else -1.0

    dv_eci = burn_axis * burn_sign * magnitude_kms
    return dv_eci, (rel_R, rel_T, rel_N)


# ── TCA-aware recovery (Issue 5) ─────────────────────────────────────────────

def _threat_still_active(sat_id, debris_id):
    sat = satellites.get(sat_id)
    deb = debris.get(debris_id)
    if sat is None or deb is None:
        return False

    rel_r = _arr(sat.r) - _arr(deb.r)
    rel_v = _arr(sat.v) - _arr(deb.v)
    v_sq  = float(np.dot(rel_v, rel_v))

    t_ca    = max(0.0, -float(np.dot(rel_r, rel_v)) / v_sq) if v_sq > 1e-12 else 0.0
    closest = float(np.linalg.norm(rel_r + rel_v * t_ca))
    return closest < SAFE_DISTANCE_KM

def _compute_slot_correction(sat):
    """
    Compute delta-v needed to return satellite toward nominal slot.
    Uses relative position in ECI to determine correction direction.
    Caps at 5 m/s (0.005 km/s) and skips if already in box.
    """
    slot_offset = _arr(sat.nominal_r) - _arr(sat.r)
    dist = float(np.linalg.norm(slot_offset))
    if dist < 0.1:          # already within 100m of slot — no burn needed
        return None
    # Scale magnitude with distance, max 0.005 km/s (5 m/s)
    dv_mag = min(0.005, dist * 0.0001)
    dv_dir = slot_offset / dist
    return dv_dir * dv_mag

def _schedule_recovery_when_clear(sat_id, debris_id,
                                  dv_evasion_eci, current_time,
                                  evasion_burn_id):
    sat = satellites.get(sat_id)
    if sat is None:
        return

    recovery_burn_id = f"RECOVERY_{sat_id}_{int(current_time)}"
    execute_at       = current_time + THRUSTER_COOLDOWN + 60.0

    # Prefer a slot-targeted correction over a blind reverse burn
    slot_dv = _compute_slot_correction(sat)
    if slot_dv is not None:
        recovery_dv = slot_dv
    else:
        # Satellite is already near its slot — use small reverse burn as fallback
        recovery_dv = -dv_evasion_eci * (RECOVERY_DV_KMS / EVASION_DV_KMS)

    sat.scheduled_burns.append({
        "burn_id":          recovery_burn_id,
        "execute_at":       execute_at,
        "delta_v":          recovery_dv,
        "type":             "RECOVERY",
        "threat_debris_id": debris_id,
        "min_clear_time":   execute_at,
    })

    dv_dict = {"x": float(recovery_dv[0]),
               "y": float(recovery_dv[1]),
               "z": float(recovery_dv[2])}

    log_recovery_scheduled(
        sat_id=sat_id, burn_id=recovery_burn_id,
        scheduled_sim_time=execute_at, delta_v_kms=dv_dict,
        evasion_burn_id=evasion_burn_id,
    )
    log_maneuver_planned(
        sat_id=sat_id, burn_id=recovery_burn_id,
        burn_sim_time=execute_at, delta_v_kms=dv_dict,
        fuel_before_kg=sat.fuel,
        fuel_after_kg=sat.fuel - fuel_consumed(sat.mass, float(np.linalg.norm(recovery_dv))),
        maneuver_type="RECOVERY",
    )

# ── Main planner ──────────────────────────────────────────────────────────────

def plan_maneuver(sat_id: str, debris_id: str, current_time: float):
    """
    Plan evasion + recovery for sat_id avoiding debris_id.
    Called from simulate.py for every CRITICAL conjunction.

    Bug 5 fix: use cooldown_remaining_at(sim_time) not cooldown_remaining(t).
    Bug 6 fix: all sat.r/v wrapped with _arr() before math.
    Bug 7 fix: use sat.is_eol (the property that actually exists on disk).
    """
    sat = satellites.get(sat_id)
    deb = debris.get(debris_id)

    if sat is None or deb is None:
        return None

    # Bug 5 fix: cooldown_remaining_at() is the method with sim_time argument.
    # sat.cooldown_remaining is a property that always returns 0.0 — DO NOT call it.
    cooldown_left = sat.cooldown_remaining_at(current_time)
    if cooldown_left > 0:
        log_maneuver_planned(
            sat_id=sat_id,
            burn_id=f"REJECTED_COOLDOWN_{sat_id}_{int(current_time)}",
            burn_sim_time=current_time,
            delta_v_kms={"x": 0.0, "y": 0.0, "z": 0.0},
            fuel_before_kg=sat.fuel, fuel_after_kg=sat.fuel,
            maneuver_type="EVASION",
        )
        return {"satellite": sat_id, "status": "COOLDOWN",
                "cooldown_remaining_s": round(cooldown_left, 1)}

    # Bug 7 fix: sat.is_eol is the property on disk (same as is_critical_fuel)
    if sat.is_eol:
        log_eol_triggered(sat_id=sat_id, fuel_remaining_kg=sat.fuel,
                          fuel_fraction=sat.fuel_fraction, sim_time=current_time)
        return _plan_graveyard(sat_id, current_time)

    fuel_evasion  = fuel_consumed(sat.mass, EVASION_DV_KMS)
    fuel_recovery = fuel_consumed(sat.mass - fuel_evasion, RECOVERY_DV_KMS)

    if sat.fuel < (fuel_evasion + fuel_recovery):
        log_maneuver_planned(
            sat_id=sat_id,
            burn_id=f"REJECTED_FUEL_{sat_id}_{int(current_time)}",
            burn_sim_time=current_time,
            delta_v_kms={"x": 0.0, "y": 0.0, "z": 0.0},
            fuel_before_kg=sat.fuel, fuel_after_kg=sat.fuel,
            maneuver_type="EVASION",
        )
        return {"satellite": sat_id, "status": "INSUFFICIENT_FUEL",
                "fuel_remaining_kg": round(sat.fuel, 4)}

    # Bug 6 fix: _arr() converts sat.r/v from list → numpy before RTN math
    dv_evasion_eci, (rel_R, rel_T, rel_N) = compute_evasion_dv(
        sat.r, sat.v, deb.r, deb.v, EVASION_DV_KMS
    )

    abs_R, abs_T, abs_N = abs(rel_R), abs(rel_T), abs(rel_N)
    dominant_axis = ("R" if abs_R >= max(abs_T, abs_N)
                     else "T" if abs_T >= abs_N else "N")

    evasion_burn_id = f"EVASION_{sat_id}_{int(current_time)}"
    dv_dict = {"x": float(dv_evasion_eci[0]),
               "y": float(dv_evasion_eci[1]),
               "z": float(dv_evasion_eci[2])}

    log_maneuver_planned(
        sat_id=sat_id, burn_id=evasion_burn_id,
        burn_sim_time=current_time + SIGNAL_LATENCY_S,
        delta_v_kms=dv_dict, fuel_before_kg=sat.fuel,
        fuel_after_kg=sat.fuel - fuel_evasion, maneuver_type="EVASION",
    )

    # Apply evasion — store back as list to keep satellite.py contract
    sat.v = list(_arr(sat.v) + dv_evasion_eci)
    sat.fuel          -= fuel_evasion
    sat.last_burn_time = current_time
    sat.status         = "EVADING"

    log_maneuver_executed(
        sat_id=sat_id, burn_id=evasion_burn_id, delta_v_kms=dv_dict,
        fuel_remaining_kg=sat.fuel, sim_time=current_time, success=True,
    )

    if sat.is_eol:
        log_eol_triggered(sat_id=sat_id, fuel_remaining_kg=sat.fuel,
                          fuel_fraction=sat.fuel_fraction, sim_time=current_time)

    _schedule_recovery_when_clear(
        sat_id, debris_id, dv_evasion_eci, current_time, evasion_burn_id
    )

    return {
        "satellite": sat_id, "status": "MANEUVER_PLANNED",
        "evasion": {
            "burn_id": evasion_burn_id,
            "delta_v_eci_kms": dv_evasion_eci.tolist(),
            "magnitude_ms": round(EVASION_DV_KMS * 1000, 2),
            "fuel_used_kg": round(fuel_evasion, 4),
            "approach_geometry": {
                "rel_R_km": round(rel_R, 4), "rel_T_km": round(rel_T, 4),
                "rel_N_km": round(rel_N, 4), "dominant_axis": dominant_axis,
            },
        },
        "recovery": {
            "status": "PENDING — fires when threat clears",
            "check_interval_s": RECOVERY_CHECK_INTERVAL_S,
            "fuel_budgeted_kg": round(fuel_recovery, 4),
        },
        "fuel_remaining_kg": round(sat.fuel, 4),
    }


# ── Execute scheduled burns ───────────────────────────────────────────────────

def execute_scheduled_burns(current_time: float):
    """
    Fire all burns due this tick.
    Bug 5 fix: cooldown_remaining_at() in both places.
    Bug 6 fix: _arr() wraps all vector operations.
    """
    executed = []

    for sat in satellites.values():
        due       = [b for b in sat.scheduled_burns if b["execute_at"] <= current_time]
        remaining = [b for b in sat.scheduled_burns if b["execute_at"] > current_time]

        for burn in due:
            burn_id   = burn["burn_id"]
            burn_type = burn.get("type", "RECOVERY")
            dv_vec    = _arr(burn["delta_v"])   # Bug 6: always numpy
            dv_dict   = {"x": float(dv_vec[0]),
                         "y": float(dv_vec[1]),
                         "z": float(dv_vec[2])}

            # Bug 5 fix: use the method, not the property
            if sat.cooldown_remaining_at(current_time) > 0:
                remaining.append(burn)
                continue

            if burn_type == "RECOVERY":
                threat_id = burn.get("threat_debris_id")
                if threat_id and _threat_still_active(sat.id, threat_id):
                    burn["execute_at"] = current_time + RECOVERY_CHECK_INTERVAL_S
                    remaining.append(burn)
                    log_maneuver_executed(
                        sat_id=sat.id, burn_id=burn_id, delta_v_kms=dv_dict,
                        fuel_remaining_kg=sat.fuel, sim_time=current_time,
                        success=False, reason="THREAT_STILL_ACTIVE — retry 5 min",
                    )
                    executed.append({"satellite": sat.id, "burn_id": burn_id,
                                     "type": "RECOVERY_DELAYED",
                                     "status": "THREAT_STILL_ACTIVE"})
                    continue

            dv_mag      = float(np.linalg.norm(dv_vec))
            fuel_needed = fuel_consumed(sat.mass, dv_mag)

            if sat.fuel < fuel_needed:
                log_maneuver_executed(
                    sat_id=sat.id, burn_id=burn_id, delta_v_kms=dv_dict,
                    fuel_remaining_kg=sat.fuel, sim_time=current_time,
                    success=False, reason="INSUFFICIENT_FUEL",
                )
                executed.append({"satellite": sat.id, "burn_id": burn_id,
                                 "status": "SKIPPED_NO_FUEL"})
                continue

            # Apply burn — store back as list
            sat.v = list(_arr(sat.v) + dv_vec)
            sat.fuel          -= fuel_needed
            sat.last_burn_time = current_time

            log_maneuver_executed(
                sat_id=sat.id, burn_id=burn_id, delta_v_kms=dv_dict,
                fuel_remaining_kg=sat.fuel, sim_time=current_time, success=True,
            )

            if burn_type == "RECOVERY":
                dist_to_slot = sat.distance_to_slot()
                in_box       = sat.in_station_keeping_box()
                sat.status   = "NOMINAL" if in_box else "RECOVERING"
                log_recovery_executed(
                    sat_id=sat.id, burn_id=burn_id, sim_time=current_time,
                    distance_to_slot_km=dist_to_slot,
                    fuel_remaining_kg=sat.fuel, in_box=in_box,
                )
                executed.append({
                    "satellite": sat.id, "burn_id": burn_id, "type": "RECOVERY",
                    "status": "EXECUTED", "fuel_remaining_kg": round(sat.fuel, 4),
                    "distance_to_slot_km": round(dist_to_slot, 4),
                    "in_station_box": in_box,
                })
            elif burn_type == "GRAVEYARD":
                sat.status = "EOL"
                log_graveyard_executed(sat_id=sat.id, sim_time=current_time,
                                       fuel_remaining_kg=sat.fuel)
                executed.append({
                    "satellite": sat.id, "burn_id": burn_id,
                    "type": "GRAVEYARD", "status": "EXECUTED",
                    "fuel_remaining_kg": round(sat.fuel, 4),
                })
            else:
                executed.append({
                    "satellite": sat.id, "burn_id": burn_id,
                    "type": burn_type, "status": "EXECUTED",
                    "fuel_remaining_kg": round(sat.fuel, 4),
                })

        sat.scheduled_burns = remaining

    return executed


# ── Graveyard ─────────────────────────────────────────────────────────────────

def _plan_graveyard(sat_id: str, current_time: float):
    """Prograde burn to raise apogee into graveyard orbit (Bug fix: was retrograde)."""
    sat  = satellites[sat_id]
    v_np = _arr(sat.v)
    dv   = (v_np / np.linalg.norm(v_np)) * GRAVEYARD_DV_KMS  # prograde

    fuel_needed       = fuel_consumed(sat.mass, GRAVEYARD_DV_KMS)
    graveyard_burn_id = f"GRAVEYARD_{sat_id}_{int(current_time)}"
    dv_dict           = {"x": float(dv[0]), "y": float(dv[1]), "z": float(dv[2])}

    if sat.fuel < fuel_needed:
        sat.status = "EOL_NO_FUEL"
        log_maneuver_executed(
            sat_id=sat_id, burn_id=graveyard_burn_id, delta_v_kms=dv_dict,
            fuel_remaining_kg=sat.fuel, sim_time=current_time,
            success=False, reason="INSUFFICIENT_FUEL_FOR_GRAVEYARD",
        )
        return {"satellite": sat_id, "status": "EOL_NO_FUEL",
                "message": "Insufficient fuel — satellite is uncontrolled debris"}

    log_maneuver_planned(
        sat_id=sat_id, burn_id=graveyard_burn_id,
        burn_sim_time=current_time + SIGNAL_LATENCY_S,
        delta_v_kms=dv_dict, fuel_before_kg=sat.fuel,
        fuel_after_kg=sat.fuel - fuel_needed, maneuver_type="GRAVEYARD",
    )

    sat.v = list(v_np + dv)        # prograde += raises apogee
    sat.fuel          -= fuel_needed
    sat.last_burn_time = current_time
    sat.status         = "EOL"

    log_graveyard_executed(sat_id=sat_id, sim_time=current_time,
                           fuel_remaining_kg=sat.fuel)
    log_maneuver_executed(
        sat_id=sat_id, burn_id=graveyard_burn_id, delta_v_kms=dv_dict,
        fuel_remaining_kg=sat.fuel, sim_time=current_time, success=True,
    )

    return {"satellite": sat_id, "status": "GRAVEYARD_BURN",
            "burn_id": graveyard_burn_id, "delta_v_eci_kms": dv.tolist(),
            "fuel_remaining_kg": round(sat.fuel, 4)}