from fastapi import APIRouter
from pydantic import BaseModel

from app.config import satellites, debris, get_sim_time, advance_sim_time
from app.orbit.propagator import propagate_orbit
from app.collision.conjunction import detect_conjunctions
from app.maneuver.planner import plan_maneuver, execute_scheduled_burns

router = APIRouter()


class StepRequest(BaseModel):
    step_seconds: float


@router.post("/api/simulate/step")
def simulate_step(body: StepRequest):
    """
    Advance simulation by step_seconds.

    Order of operations per tick:
      1. Propagate all satellites (RK4 + J2)
      2. Propagate all debris     (RK4 + J2)
      3. Execute any scheduled recovery burns that are now due
      4. Detect conjunctions (KDTree spatial index)
      5. Plan evasion maneuvers for critical conjunctions
      6. Update nominal slots for station-keeping tracking
      7. Return step summary
    """
    step = body.step_seconds
    current_time = get_sim_time()

    # ── 1. Propagate satellites ───────────────────────────────────────────────
    for sat in satellites.values():
        if sat.status == "EOL":
            continue  # don't waste compute on dead satellites

        r_new, v_new = propagate_orbit(sat.r, sat.v, total_dt=step)
        sat.r = r_new
        sat.v = v_new

        # Also propagate nominal slot so station-keeping box moves with ideal orbit
        r_nom, v_nom = propagate_orbit(sat.nominal_r, sat.nominal_v, total_dt=step)
        sat.nominal_r = r_nom
        sat.nominal_v = v_nom

    # ── 2. Propagate debris ───────────────────────────────────────────────────
    for deb in debris.values():
        r_new, v_new = propagate_orbit(deb.r, deb.v, total_dt=step)
        deb.r = r_new
        deb.v = v_new

    # ── 3. Advance simulation clock ───────────────────────────────────────────
    advance_sim_time(step)
    new_time = get_sim_time()

    # ── 4. Execute any pending scheduled burns (e.g., recovery burns) ─────────
    executed_burns = execute_scheduled_burns(new_time)

    # ── 5. Detect conjunctions ────────────────────────────────────────────────
    warnings = detect_conjunctions()

    # ── 6. Plan evasion maneuvers for CRITICAL conjunctions ───────────────────
    maneuvers = []
    handled = set()

    for w in warnings:
        if w["severity"] != "CRITICAL":
            continue

        sat_id = w["satellite"]
        if sat_id in handled:
            continue

        sat = satellites.get(sat_id)
        if sat is None or sat.status == "EOL":
            continue

        maneuver = plan_maneuver(sat_id, w["debris"], new_time)

        if maneuver:
            maneuvers.append(maneuver)
            handled.add(sat_id)

    # ── 7. Build response ──────────────────────────────────────────────────────
    return {
        "status": "STEP_COMPLETE",
        "new_timestamp": new_time,
        "satellites_updated": sum(1 for s in satellites.values() if s.status != "EOL"),
        "debris_propagated": len(debris),
        "collisions_detected": sum(1 for w in warnings if w["severity"] == "CRITICAL"),
        "warnings_total": len(warnings),
        "maneuvers_executed": len(maneuvers) + len(executed_burns),
        "maneuvers": maneuvers,
        "scheduled_burns_executed": executed_burns,
    }