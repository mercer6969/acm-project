"""
POST /api/simulate/step

Advances the simulation by step_seconds.  Every tick:
  1. Propagates real positions (RK4 + J2)
  2. Propagates nominal slot positions WITH THE SAME propagator  ← Problem 7 fix
  3. Advances the sim clock
  4. Executes any scheduled burns
  5. Runs the 3-stage conjunction predictor
  6. For each CRITICAL conjunction → plan evasion + schedule recovery
  7. Logs every event via the structured logger                   ← Problem 6 fix
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import (
    get_sim_time,
    advance_sim_time,
    satellites,
    debris,
)
from app.logger import log_cdm, get_recent_events
from app.maneuver.planner import plan_maneuver, execute_scheduled_burns
from app.orbit.propagator import propagate_orbit
from app.prediction.predictor import predict_conjunctions

router = APIRouter()


class StepRequest(BaseModel):
    step_seconds: float


class StepResponse(BaseModel):
    status: str
    new_timestamp: float
    collisions_detected: int
    maneuvers_executed: int
    conjunctions_active: int


@router.post("/api/simulate/step", response_model=StepResponse)
def simulate_step(req: StepRequest) -> StepResponse:
    dt = req.step_seconds

    # ── 1. Propagate real positions ───────────────────────────────────────────
    for sat in satellites.values():
        sat.r, sat.v = propagate_orbit(sat.r, sat.v, dt)

    for deb in debris.values():
        deb.r, deb.v = propagate_orbit(deb.r, deb.v, dt)

    # ── 2. Propagate nominal slots (Problem 7 fix) ────────────────────────────
    # Uses sat.propagate_nominal() which calls the same orbit.propagator.
    # Must happen AFTER real propagation so the slot tracks ideal orbit drift.
    for sat in satellites.values():
        sat.propagate_nominal(dt)

    # ── 3. Advance simulation clock ───────────────────────────────────────────
    advance_sim_time(dt)
    sim_time = get_sim_time()

    # ── 4. Execute scheduled burns ────────────────────────────────────────────
    maneuvers_executed = execute_scheduled_burns(sim_time)

    # ── 5 + 6. Conjunction prediction + logging (Problem 6 fix) ──────────────
    conjunctions = predict_conjunctions(sim_time)

    collisions_detected = 0
    for conj in conjunctions:
        sat_id      = conj["sat_id"]
        debris_id   = conj["debris_id"]
        tca         = conj.get("tca_sim_time", sim_time)
        miss_km     = conj.get("miss_distance_km", 0.0)
        severity    = conj.get("severity", "YELLOW")

        # Log every conjunction event with full details
        log_cdm(
            sat_id=sat_id,
            debris_id=debris_id,
            tca_sim_time=tca,
            predicted_miss_km=miss_km,
            severity=severity,
            sim_time_now=sim_time,
        )

        if severity == "CRITICAL":
            collisions_detected += 1
            # Autonomous evasion — planner handles fuel check, cooldown,
            # RTN geometry, Tsiolkovsky depletion, and recovery scheduling.
            # The planner itself calls log_maneuver_planned / log_recovery_scheduled.
            plan_maneuver(sat_id, debris_id, conj, sim_time)

    return StepResponse(
        status="STEP_COMPLETE",
        new_timestamp=sim_time,
        collisions_detected=collisions_detected,
        maneuvers_executed=maneuvers_executed,
        conjunctions_active=len(conjunctions),
    )


@router.get("/api/events")
def get_events(
    limit: int = 100,
    event_type: str = None,
    sat_id: str = None,
):
    """
    Return recent structured log events from the in-memory ring buffer.
    Useful for the frontend event log panel and for debugging.

    Query params:
        limit      - max events to return (default 100)
        event_type - filter: CDM_DETECTED | MANEUVER_PLANNED |
                             MANEUVER_EXECUTED | RECOVERY_SCHEDULED |
                             RECOVERY_EXECUTED | EOL_TRIGGERED
        sat_id     - filter by satellite ID
    """
    return {
        "events": get_recent_events(
            limit=limit,
            event_type=event_type,
            sat_id=sat_id,
        )
    }