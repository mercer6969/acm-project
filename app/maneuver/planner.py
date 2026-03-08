import numpy as np
from app.config import satellites, debris
from app.maneuver.fuel_model import fuel_consumed, MAX_DELTA_V_KMS, THRUSTER_COOLDOWN

# Evasion burn magnitude — conservative, well within 15 m/s limit
EVASION_DV_KMS = 0.010     # km/s = 10 m/s
RECOVERY_DV_KMS = 0.010    # km/s = 10 m/s (approximate reverse)

# Graveyard orbit: raise perigee by ~300 km above LEO
GRAVEYARD_DV_KMS = 0.012   # km/s


def _evasion_direction(sat_r: np.ndarray, debris_r: np.ndarray,
                       sat_v: np.ndarray) -> np.ndarray:
    """
    Compute unit vector for evasion burn using RTN frame logic.

    Strategy: burn in the Transverse (prograde/retrograde) direction,
    which is most fuel-efficient for changing orbital phasing.
    Direction chosen to maximise separation from debris approach vector.
    """
    # Relative position: debris → satellite (push away from debris)
    rel_pos = sat_r - debris_r

    # Transverse direction (prograde)
    t_hat = sat_v / np.linalg.norm(sat_v)

    # Normal direction (out of plane)
    r_hat = sat_r / np.linalg.norm(sat_r)
    n_hat = np.cross(r_hat, t_hat)
    n_hat /= np.linalg.norm(n_hat)

    # Project relative position onto RTN to decide prograde or retrograde
    rel_transverse = np.dot(rel_pos, t_hat)

    # Burn retrograde if debris is approaching from behind, prograde otherwise
    direction = t_hat if rel_transverse < 0 else -t_hat

    return direction


def plan_maneuver(sat_id: str, debris_id: str, current_time: float) -> dict | None:
    """
    Plan an evasion + recovery maneuver pair for sat_id avoiding debris_id.

    Returns a maneuver dict or None if not possible.
    """
    sat = satellites.get(sat_id)
    deb = debris.get(debris_id)

    if sat is None or deb is None:
        return None

    # ── Cooldown check ────────────────────────────────────────────────────────
    cooldown_left = sat.cooldown_remaining(current_time)
    if cooldown_left > 0:
        return {
            "satellite": sat_id,
            "status": "COOLDOWN",
            "cooldown_remaining_s": round(cooldown_left, 1)
        }

    # ── EOL check ─────────────────────────────────────────────────────────────
    if sat.is_critical_fuel:
        return _plan_graveyard(sat_id, current_time)

    # ── Fuel check for evasion + recovery ─────────────────────────────────────
    fuel_evasion = fuel_consumed(sat.mass, EVASION_DV_KMS)
    fuel_recovery = fuel_consumed(sat.mass - fuel_evasion, RECOVERY_DV_KMS)

    if sat.fuel < (fuel_evasion + fuel_recovery):
        return {
            "satellite": sat_id,
            "status": "INSUFFICIENT_FUEL",
            "fuel_remaining_kg": round(sat.fuel, 4)
        }

    # ── Compute evasion delta-v vector ────────────────────────────────────────
    evasion_dir = _evasion_direction(sat.r, deb.r, sat.v)
    dv_evasion = evasion_dir * EVASION_DV_KMS          # km/s vector

    # ── Apply evasion burn ────────────────────────────────────────────────────
    sat.v = sat.v + dv_evasion
    sat.fuel -= fuel_evasion
    sat.last_burn_time = current_time
    sat.status = "EVADING"

    # ── Schedule recovery burn after cooldown + buffer ────────────────────────
    # Recovery burn reverses the evasion approximately (opposite direction)
    # A proper Hohmann transfer would be ideal but this keeps it simple and correct
    recovery_time = current_time + THRUSTER_COOLDOWN + 60.0   # 10 min buffer
    dv_recovery = -dv_evasion * (RECOVERY_DV_KMS / EVASION_DV_KMS)

    sat.scheduled_burns.append({
        "burn_id": f"RECOVERY_{sat_id}_{int(current_time)}",
        "execute_at": recovery_time,
        "delta_v": dv_recovery,
        "type": "RECOVERY"
    })

    return {
        "satellite": sat_id,
        "status": "MANEUVER_PLANNED",
        "evasion": {
            "delta_v_kms": dv_evasion.tolist(),
            "magnitude_ms": round(EVASION_DV_KMS * 1000, 3),
            "fuel_used_kg": round(fuel_evasion, 4),
        },
        "recovery": {
            "scheduled_at_sim_s": round(recovery_time, 1),
            "delta_v_kms": dv_recovery.tolist(),
            "fuel_budgeted_kg": round(fuel_recovery, 4),
        },
        "fuel_remaining_kg": round(sat.fuel, 4)
    }


def execute_scheduled_burns(current_time: float) -> list[dict]:
    """
    Execute any recovery (or other scheduled) burns whose time has arrived.
    Called every simulate/step tick.
    """
    executed = []

    for sat in satellites.values():
        due = [b for b in sat.scheduled_burns if b["execute_at"] <= current_time]

        for burn in due:
            cooldown_left = sat.cooldown_remaining(current_time)
            if cooldown_left > 0:
                continue  # still cooling down, will retry next tick

            fuel_needed = fuel_consumed(sat.mass, np.linalg.norm(burn["delta_v"]))

            if sat.fuel < fuel_needed:
                sat.scheduled_burns.remove(burn)
                executed.append({
                    "satellite": sat.id,
                    "burn_id": burn["burn_id"],
                    "status": "SKIPPED_NO_FUEL"
                })
                continue

            # Apply the burn
            sat.v = sat.v + burn["delta_v"]
            sat.fuel -= fuel_needed
            sat.last_burn_time = current_time

            if burn["type"] == "RECOVERY":
                sat.status = "NOMINAL"

            sat.scheduled_burns.remove(burn)

            executed.append({
                "satellite": sat.id,
                "burn_id": burn["burn_id"],
                "type": burn["type"],
                "status": "EXECUTED",
                "fuel_remaining_kg": round(sat.fuel, 4)
            })

    return executed


def _plan_graveyard(sat_id: str, current_time: float) -> dict:
    """
    When fuel is critical (<5%), raise satellite into graveyard orbit
    to prevent it becoming uncontrolled debris.
    """
    sat = satellites[sat_id]

    # Prograde burn to raise apogee (graveyard)
    t_hat = sat.v / np.linalg.norm(sat.v)
    dv_graveyard = t_hat * GRAVEYARD_DV_KMS

    fuel_needed = fuel_consumed(sat.mass, GRAVEYARD_DV_KMS)

    if sat.fuel < fuel_needed:
        sat.status = "EOL_NO_FUEL"
        return {
            "satellite": sat_id,
            "status": "EOL_NO_FUEL",
            "message": "Insufficient fuel even for graveyard — satellite is dead debris"
        }

    sat.v = sat.v + dv_graveyard
    sat.fuel -= fuel_needed
    sat.last_burn_time = current_time
    sat.status = "EOL"

    return {
        "satellite": sat_id,
        "status": "GRAVEYARD_BURN",
        "delta_v_kms": dv_graveyard.tolist(),
        "fuel_remaining_kg": round(sat.fuel, 4)
    }