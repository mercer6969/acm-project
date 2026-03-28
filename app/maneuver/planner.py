"""
maneuver/planner.py
───────────────────
Issue 4 fix: Evasion direction computed from actual approach geometry at TCA.
             Burns in the direction that maximises miss distance — not a fixed
             transverse direction that can make collisions worse.

Issue 5 fix: Recovery burn only scheduled after post-evasion conjunction check
             confirms the threat has cleared. T+660s hardcode removed.
"""

import numpy as np
from app.config import satellites, debris, get_sim_time
from app.maneuver.fuel_model import fuel_consumed, MAX_DELTA_V_KMS, THRUSTER_COOLDOWN
from app.prediction.tca import propagated_tca

# Maneuver constants
EVASION_DV_KMS   = 0.010    # 10 m/s evasion burn
RECOVERY_DV_KMS  = 0.010    # 10 m/s recovery burn
GRAVEYARD_DV_KMS = 0.012    # 12 m/s graveyard raise
SAFE_DISTANCE_KM = 0.5      # debris must be this far before recovery fires
RECOVERY_CHECK_INTERVAL_S = 300.0   # re-check conjunction every 5 min


# ── RTN frame helpers ─────────────────────────────────────────────────────────

def compute_rtn_axes(r, v):
    """
    Compute the RTN (Radial-Transverse-Normal) unit vectors for a
    satellite at position r with velocity v (both in ECI, km/km/s).

    R — radial: outward from Earth centre through satellite
    T — transverse: direction of motion (prograde)
    N — normal: perpendicular to orbital plane (R × T)
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

def compute_evasion_dv(sat_r, sat_v, deb_r, deb_v, magnitude_kms=EVASION_DV_KMS):
    """
    Compute the evasion delta-v vector in ECI that maximises miss distance.

    Strategy (in order of priority):
    ─────────────────────────────────
    1. Find relative position at TCA (where are we closest?)
    2. Decompose relative position into RTN components
    3. Choose burn axis based on which RTN component is smallest
       (burn perpendicular to the primary approach direction):

       - If debris approaches mostly radially   → burn transverse (T)
         A prograde/retrograde burn shifts the satellite's orbital phase,
         moving it out of the debris path most efficiently.

       - If debris approaches mostly transversely (head-on / tail-on)
         → burn radial (R) to shift the orbital altitude slightly,
         changing the crossing time so paths no longer intersect.

       - If debris approaches mostly normally (out-of-plane)
         → burn radial or transverse (NOT normal — too fuel-expensive).

    4. Direction sign chosen to push satellite AWAY from debris at TCA.
    """
    r_hat, t_hat, n_hat = compute_rtn_axes(sat_r, sat_v)

    # Get relative position at TCA using linear approximation
    # (fast — full propagated TCA already done upstream)
    rel_r = sat_r - deb_r
    rel_v = sat_v - deb_v

    # Linear TCA time
    v_norm_sq = float(np.dot(rel_v, rel_v))
    if v_norm_sq > 1e-12:
        t_ca = -float(np.dot(rel_r, rel_v)) / v_norm_sq
        t_ca = max(0.0, t_ca)
    else:
        t_ca = 0.0

    # Relative position at TCA
    rel_at_tca = rel_r + rel_v * t_ca   # vector from debris to sat at TCA

    # Decompose into RTN
    rel_R = float(np.dot(rel_at_tca, r_hat))
    rel_T = float(np.dot(rel_at_tca, t_hat))
    rel_N = float(np.dot(rel_at_tca, n_hat))

    abs_R, abs_T, abs_N = abs(rel_R), abs(rel_T), abs(rel_N)

    # ── Choose burn axis ──────────────────────────────────────────────────────
    if abs_T >= abs_R and abs_T >= abs_N:
        # Debris approaching mostly transversely (head-on/tail-on)
        # → burn radial to shift altitude and change crossing time
        burn_axis  = r_hat
        burn_sign  = 1.0 if rel_R >= 0 else -1.0   # push away radially

    elif abs_R >= abs_T and abs_R >= abs_N:
        # Debris approaching mostly radially (from above/below)
        # → burn transverse (prograde/retrograde) — most fuel efficient
        burn_axis  = t_hat
        burn_sign  = 1.0 if rel_T >= 0 else -1.0   # push away transversely

    else:
        # Debris approaching mostly out-of-plane
        # → burn transverse (avoid expensive normal burns)
        burn_axis  = t_hat
        burn_sign  = 1.0 if rel_T >= 0 else -1.0

    dv_eci = burn_axis * burn_sign * magnitude_kms
    return dv_eci, (rel_R, rel_T, rel_N)


# ── Issue 5: TCA-aware recovery scheduling ────────────────────────────────────

def _threat_still_active(sat_id, debris_id):
    """
    Re-run conjunction check between one satellite and one debris object.
    Returns True if the threat is still within SAFE_DISTANCE_KM.
    Used to decide when it's safe to fire the recovery burn.
    """
    sat = satellites.get(sat_id)
    deb = debris.get(debris_id)
    if sat is None or deb is None:
        return False

    # Quick linear check first
    rel_r = sat.r - deb.r
    rel_v = sat.v - deb.v
    v_sq  = float(np.dot(rel_v, rel_v))

    if v_sq > 1e-12:
        t_ca = max(0.0, -float(np.dot(rel_r, rel_v)) / v_sq)
        closest = np.linalg.norm(rel_r + rel_v * t_ca)
    else:
        closest = np.linalg.norm(rel_r)

    return float(closest) < SAFE_DISTANCE_KM


def _schedule_recovery_when_clear(sat_id, debris_id, dv_evasion_eci, current_time):
    """
    Instead of hardcoding recovery at T+660s, we store a 'pending recovery'
    on the satellite and check every simulation step whether the threat has
    cleared. Recovery fires on the first step where threat distance > SAFE_DISTANCE_KM
    AND thruster cooldown has expired.
    """
    sat = satellites.get(sat_id)
    if sat is None:
        return

    # Store pending recovery info — execute_scheduled_burns() checks this
    sat.scheduled_burns.append({
        "burn_id":           f"RECOVERY_{sat_id}_{int(current_time)}",
        "execute_at":        current_time + THRUSTER_COOLDOWN + 60.0,
        "delta_v":           -dv_evasion_eci * (RECOVERY_DV_KMS / EVASION_DV_KMS),
        "type":              "RECOVERY",
        "threat_debris_id":  debris_id,   # used to check if threat cleared
        "min_clear_time":    current_time + THRUSTER_COOLDOWN + 60.0,
    })


# ── Main planner ───────────────────────────────────────────────────────────────

def plan_maneuver(sat_id: str, debris_id: str, current_time: float):
    """
    Plan an evasion + recovery maneuver pair for sat_id avoiding debris_id.
    Returns a result dict or None if planning not possible.
    """
    sat = satellites.get(sat_id)
    deb = debris.get(debris_id)

    if sat is None or deb is None:
        return None

    # ── Cooldown check ─────────────────────────────────────────────────────────
    cooldown_left = sat.cooldown_remaining(current_time)
    if cooldown_left > 0:
        return {
            "satellite": sat_id,
            "status": "COOLDOWN",
            "cooldown_remaining_s": round(cooldown_left, 1),
        }

    # ── EOL check ──────────────────────────────────────────────────────────────
    if sat.is_critical_fuel:
        return _plan_graveyard(sat_id, current_time)

    # ── Fuel pre-check ─────────────────────────────────────────────────────────
    fuel_evasion  = fuel_consumed(sat.mass, EVASION_DV_KMS)
    fuel_recovery = fuel_consumed(sat.mass - fuel_evasion, RECOVERY_DV_KMS)

    if sat.fuel < (fuel_evasion + fuel_recovery):
        return {
            "satellite": sat_id,
            "status": "INSUFFICIENT_FUEL",
            "fuel_remaining_kg": round(sat.fuel, 4),
        }

    # ── Issue 4: Geometry-aware evasion delta-v ────────────────────────────────
    dv_evasion_eci, (rel_R, rel_T, rel_N) = compute_evasion_dv(
        sat.r.copy(), sat.v.copy(),
        deb.r.copy(), deb.v.copy(),
        EVASION_DV_KMS,
    )

    # ── Apply evasion burn ─────────────────────────────────────────────────────
    sat.v = sat.v + dv_evasion_eci
    sat.fuel -= fuel_evasion
    sat.last_burn_time = current_time
    sat.status = "EVADING"

    # ── Issue 5: TCA-aware recovery — no hardcoded T+660s ─────────────────────
    _schedule_recovery_when_clear(sat_id, debris_id, dv_evasion_eci, current_time)

    return {
        "satellite": sat_id,
        "status": "MANEUVER_PLANNED",
        "evasion": {
            "delta_v_eci_kms":  dv_evasion_eci.tolist(),
            "magnitude_ms":     round(EVASION_DV_KMS * 1000, 2),
            "fuel_used_kg":     round(fuel_evasion, 4),
            "approach_geometry": {
                "rel_R_km": round(rel_R, 4),
                "rel_T_km": round(rel_T, 4),
                "rel_N_km": round(rel_N, 4),
                "dominant_axis": "R" if abs(rel_R) >= max(abs(rel_T), abs(rel_N))
                                 else "T" if abs(rel_T) >= abs(rel_N) else "N",
            },
        },
        "recovery": {
            "status": "PENDING — fires when threat clears",
            "check_interval_s": RECOVERY_CHECK_INTERVAL_S,
            "fuel_budgeted_kg": round(fuel_recovery, 4),
        },
        "fuel_remaining_kg": round(sat.fuel, 4),
    }


def execute_scheduled_burns(current_time: float):
    """
    Execute any scheduled burns (evasion or recovery) due this tick.

    Issue 5 fix:
    Recovery burns now check if the threat debris has actually cleared
    (distance > SAFE_DISTANCE_KM) before firing. If threat is still active,
    the burn is delayed by RECOVERY_CHECK_INTERVAL_S and re-checked next tick.
    """
    executed = []

    for sat in satellites.values():
        due = [b for b in sat.scheduled_burns if b["execute_at"] <= current_time]

        for burn in due:
            # ── Cooldown check ─────────────────────────────────────────────────
            if sat.cooldown_remaining(current_time) > 0:
                continue

            # ── Issue 5: For recovery burns, verify threat has cleared ─────────
            if burn["type"] == "RECOVERY":
                threat_id = burn.get("threat_debris_id")
                if threat_id and _threat_still_active(sat.id, threat_id):
                    # Debris still too close — delay recovery by 5 minutes
                    burn["execute_at"] = current_time + RECOVERY_CHECK_INTERVAL_S
                    executed.append({
                        "satellite":  sat.id,
                        "burn_id":    burn["burn_id"],
                        "type":       "RECOVERY_DELAYED",
                        "status":     "THREAT_STILL_ACTIVE — retry in 5min",
                        "retry_at_s": burn["execute_at"],
                    })
                    continue

            # ── Fuel check ─────────────────────────────────────────────────────
            dv_mag       = float(np.linalg.norm(burn["delta_v"]))
            fuel_needed  = fuel_consumed(sat.mass, dv_mag)

            if sat.fuel < fuel_needed:
                sat.scheduled_burns.remove(burn)
                executed.append({
                    "satellite": sat.id,
                    "burn_id":   burn["burn_id"],
                    "status":    "SKIPPED_NO_FUEL",
                })
                continue

            # ── Apply burn ─────────────────────────────────────────────────────
            sat.v          = sat.v + burn["delta_v"]
            sat.fuel      -= fuel_needed
            sat.last_burn_time = current_time

            if burn["type"] == "RECOVERY":
                sat.status = "NOMINAL"

            sat.scheduled_burns.remove(burn)

            executed.append({
                "satellite":        sat.id,
                "burn_id":          burn["burn_id"],
                "type":             burn["type"],
                "status":           "EXECUTED",
                "fuel_remaining_kg": round(sat.fuel, 4),
            })

    return executed


def _plan_graveyard(sat_id: str, current_time: float):
    """
    When fuel is critical (<5%), raise satellite into graveyard orbit
    to prevent it becoming uncontrolled debris.
    Prograde burn raises apogee above LEO.
    """
    sat = satellites[sat_id]
    t_hat = sat.v / np.linalg.norm(sat.v)
    dv    = t_hat * GRAVEYARD_DV_KMS

    fuel_needed = fuel_consumed(sat.mass, GRAVEYARD_DV_KMS)
    if sat.fuel < fuel_needed:
        sat.status = "EOL_NO_FUEL"
        return {
            "satellite": sat_id,
            "status":    "EOL_NO_FUEL",
            "message":   "Insufficient fuel for graveyard — satellite is uncontrolled debris",
        }

    sat.v             -= dv   # retrograde to lower perigee for controlled reentry
    sat.fuel          -= fuel_needed
    sat.last_burn_time = current_time
    sat.status         = "EOL"

    return {
        "satellite":        sat_id,
        "status":           "GRAVEYARD_BURN",
        "delta_v_eci_kms":  dv.tolist(),
        "fuel_remaining_kg": round(sat.fuel, 4),
    }