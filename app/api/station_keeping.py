import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple
 
from fastapi import APIRouter
from pydantic import BaseModel
 
from app.api.maneuver import (
    Vec3, build_rtn_frame, plan_hohmann_transfer,
    plan_phasing_maneuver, _norm, _sub, EARTH_RADIUS_KM
)
 
router = APIRouter()
 
# ---------------------------------------------------------------------------
# Station-Keeping Box definition (RTN frame)
# ---------------------------------------------------------------------------
@dataclass
class SKBox:
    """
    Rectangular dead-band box in RTN coordinates.
 
    All dimensions in kilometres.
    The box is centred on the nominal orbit point (origin of the RTN frame).
 
    half_r_km:  allowed radial  drift  (altitude error)
    half_t_km:  allowed tangential drift (along-track phase error)
    half_n_km:  allowed normal drift (cross-track / inclination error)
 
    Typical LEO station-keeping box: ±1 km radial, ±5 km tangential, ±2 km normal
    GEO east-west station-keeping:   ±0.05° longitude ≈ ±37 km tangential
    """
    name: str
    half_r_km: float = 1.0   # radial
    half_t_km: float = 5.0   # tangential (along-track)
    half_n_km: float = 2.0   # normal (cross-track)
 
    # Warning threshold as fraction of box limit (default 80%)
    warning_fraction: float = 0.80
 
    def check(self, rtn_offset: Vec3) -> "BoxCheckResult":
        """
        Check an RTN offset vector against the box limits.
        rtn_offset: (dR, dT, dN) deviation from nominal in km.
        """
        dR, dT, dN = rtn_offset
        viol_r = abs(dR) > self.half_r_km
        viol_t = abs(dT) > self.half_t_km
        viol_n = abs(dN) > self.half_n_km
 
        warn_r = abs(dR) > self.half_r_km * self.warning_fraction
        warn_t = abs(dT) > self.half_t_km * self.warning_fraction
        warn_n = abs(dN) > self.half_n_km * self.warning_fraction
 
        violated = viol_r or viol_t or viol_n
        warning  = (warn_r or warn_t or warn_n) and not violated
 
        return BoxCheckResult(
            box_name=self.name,
            rtn_offset_km=rtn_offset,
            violated=violated,
            warning=warning,
            violation_axes=[
                ax for ax, v in [("R", viol_r), ("T", viol_t), ("N", viol_n)] if v
            ],
            warning_axes=[
                ax for ax, w in [("R", warn_r), ("T", warn_t), ("N", warn_n)] if w
            ],
            margin_r_km=round(self.half_r_km - abs(dR), 4),
            margin_t_km=round(self.half_t_km - abs(dT), 4),
            margin_n_km=round(self.half_n_km - abs(dN), 4),
        )
 
 
# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------
class BoxStatus(str, Enum):
    OK       = "OK"
    WARNING  = "WARNING"
    VIOLATED = "VIOLATED"
 
 
@dataclass
class BoxCheckResult:
    box_name: str
    rtn_offset_km: Vec3
    violated: bool
    warning: bool
    violation_axes: List[str]
    warning_axes: List[str]
    margin_r_km: float
    margin_t_km: float
    margin_n_km: float
 
    @property
    def status(self) -> BoxStatus:
        if self.violated:
            return BoxStatus.VIOLATED
        if self.warning:
            return BoxStatus.WARNING
        return BoxStatus.OK
 
 
@dataclass
class RecoveryBurn:
    """A scheduled recovery burn to bring satellite back inside SK box."""
    sat_id: str
    triggered_by: str               # which axis was violated
    burn_time_unix: float           # when to execute (Unix ts)
    burn_type: str                  # "radial_correction" | "tangential_correction" | "normal_correction" | "combined"
    delta_v_rtn_km_s: Vec3
    delta_v_eci_km_s: Vec3
    delta_v_magnitude_m_s: float
    burn_duration_s: float
    priority: int                   # 1 = highest (immediate), 3 = low
    notes: str
 
 
# ---------------------------------------------------------------------------
# Recovery burn planner
# ---------------------------------------------------------------------------
def _radial_correction_dv(dR_km: float, v_circ_km_s: float) -> Vec3:
    """
    Small radial correction: fire in -R to lower orbit (reduce altitude),
    or +R to raise. Uses linearised CW (Clohessy-Wiltshire) approximation.
    A pure R burn also induces T drift, so we add a compensating T component.
    """
    # For a drift dR over one orbit, required delta-v ≈ n * dR / 2
    # where n = mean motion. Simplified: just use proportional R burn.
    dv_r = -dR_km * 0.001   # scale factor (tunable gain)
    dv_t = 0.0
    return (round(dv_r, 6), dv_t, 0.0)
 
 
def _tangential_correction_dv(dT_km: float, orbital_period_s: float) -> Vec3:
    """
    Phase correction to remove along-track offset.
    Tangential burn of magnitude dT / (3π * T / (2π)) = 2*dT / (3*T)
    in km/s (very small for typical station-keeping).
    """
    dv_t = -2.0 * dT_km / (3.0 * orbital_period_s / (2 * math.pi))
    return (0.0, round(dv_t, 6), 0.0)
 
 
def _normal_correction_dv(dN_km: float, v_circ_km_s: float) -> Vec3:
    """
    Cross-track (inclination) correction. A normal burn removes the
    cross-track velocity; for a small incl error dN, dv_N ≈ n * dN.
    """
    n = math.sqrt(398600.4418 / ((EARTH_RADIUS_KM + 500)**3)) * 1e3  # approx LEO n (rad/s)
    dv_n = -dN_km * n * 1e-3  # to km/s
    return (0.0, 0.0, round(dv_n, 6))
 
 
def plan_recovery_burn(
    sat_id: str,
    pos_eci: Vec3,
    vel_eci: Vec3,
    check: BoxCheckResult,
    nominal_pos_eci: Vec3,
    mass_kg: float = 100.0,
    thrust_n: float = 1.0,
) -> Optional[RecoveryBurn]:
    """
    Given a BoxCheckResult that shows VIOLATED status, generate a RecoveryBurn.
    Returns None if status is OK or WARNING (no burn needed yet).
    """
    if not check.violated:
        return None
 
    frame = build_rtn_frame(pos_eci, vel_eci)
    r = _norm(pos_eci)
    v = _norm(vel_eci)
    v_circ = math.sqrt(398600.4418 / r)
    T = 2 * math.pi * math.sqrt(r**3 / 398600.4418)
 
    dR, dT, dN = check.rtn_offset_km
    viol_axes = check.violation_axes
 
    # Determine burn type and compute delta-V
    if len(viol_axes) == 1:
        ax = viol_axes[0]
        if ax == "R":
            dv_rtn = _radial_correction_dv(dR, v_circ)
            burn_type = "radial_correction"
            priority = 2
        elif ax == "T":
            dv_rtn = _tangential_correction_dv(dT, T)
            burn_type = "tangential_correction"
            priority = 3
        else:  # N
            dv_rtn = _normal_correction_dv(dN, v_circ)
            burn_type = "normal_correction"
            priority = 2
    else:
        # Combined burn: sum corrections
        dr = _radial_correction_dv(dR, v_circ) if "R" in viol_axes else (0,0,0)
        dt = _tangential_correction_dv(dT, T)  if "T" in viol_axes else (0,0,0)
        dn = _normal_correction_dv(dN, v_circ) if "N" in viol_axes else (0,0,0)
        dv_rtn = (
            dr[0]+dt[0]+dn[0],
            dr[1]+dt[1]+dn[1],
            dr[2]+dt[2]+dn[2],
        )
        burn_type = "combined"
        priority = 1
 
    dv_eci = frame.rtn_to_eci(dv_rtn)
    dv_m_s = _norm(dv_rtn) * 1000.0
    accel = thrust_n / mass_kg
    burn_s = dv_m_s / accel if accel > 0 else 0.0
 
    return RecoveryBurn(
        sat_id=sat_id,
        triggered_by="+".join(viol_axes),
        burn_time_unix=time.time() + 300.0,   # schedule 5 minutes from now
        burn_type=burn_type,
        delta_v_rtn_km_s=tuple(round(x, 6) for x in dv_rtn),
        delta_v_eci_km_s=tuple(round(x, 6) for x in dv_eci),
        delta_v_magnitude_m_s=round(dv_m_s, 6),
        burn_duration_s=round(burn_s, 3),
        priority=priority,
        notes=(
            f"Recovery burn for {sat_id}. "
            f"Violations: {viol_axes}. "
            f"RTN offset: dR={dR:.3f} km, dT={dT:.3f} km, dN={dN:.3f} km."
        ),
    )
 
 
# ---------------------------------------------------------------------------
# In-memory burn queue (replace with DB/Redis in production)
# ---------------------------------------------------------------------------
_burn_queue: List[RecoveryBurn] = []
_default_boxes: Dict[str, SKBox] = {
    "LEO": SKBox("LEO", half_r_km=1.0, half_t_km=5.0, half_n_km=2.0),
    "MEO": SKBox("MEO", half_r_km=2.0, half_t_km=10.0, half_n_km=3.0),
    "GEO": SKBox("GEO", half_r_km=5.0, half_t_km=37.0, half_n_km=5.0),
}
 
 
# ---------------------------------------------------------------------------
# FastAPI endpoints
# ---------------------------------------------------------------------------
class SKCheckRequest(BaseModel):
    sat_id: str
    pos_eci_km: List[float]          # current ECI position
    vel_eci_km_s: List[float]        # current ECI velocity
    nominal_pos_eci_km: List[float]  # nominal (target) ECI position
    shell: str = "LEO"               # "LEO" | "MEO" | "GEO"
    mass_kg: float = 100.0
    thrust_n: float = 1.0
    # Override box limits (optional)
    half_r_km: Optional[float] = None
    half_t_km: Optional[float] = None
    half_n_km: Optional[float] = None
 
 
class SKCheckResponse(BaseModel):
    sat_id: str
    status: str
    box_name: str
    rtn_offset_km: dict
    violation_axes: List[str]
    warning_axes: List[str]
    margin_km: dict
    recovery_burn: Optional[dict]
    burn_scheduled: bool
 
 
@router.post("/check", response_model=SKCheckResponse)
def check_station_keeping(req: SKCheckRequest):
    """
    POST /api/station-keeping/check
 
    Checks if satellite is inside its SK box. If violated, plans and queues
    a recovery burn automatically.
 
    Body example:
    {
      "sat_id": "SAT-001",
      "pos_eci_km": [6871, 0, 0],
      "vel_eci_km_s": [0, 7.784, 0],
      "nominal_pos_eci_km": [6870, 0, 0],
      "shell": "LEO"
    }
    """
    pos = tuple(req.pos_eci_km)
    vel = tuple(req.vel_eci_km_s)
    nom = tuple(req.nominal_pos_eci_km)
 
    # Select (and optionally override) the SK box
    box = _default_boxes.get(req.shell, _default_boxes["LEO"])
    if req.half_r_km is not None: box.half_r_km = req.half_r_km
    if req.half_t_km is not None: box.half_t_km = req.half_t_km
    if req.half_n_km is not None: box.half_n_km = req.half_n_km
 
    # Compute RTN offset from nominal
    frame = build_rtn_frame(pos, vel)
    diff_eci = _sub(pos, nom)
    rtn_offset = frame.eci_to_rtn(diff_eci)
 
    check = box.check(rtn_offset)
 
    # Plan recovery burn if violated
    burn = None
    if check.violated:
        burn = plan_recovery_burn(req.sat_id, pos, vel, check, nom, req.mass_kg, req.thrust_n)
        if burn:
            _burn_queue.append(burn)
            _burn_queue.sort(key=lambda b: b.priority)
 
    return SKCheckResponse(
        sat_id=req.sat_id,
        status=check.status.value,
        box_name=check.box_name,
        rtn_offset_km={"dR": round(rtn_offset[0], 4), "dT": round(rtn_offset[1], 4), "dN": round(rtn_offset[2], 4)},
        violation_axes=check.violation_axes,
        warning_axes=check.warning_axes,
        margin_km={"R": check.margin_r_km, "T": check.margin_t_km, "N": check.margin_n_km},
        recovery_burn=vars(burn) if burn else None,
        burn_scheduled=burn is not None,
    )
 
 
@router.get("/burn-queue")
def get_burn_queue():
    """GET /api/station-keeping/burn-queue — view all pending recovery burns."""
    return [vars(b) for b in _burn_queue]
 
 
@router.delete("/burn-queue/{sat_id}")
def clear_burns(sat_id: str):
    """DELETE /api/station-keeping/burn-queue/{sat_id} — remove burns for a satellite."""
    global _burn_queue
    removed = [b for b in _burn_queue if b.sat_id == sat_id]
    _burn_queue = [b for b in _burn_queue if b.sat_id != sat_id]
    return {"removed": len(removed), "sat_id": sat_id}