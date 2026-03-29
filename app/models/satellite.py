"""
app/models/satellite.py
Bug 7 fix: add is_critical_fuel as alias for is_eol so both names work.
All other code unchanged.
"""

import math
from typing import Dict, List, Optional

DRY_MASS_KG:           float = 500.0
INITIAL_FUEL_KG:       float = 50.0
ISP_S:                 float = 300.0
G0_MS2:                float = 9.80665
MAX_DV_MS:             float = 15.0
COOLDOWN_S:            float = 600.0
EOL_FUEL_FRACTION:     float = 0.05
STATION_KEEPING_BOX_KM: float = 10.0


class Satellite:
    """
    Satellite state in ECI frame.
    r and v are stored as plain Python lists for JSON-serialisation
    compatibility. Use np.array(sat.r) before any vector arithmetic.
    """

    def __init__(
        self,
        sat_id: str,
        r: List[float],
        v: List[float],
        nominal_r: Optional[List[float]] = None,
        nominal_v: Optional[List[float]] = None,
    ) -> None:
        self.id:    str = sat_id
        self.r:     List[float] = list(r)
        self.v:     List[float] = list(v)
        self.nominal_r: List[float] = list(nominal_r) if nominal_r else list(r)
        self.nominal_v: List[float] = list(nominal_v) if nominal_v else list(v)
        self.fuel:           float = INITIAL_FUEL_KG
        self.dry_mass:       float = DRY_MASS_KG
        self.last_burn_time: float = -COOLDOWN_S   # allows burn at t=0
        self.scheduled_burns: List[Dict] = []
        self.status: str = "NOMINAL"

    # ── mass / fuel ───────────────────────────────────────────────────────────

    @property
    def mass(self) -> float:
        return self.dry_mass + max(self.fuel, 0.0)

    @property
    def fuel_fraction(self) -> float:
        return max(self.fuel, 0.0) / INITIAL_FUEL_KG

    @property
    def is_eol(self) -> bool:
        """True when fuel ≤ 5% of initial."""
        return self.fuel_fraction <= EOL_FUEL_FRACTION

    @property
    def is_critical_fuel(self) -> bool:
        """Alias for is_eol — both names accepted by planner."""
        return self.is_eol

    # ── cooldown ──────────────────────────────────────────────────────────────

    @property
    def cooldown_remaining(self) -> float:
        """
        Legacy property — always returns 0.0.
        Use cooldown_remaining_at(sim_time) for correct behaviour.
        Kept so old code that accesses sat.cooldown_remaining doesn't crash.
        """
        return 0.0

    def cooldown_remaining_at(self, sim_time: float) -> float:
        """Return remaining cooldown seconds at sim_time."""
        return max(0.0, COOLDOWN_S - (sim_time - self.last_burn_time))

    def is_on_cooldown(self, sim_time: float) -> bool:
        return self.cooldown_remaining_at(sim_time) > 0.0

    # ── station-keeping ───────────────────────────────────────────────────────

    def distance_to_slot(self) -> float:
        """Euclidean distance to nominal slot (km). Uses 10 km sphere per spec."""
        dx = self.r[0] - self.nominal_r[0]
        dy = self.r[1] - self.nominal_r[1]
        dz = self.r[2] - self.nominal_r[2]
        return math.sqrt(dx*dx + dy*dy + dz*dz)

    def in_station_keeping_box(self) -> bool:
        """True if within the 10 km spherical station-keeping box."""
        return self.distance_to_slot() <= STATION_KEEPING_BOX_KM

    # ── nominal slot propagation (Problem 7) ──────────────────────────────────

    def propagate_nominal(self, dt: float) -> None:
        """
        Advance nominal slot with same RK4+J2 propagator as real position.
        Called by simulate.py every tick to prevent phantom slot drift.
        """
        from app.orbit.propagator import propagate_orbit
        new_r, new_v = propagate_orbit(self.nominal_r, self.nominal_v, dt)
        self.nominal_r = list(new_r)
        self.nominal_v = list(new_v)

    # ── fuel accounting ───────────────────────────────────────────────────────

    def compute_fuel_cost(self, delta_v_ms: float) -> float:
        exponent = (delta_v_ms / 1000.0) * 1000.0 / (ISP_S * G0_MS2)
        return self.mass * (1.0 - math.exp(-exponent))

    def apply_burn(self, delta_v_vec_kms: List[float], sim_time: float) -> float:
        dv_ms = math.sqrt(sum(c**2 for c in delta_v_vec_kms)) * 1000.0
        if dv_ms > MAX_DV_MS + 1e-9:
            raise ValueError(f"ΔV {dv_ms:.3f} m/s > {MAX_DV_MS} m/s limit")
        consumed = self.compute_fuel_cost(dv_ms)
        if consumed > self.fuel + 1e-6:
            raise ValueError(f"Need {consumed:.4f} kg, have {self.fuel:.4f} kg")
        self.v[0] += delta_v_vec_kms[0]
        self.v[1] += delta_v_vec_kms[1]
        self.v[2] += delta_v_vec_kms[2]
        self.fuel = max(0.0, self.fuel - consumed)
        self.last_burn_time = sim_time
        return consumed

    # ── serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> Dict:
        return {
            "id":                  self.id,
            "r":                   self.r,
            "v":                   self.v,
            "fuel_kg":             round(self.fuel, 4),
            "fuel_pct":            round(self.fuel_fraction * 100, 2),
            "mass_kg":             round(self.mass, 4),
            "status":              self.status,
            "distance_to_slot_km": round(self.distance_to_slot(), 4),
            "in_box":              self.in_station_keeping_box(),
        }

    def __repr__(self) -> str:
        return f"<Satellite {self.id} fuel={self.fuel:.1f}kg status={self.status}>"