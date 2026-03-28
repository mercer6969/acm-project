"""
maneuver/planner.py
───────────────────
Issue 4 fix : Evasion direction computed from actual approach geometry at TCA.
              Burns in the direction that maximises miss distance — not a fixed
              transverse direction that can make collisions worse.

Issue 5 fix : Recovery burn only fires after post-evasion conjunction check
              confirms the threat has cleared.  T+660s hardcode removed.

Issue 6 fix : Every decision point emits a structured JSON log event via
              app.logger (ring-buffer + acm_events.log on disk).

Issue 7 fix : After recovery executes, distance_to_slot is measured against
              the nominal slot that is propagated by the same RK4+J2 integrator
              as the real position (propagate_nominal() is called in simulate.py
              every tick — this file reads the result via sat.distance_to_slot()).

Bug fix     : _plan_graveyard was using sat.v -= dv (retrograde = lowers orbit).
              Graveyard requires prograde (+=) to raise apogee. Fixed.
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
from app.maneuver.fuel_model import (
    MAX_DELTA_V_KMS,
    THRUSTER_COOLDOWN,
    fuel_consumed,
)

# ── maneuver constants ────────────────────────────────────────────────────────
EVASION_DV_KMS            = 0.010   # 10 m/s evasion burn
RECOVERY_DV_KMS           = 0.010   # 10 m/s recovery burn
GRAVEYARD_DV_KMS          = 0.012   # 12 m/s prograde graveyard raise
SAFE_DISTANCE_KM          = 0.5     # debris must be this far before recovery fires
RECOVERY_CHECK_INTERVAL_S = 300.0   # re-check conjunction every 5 min
SIGNAL_LATENCY_S          = 10.0    # minimum scheduling lead time (spec §5.4)


# ── RTN frame helpers ─────────────────────────────────────────────────────────

def compute_rtn_axes(r, v):
    """
    Compute RTN (Radial-Transverse-Normal) unit vectors for a satellite
    at ECI position r and velocity v (km and km/s).

    R — radial    : outward from Earth centre through satellite
    T — transverse: direction of motion (prograde)
    N — normal    : perpendicular to orbital plane (R × T)
    """
    r_hat = r / np.linalg.norm(r)
    v_hat = v / np.linalg.norm(v)
    n_hat = np.cross(r_hat, v_hat)
    n_hat = n_hat / np.linalg.norm(n_hat)
    t_hat = np.cross(n_hat, r_hat)
    return r_hat, t_hat, n_hat


def rtn_to_eci(dv_rtn, r_hat, t_hat, n_hat):
    """Convert a delta-v vector from RTN frame to ECI frame."""
    return dv_rtn[0] * r_hat + dv_rtn[1] * t_hat + dv_rtn[2] * n_hat


# ── Issue 4: Geometry-aware evasion direction ─────────────────────────────────

def compute_evasion_dv(sat_r, sat_v, deb_r, deb_v,
                       magnitude_kms=EVASION_DV_KMS):
    """
    Compute the evasion delta-v in ECI that maximises miss distance.

    Strategy (priority order):
    ───────────────────────────
    1. Find relative position at TCA via linear approximation.
    2. Decompose into RTN components to classify approach direction.
    3. Choose burn axis:

       Debris approaches mostly TRANSVERSELY (head-on / tail-on)
         -> burn RADIAL: shifts orbital altitude, changes crossing
            time so the paths no longer intersect at the same moment.

       Debris approaches mostly RADIALLY (from above / below)
         -> burn TRANSVERSE: most fuel-efficient phase shift out of
            the debris path.

       Debris approaches mostly NORMALLY (out-of-plane)
         -> burn TRANSVERSE: avoids expensive normal/plane-change burns.

    4. Sign chosen to push satellite AWAY from debris at TCA.

    Returns
    -------
    dv_eci         : np.ndarray (3,) — delta-v in ECI km/s
    rel_components : tuple (rel_R, rel_T, rel_N) at TCA in km
    """
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
        # Transverse approach -> radial burn
        burn_axis = r_hat
        burn_sign = 1.0 if rel_R >= 0 else -1.0
    elif abs_R >= abs_T and abs_R >= abs_N:
        # Radial approach -> transverse burn
        burn_axis = t_hat
        burn_sign = 1.0 if rel_T >= 0 else -1.0
    else:
        # Normal approach -> transverse burn (avoid plane-change cost)
        burn_axis = t_hat
        burn_sign = 1.0 if rel_T >= 0 else -1.0

    dv_eci = burn_axis * burn_sign * magnitude_kms
    return dv_eci, (rel_R, rel_T, rel_N)


# ── Issue 5: TCA-aware recovery ───────────────────────────────────────────────

def _threat_still_active(sat_id, debris_id):
    """
    Return True if debris is still within SAFE_DISTANCE_KM of the satellite.
    Used to gate recovery burn execution.
    """
    sat = satellites.get(sat_id)
    deb = debris.get(debris_id)
    if sat is None or deb is None:
        return False

    rel_r = sat.r - deb.r
    rel_v = sat.v - deb.v
    v_sq  = float(np.dot(rel_v, rel_v))

    if v_sq > 1e-12:
        t_ca    = max(0.0, -float(np.dot(rel_r, rel_v)) / v_sq)
        closest = float(np.linalg.norm(rel_r + rel_v * t_ca))
    else:
        closest = float(np.linalg.norm(rel_r))

    return closest < SAFE_DISTANCE_KM


def _schedule_recovery_when_clear(sat_id, debris_id,
                                  dv_evasion_eci, current_time,
                                  evasion_burn_id):
    """
    Queue a recovery burn that fires only when:
      - Threat debris has cleared (> SAFE_DISTANCE_KM), AND
      - Thruster cooldown has expired.
    No hardcoded T+660s.

    Issue 6: logs scheduling immediately.
    """
    sat = satellites.get(sat_id)
    if sat is None:
        return

    recovery_burn_id = f"RECOVERY_{sat_id}_{int(current_time)}"
    execute_at       = current_time + THRUSTER_COOLDOWN + 60.0
    recovery_dv      = -dv_evasion_eci * (RECOVERY_DV_KMS / EVASION_DV_KMS)

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

    # Issue 6: log recovery scheduled + planned
    log_recovery_scheduled(
        sat_id=sat_id,
        burn_id=recovery_burn_id,
        scheduled_sim_time=execute_at,
        delta_v_kms=dv_dict,
        evasion_burn_id=evasion_burn_id,
    )
    log_maneuver_planned(
        sat_id=sat_id,
        burn_id=recovery_burn_id,
        burn_sim_time=execute_at,
        delta_v_kms=dv_dict,
        fuel_before_kg=sat.fuel,
        fuel_after_kg=sat.fuel - fuel_consumed(sat.mass, RECOVERY_DV_KMS),
        maneuver_type="RECOVERY",
    )


# ── Main planner ───────────────────────────────────────────────────────────────

def plan_maneuver(sat_id: str, debris_id: str, current_time: float):
    """
    Plan an evasion + recovery maneuver pair for sat_id avoiding debris_id.

    Issue 6: all decisions logged (cooldown/fuel rejection, planned,
             applied, EOL trigger).
    Issue 7: nominal slot not touched here — propagate_nominal() in
             simulate.py keeps it current. distance_to_slot() reads it.

    Returns a result dict, or None if sat/debris not found.
    """
    sat = satellites.get(sat_id)
    deb = debris.get(debris_id)

    if sat is None or deb is None:
        return None

    # ── Cooldown check ─────────────────────────────────────────────────────────
    cooldown_left = sat.cooldown_remaining(current_time)
    if cooldown_left > 0:
        log_maneuver_planned(
            sat_id=sat_id,
            burn_id=f"REJECTED_COOLDOWN_{sat_id}_{int(current_time)}",
            burn_sim_time=current_time,
            delta_v_kms={"x": 0.0, "y": 0.0, "z": 0.0},
            fuel_before_kg=sat.fuel,
            fuel_after_kg=sat.fuel,
            maneuver_type="EVASION",
        )
        return {
            "satellite": sat_id,
            "status": "COOLDOWN",
            "cooldown_remaining_s": round(cooldown_left, 1),
        }

    # ── EOL check ──────────────────────────────────────────────────────────────
    if sat.is_critical_fuel:
        log_eol_triggered(
            sat_id=sat_id,
            fuel_remaining_kg=sat.fuel,
            fuel_fraction=sat.fuel_fraction,
            sim_time=current_time,
        )
        return _plan_graveyard(sat_id, current_time)

    # ── Fuel pre-check ─────────────────────────────────────────────────────────
    fuel_evasion  = fuel_consumed(sat.mass, EVASION_DV_KMS)
    fuel_recovery = fuel_consumed(sat.mass - fuel_evasion, RECOVERY_DV_KMS)

    if sat.fuel < (fuel_evasion + fuel_recovery):
        log_maneuver_planned(
            sat_id=sat_id,
            burn_id=f"REJECTED_FUEL_{sat_id}_{int(current_time)}",
            burn_sim_time=current_time,
            delta_v_kms={"x": 0.0, "y": 0.0, "z": 0.0},
            fuel_before_kg=sat.fuel,
            fuel_after_kg=sat.fuel,
            maneuver_type="EVASION",
        )
        return {
            "satellite": sat_id,
            "status": "INSUFFICIENT_FUEL",
            "fuel_remaining_kg": round(sat.fuel, 4),
        }

    # ── Issue 4: geometry-aware evasion ΔV ────────────────────────────────────
    dv_evasion_eci, (rel_R, rel_T, rel_N) = compute_evasion_dv(
        sat.r.copy(), sat.v.copy(),
        deb.r.copy(), deb.v.copy(),
        EVASION_DV_KMS,
    )

    abs_R, abs_T, abs_N = abs(rel_R), abs(rel_T), abs(rel_N)
    dominant_axis = ("R" if abs_R >= max(abs_T, abs_N)
                     else "T" if abs_T >= abs_N else "N")

    evasion_burn_id = f"EVASION_{sat_id}_{int(current_time)}"
    dv_dict = {"x": float(dv_evasion_eci[0]),
               "y": float(dv_evasion_eci[1]),
               "z": float(dv_evasion_eci[2])}

    # Issue 6: log planned evasion (before applying)
    log_maneuver_planned(
        sat_id=sat_id,
        burn_id=evasion_burn_id,
        burn_sim_time=current_time + SIGNAL_LATENCY_S,
        delta_v_kms=dv_dict,
        fuel_before_kg=sat.fuel,
        fuel_after_kg=sat.fuel - fuel_evasion,
        maneuver_type="EVASION",
    )

    # ── Apply evasion burn ─────────────────────────────────────────────────────
    sat.v          = sat.v + dv_evasion_eci
    sat.fuel      -= fuel_evasion
    sat.last_burn_time = current_time
    sat.status     = "EVADING"

    # Issue 6: log executed evasion
    log_maneuver_executed(
        sat_id=sat_id,
        burn_id=evasion_burn_id,
        delta_v_kms=dv_dict,
        fuel_remaining_kg=sat.fuel,
        sim_time=current_time,
        success=True,
    )

    # Re-check EOL after burn
    if sat.is_critical_fuel:
        log_eol_triggered(
            sat_id=sat_id,
            fuel_remaining_kg=sat.fuel,
            fuel_fraction=sat.fuel_fraction,
            sim_time=current_time,
        )

    # Issue 5: TCA-aware recovery (also logs via Issue 6 inside helper)
    _schedule_recovery_when_clear(
        sat_id, debris_id, dv_evasion_eci,
        current_time, evasion_burn_id,
    )

    return {
        "satellite": sat_id,
        "status": "MANEUVER_PLANNED",
        "evasion": {
            "burn_id":         evasion_burn_id,
            "delta_v_eci_kms": dv_evasion_eci.tolist(),
            "magnitude_ms":    round(EVASION_DV_KMS * 1000, 2),
            "fuel_used_kg":    round(fuel_evasion, 4),
            "approach_geometry": {
                "rel_R_km":      round(rel_R, 4),
                "rel_T_km":      round(rel_T, 4),
                "rel_N_km":      round(rel_N, 4),
                "dominant_axis": dominant_axis,
            },
        },
        "recovery": {
            "status":           "PENDING — fires when threat clears",
            "check_interval_s": RECOVERY_CHECK_INTERVAL_S,
            "fuel_budgeted_kg": round(fuel_recovery, 4),
        },
        "fuel_remaining_kg": round(sat.fuel, 4),
    }


# ── Execute scheduled burns ────────────────────────────────────────────────────

def execute_scheduled_burns(current_time: float):
    """
    Execute any scheduled burns due this simulation tick.

    Issue 5 : Recovery burns check threat has cleared before firing.
              Delayed burns re-queue at current + RECOVERY_CHECK_INTERVAL_S.

    Issue 6 : Every outcome (success / delay / skip) is logged.

    Issue 7 : After a successful recovery, distance_to_slot() is evaluated
              against the RK4+J2 nominal slot (propagated in simulate.py).
              Result goes into log_recovery_executed().
    """
    executed = []

    for sat in satellites.values():
        due       = [b for b in sat.scheduled_burns
                     if b["execute_at"] <= current_time]
        remaining = [b for b in sat.scheduled_burns
                     if b["execute_at"] > current_time]

        for burn in due:
            burn_id   = burn["burn_id"]
            burn_type = burn.get("type", "RECOVERY")
            dv_vec    = burn["delta_v"]
            dv_dict   = {"x": float(dv_vec[0]),
                         "y": float(dv_vec[1]),
                         "z": float(dv_vec[2])}

            # ── Cooldown check ─────────────────────────────────────────────────
            if sat.cooldown_remaining(current_time) > 0:
                remaining.append(burn)
                continue

            # ── Issue 5: Recovery — verify threat cleared ──────────────────────
            if burn_type == "RECOVERY":
                threat_id = burn.get("threat_debris_id")
                if threat_id and _threat_still_active(sat.id, threat_id):
                    burn["execute_at"] = (current_time
                                          + RECOVERY_CHECK_INTERVAL_S)
                    remaining.append(burn)
                    log_maneuver_executed(
                        sat_id=sat.id,
                        burn_id=burn_id,
                        delta_v_kms=dv_dict,
                        fuel_remaining_kg=sat.fuel,
                        sim_time=current_time,
                        success=False,
                        reason="THREAT_STILL_ACTIVE — retrying in 5 min",
                    )
                    executed.append({
                        "satellite": sat.id,
                        "burn_id":   burn_id,
                        "type":      "RECOVERY_DELAYED",
                        "status":    "THREAT_STILL_ACTIVE",
                        "retry_at":  burn["execute_at"],
                    })
                    continue

            # ── Fuel check ─────────────────────────────────────────────────────
            dv_mag      = float(np.linalg.norm(dv_vec))
            fuel_needed = fuel_consumed(sat.mass, dv_mag)

            if sat.fuel < fuel_needed:
                log_maneuver_executed(
                    sat_id=sat.id,
                    burn_id=burn_id,
                    delta_v_kms=dv_dict,
                    fuel_remaining_kg=sat.fuel,
                    sim_time=current_time,
                    success=False,
                    reason="INSUFFICIENT_FUEL",
                )
                executed.append({
                    "satellite": sat.id,
                    "burn_id":   burn_id,
                    "status":    "SKIPPED_NO_FUEL",
                })
                continue

            # ── Apply burn ─────────────────────────────────────────────────────
            sat.v          = sat.v + dv_vec
            sat.fuel      -= fuel_needed
            sat.last_burn_time = current_time

            log_maneuver_executed(
                sat_id=sat.id,
                burn_id=burn_id,
                delta_v_kms=dv_dict,
                fuel_remaining_kg=sat.fuel,
                sim_time=current_time,
                success=True,
            )

            if burn_type == "RECOVERY":
                # Issue 7: read distance from RK4+J2 nominal slot
                dist_to_slot = sat.distance_to_slot()
                in_box       = sat.in_station_keeping_box()
                sat.status   = "NOMINAL" if in_box else "RECOVERING"

                log_recovery_executed(
                    sat_id=sat.id,
                    burn_id=burn_id,
                    sim_time=current_time,
                    distance_to_slot_km=dist_to_slot,
                    fuel_remaining_kg=sat.fuel,
                    in_box=in_box,
                )
                executed.append({
                    "satellite":           sat.id,
                    "burn_id":             burn_id,
                    "type":                "RECOVERY",
                    "status":              "EXECUTED",
                    "fuel_remaining_kg":   round(sat.fuel, 4),
                    "distance_to_slot_km": round(dist_to_slot, 4),
                    "in_station_box":      in_box,
                })

            elif burn_type == "GRAVEYARD":
                sat.status = "EOL"
                log_graveyard_executed(
                    sat_id=sat.id,
                    sim_time=current_time,
                    fuel_remaining_kg=sat.fuel,
                )
                executed.append({
                    "satellite":         sat.id,
                    "burn_id":           burn_id,
                    "type":              "GRAVEYARD",
                    "status":            "EXECUTED",
                    "fuel_remaining_kg": round(sat.fuel, 4),
                })

            else:
                executed.append({
                    "satellite":         sat.id,
                    "burn_id":           burn_id,
                    "type":              burn_type,
                    "status":            "EXECUTED",
                    "fuel_remaining_kg": round(sat.fuel, 4),
                })

        sat.scheduled_burns = remaining

    return executed


# ── Graveyard helper ───────────────────────────────────────────────────────────

def _plan_graveyard(sat_id: str, current_time: float):
    """
    When fuel is critical (<5%), raise the satellite into a graveyard orbit
    with a PROGRADE burn to increase apogee above the LEO operational belt.

    Bug fix: original code used sat.v -= dv (retrograde = lowers orbit).
    Graveyard requires prograde (sat.v += dv) to raise apogee.
    """
    sat = satellites[sat_id]

    t_hat = sat.v / np.linalg.norm(sat.v)   # prograde unit vector
    dv    = t_hat * GRAVEYARD_DV_KMS

    fuel_needed       = fuel_consumed(sat.mass, GRAVEYARD_DV_KMS)
    graveyard_burn_id = f"GRAVEYARD_{sat_id}_{int(current_time)}"
    dv_dict           = {"x": float(dv[0]),
                         "y": float(dv[1]),
                         "z": float(dv[2])}

    if sat.fuel < fuel_needed:
        sat.status = "EOL_NO_FUEL"
        log_maneuver_executed(
            sat_id=sat_id,
            burn_id=graveyard_burn_id,
            delta_v_kms=dv_dict,
            fuel_remaining_kg=sat.fuel,
            sim_time=current_time,
            success=False,
            reason="INSUFFICIENT_FUEL_FOR_GRAVEYARD — satellite uncontrolled",
        )
        return {
            "satellite": sat_id,
            "status":    "EOL_NO_FUEL",
            "message":   "Insufficient fuel for graveyard — satellite is uncontrolled debris",
        }

    # Issue 6: log planned graveyard
    log_maneuver_planned(
        sat_id=sat_id,
        burn_id=graveyard_burn_id,
        burn_sim_time=current_time + SIGNAL_LATENCY_S,
        delta_v_kms=dv_dict,
        fuel_before_kg=sat.fuel,
        fuel_after_kg=sat.fuel - fuel_needed,
        maneuver_type="GRAVEYARD",
    )

    # Apply prograde graveyard burn (raises apogee)
    sat.v          = sat.v + dv
    sat.fuel      -= fuel_needed
    sat.last_burn_time = current_time
    sat.status     = "EOL"

    # Issue 6: log executed graveyard
    log_graveyard_executed(
        sat_id=sat_id,
        sim_time=current_time,
        fuel_remaining_kg=sat.fuel,
    )
    log_maneuver_executed(
        sat_id=sat_id,
        burn_id=graveyard_burn_id,
        delta_v_kms=dv_dict,
        fuel_remaining_kg=sat.fuel,
        sim_time=current_time,
        success=True,
    )

    return {
        "satellite":         sat_id,
        "status":            "GRAVEYARD_BURN",
        "burn_id":           graveyard_burn_id,
        "delta_v_eci_kms":   dv.tolist(),
        "fuel_remaining_kg": round(sat.fuel, 4),
    }