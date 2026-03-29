"""
app/api/simulate.py
───────────────────
Bug fixes in this version:
  Bug 2: predict_conjunctions() called without args
  Bug 3: conjunction dict keys fixed
  Bug 4: plan_maneuver called with 3 args not 4
  Bug 5: maneuvers_executed counter includes both executed + planned
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import advance_sim_time, debris, get_sim_time, satellites
from app.logger import get_recent_events, log_cdm
from app.maneuver.planner import execute_scheduled_burns, plan_maneuver
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

    # 1. Propagate real positions
    for sat in satellites.values():
        sat.r, sat.v = propagate_orbit(sat.r, sat.v, dt)

    for deb in debris.values():
        deb.r, deb.v = propagate_orbit(deb.r, deb.v, dt)

    # 2. Propagate nominal slots with same RK4+J2 (Problem 7 fix)
    for sat in satellites.values():
        sat.propagate_nominal(dt)

    # 3. Advance simulation clock
    advance_sim_time(dt)
    sim_time = get_sim_time()

    # 4. Execute scheduled burns that are now due
    maneuvers_executed_list = execute_scheduled_burns(sim_time)
    maneuvers_planned_count = 0

    # 5+6. Conjunction prediction + autonomous evasion
    conjunctions = predict_conjunctions()

    collisions_detected = 0
    for conj in conjunctions:
        sat_id    = conj["satellite"]
        debris_id = conj["debris"]
        tca_s     = conj.get("t_ca_seconds", 0.0)
        miss_km   = conj.get("distance_km", 0.0)
        severity  = conj.get("severity", "YELLOW")

        log_cdm(
            sat_id=sat_id,
            debris_id=debris_id,
            tca_sim_time=sim_time + tca_s,
            predicted_miss_km=miss_km,
            severity=severity,
            sim_time_now=sim_time,
        )

        if severity == "CRITICAL":
            collisions_detected += 1
            result = plan_maneuver(sat_id, debris_id, sim_time)
            if result:
                maneuvers_planned_count += 1

    # Bug 5 fix: total = burns executed this tick + new evasions planned
    total_maneuvers = len(maneuvers_executed_list) + maneuvers_planned_count

    return StepResponse(
        status="STEP_COMPLETE",
        new_timestamp=sim_time,
        collisions_detected=collisions_detected,
        maneuvers_executed=total_maneuvers,
        conjunctions_active=len(conjunctions),
    )


@router.get("/api/simulate/events")
@router.get("/api/events")
def get_events(
    limit: int = 100,
    event_type: str = None,
    satellite_id: str = None,
):
    events = get_recent_events(
        limit=limit,
        event_type=event_type,
        sat_id=satellite_id,
    )
    return {"count": len(events), "events": events}