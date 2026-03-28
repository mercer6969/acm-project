"""
Satellite model for the ACM system.

Key guarantee (Problem 7 fix):
    sat.nominal_r and sat.nominal_v are propagated using the IDENTICAL
    RK4 + J2 integrator used for the real position (orbit.propagator).
    They are never advanced by a simpler method, preventing phantom
    station-keeping drift when no maneuvers have been fired.
"""

import math
from typing import Dict, List, Optional


# ── physical constants ────────────────────────────────────────────────────────
DRY_MASS_KG: float = 500.0
INITIAL_FUEL_KG: float = 50.0
ISP_S: float = 300.0
G0_MS2: float = 9.80665
MAX_DV_MS: float = 15.0          # per single burn command
COOLDOWN_S: float = 600.0
EOL_FUEL_FRACTION: float = 0.05  # 5 % → graveyard
STATION_KEEPING_BOX_KM: float = 10.0


class Satellite:
    """
    Represents one satellite in the constellation.

    Position / velocity are in ECI (J2000), km and km/s.
    nominal_r / nominal_v track the ideal, unperturbed slot using the
    same propagator as the real state — ensuring no phantom drift.
    """

    def __init__(
        self,
        sat_id: str,
        r: List[float],
        v: List[float],
        nominal_r: Optional[List[float]] = None,
        nominal_v: Optional[List[float]] = None,
    ) -> None:
        self.id: str = sat_id

        # ── real kinematic state ──────────────────────────────────────────
        self.r: List[float] = list(r)   # [x, y, z] km
        self.v: List[float] = list(v)   # [vx, vy, vz] km/s

        # ── nominal slot (same propagator, same epoch) ────────────────────
        # If not provided, the slot is initialised to the launch position.
        # Once set, it must be advanced only via propagate_nominal().
        self.nominal_r: List[float] = list(nominal_r) if nominal_r else list(r)
        self.nominal_v: List[float] = list(nominal_v) if nominal_v else list(v)

        # ── propellant budget ─────────────────────────────────────────────
        self.fuel: float = INITIAL_FUEL_KG          # kg, depleted each burn
        self.dry_mass: float = DRY_MASS_KG          # kg, constant

        # ── maneuver scheduling ───────────────────────────────────────────
        self.last_burn_time: float = -COOLDOWN_S    # allows burn at t=0
        self.scheduled_burns: List[Dict] = []       # pending burn dicts

        # ── mission status ────────────────────────────────────────────────
        # "NOMINAL" | "EVADING" | "RECOVERING" | "EOL"
        self.status: str = "NOMINAL"

    # ── derived properties ────────────────────────────────────────────────────

    @property
    def mass(self) -> float:
        """Current wet mass (dry + remaining fuel) in kg."""
        return self.dry_mass + max(self.fuel, 0.0)

    @property
    def fuel_fraction(self) -> float:
        """Fraction of initial fuel remaining (0.0 – 1.0)."""
        return max(self.fuel, 0.0) / INITIAL_FUEL_KG

    @property
    def is_eol(self) -> bool:
        """True when fuel has dropped to or below the EOL threshold."""
        return self.fuel_fraction <= EOL_FUEL_FRACTION

    @property
    def cooldown_remaining(self) -> float:
        """
        Seconds of thruster cooldown still active.
        Caller must pass current sim_time; this property is relative to
        last_burn_time, so use cooldown_remaining_at(sim_time) instead.
        Kept here as 0 so legacy code that checks `sat.cooldown_remaining`
        does not break — always use the method below for correctness.
        """
        return 0.0

    def cooldown_remaining_at(self, sim_time: float) -> float:
        """Return remaining cooldown seconds at the given sim_time."""
        elapsed = sim_time - self.last_burn_time
        return max(0.0, COOLDOWN_S - elapsed)

    def is_on_cooldown(self, sim_time: float) -> bool:
        """True if the thruster cannot fire yet at sim_time."""
        return self.cooldown_remaining_at(sim_time) > 0.0

    # ── station-keeping ───────────────────────────────────────────────────────

    def distance_to_slot(self) -> float:
        """
        Euclidean distance between current position and nominal slot (km).
        """
        dx = self.r[0] - self.nominal_r[0]
        dy = self.r[1] - self.nominal_r[1]
        dz = self.r[2] - self.nominal_r[2]
        return math.sqrt(dx*dx + dy*dy + dz*dz)

    def in_station_keeping_box(self) -> bool:
        """True when the satellite is within its 10 km nominal slot."""
        return self.distance_to_slot() <= STATION_KEEPING_BOX_KM

    # ── nominal slot propagation (Problem 7 fix) ──────────────────────────────

    def propagate_nominal(self, dt: float) -> None:
        """
        Advance the nominal slot by dt seconds using the SAME RK4 + J2
        integrator used for the real position.

        This method must be called alongside propagate_orbit() every tick
        so that the nominal slot never drifts relative to the real satellite
        when no maneuvers have been fired.

        Args:
            dt: time step in seconds (must be positive)
        """
        # Import here to avoid circular imports at module load time.
        from app.orbit.propagator import propagate_orbit

        new_r, new_v = propagate_orbit(self.nominal_r, self.nominal_v, dt)
        self.nominal_r = new_r
        self.nominal_v = new_v

    # ── fuel accounting ───────────────────────────────────────────────────────

    def compute_fuel_cost(self, delta_v_ms: float) -> float:
        """
        Return the propellant mass (kg) consumed by a burn of magnitude
        delta_v_ms [m/s] using the Tsiolkovsky rocket equation and the
        satellite's CURRENT wet mass (not initial mass).

        Does NOT modify self.fuel — call apply_burn() for that.
        """
        dv_kms = delta_v_ms / 1000.0          # m/s → km/s (Isp in SI)
        exponent = dv_kms * 1000.0 / (ISP_S * G0_MS2)   # unitless
        return self.mass * (1.0 - math.exp(-exponent))

    def apply_burn(
        self,
        delta_v_vec_kms: List[float],
        sim_time: float,
    ) -> float:
        """
        Apply an impulsive burn to the velocity vector and deplete fuel.

        Args:
            delta_v_vec_kms: [dvx, dvy, dvz] in km/s
            sim_time:        current simulation clock (seconds)

        Returns:
            Fuel mass consumed (kg).

        Raises:
            ValueError: if ΔV exceeds 15 m/s or fuel is insufficient.
        """
        dv_ms = math.sqrt(sum(c**2 for c in delta_v_vec_kms)) * 1000.0

        if dv_ms > MAX_DV_MS + 1e-9:
            raise ValueError(
                f"Burn magnitude {dv_ms:.3f} m/s exceeds hard limit "
                f"{MAX_DV_MS} m/s for {self.id}."
            )

        consumed = self.compute_fuel_cost(dv_ms)
        if consumed > self.fuel + 1e-6:
            raise ValueError(
                f"Insufficient fuel on {self.id}: need {consumed:.4f} kg, "
                f"have {self.fuel:.4f} kg."
            )

        # Apply ΔV
        self.v[0] += delta_v_vec_kms[0]
        self.v[1] += delta_v_vec_kms[1]
        self.v[2] += delta_v_vec_kms[2]

        # Deplete fuel
        self.fuel = max(0.0, self.fuel - consumed)
        self.last_burn_time = sim_time

        return consumed

    # ── serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> Dict:
        """Compact dict for snapshot / logging purposes."""
        return {
            "id": self.id,
            "r": self.r,
            "v": self.v,
            "nominal_r": self.nominal_r,
            "nominal_v": self.nominal_v,
            "fuel_kg": round(self.fuel, 4),
            "fuel_pct": round(self.fuel_fraction * 100, 2),
            "mass_kg": round(self.mass, 4),
            "status": self.status,
            "distance_to_slot_km": round(self.distance_to_slot(), 4),
            "in_box": self.in_station_keeping_box(),
        }

    def __repr__(self) -> str:
        return (
            f"<Satellite {self.id} "
            f"fuel={self.fuel:.1f}kg "
            f"status={self.status}>"
        )