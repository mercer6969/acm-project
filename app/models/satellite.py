import numpy as np
DRY_MASS = 500.0   # kg
INITIAL_FUEL = 50.0  # kg

class Satellite:

    def __init__(self, sat_id, position, velocity, fuel=50.0, dry_mass=500.0):

        self.id = sat_id
        self.r = np.array(position, dtype=float)
        self.v = np.array(velocity, dtype=float)
        self.fuel = fuel
        self.dry_mass = dry_mass
    def state_vector(self):

        return np.concatenate([self.r, self.v])


@property
def mass(self):
    return self.dry_mass + self.fuel  # total wet mass — changes as fuel burnsimport numpy as np

# Spacecraft physical constants (per spec)
DRY_MASS = 500.0         # kg
INITIAL_FUEL = 50.0      # kg
FUEL_CRITICAL_PCT = 0.05 # 5% threshold → graveyard orbit


class Satellite:

    def __init__(self, sat_id: str, position, velocity,
                 fuel: float = INITIAL_FUEL, dry_mass: float = DRY_MASS):
        self.id = sat_id
        self.r = np.array(position, dtype=float)   # km, ECI
        self.v = np.array(velocity, dtype=float)   # km/s, ECI

        self.dry_mass = dry_mass                   # kg — never changes
        self.fuel = fuel                           # kg — depletes with burns

        # Nominal slot — set after deployment, used for station-keeping
        self.nominal_r = np.array(position, dtype=float)
        self.nominal_v = np.array(velocity, dtype=float)

        # Maneuver scheduling
        self.last_burn_time: float = -9999.0       # simulation seconds
        self.scheduled_burns: list = []            # list of pending burn dicts

        # Status tracking
        self.status: str = "NOMINAL"               # NOMINAL | EVADING | EOL

    @property
    def mass(self) -> float:
        """Total wet mass — decreases as fuel is burned. Used in Tsiolkovsky."""
        return self.dry_mass + self.fuel

    @property
    def fuel_fraction(self) -> float:
        return self.fuel / INITIAL_FUEL

    @property
    def is_critical_fuel(self) -> bool:
        return self.fuel_fraction <= FUEL_CRITICAL_PCT

    def state_vector(self) -> np.ndarray:
        return np.concatenate([self.r, self.v])

    def in_station_keeping_box(self, box_radius_km: float = 10.0) -> bool:
        """Check if satellite is within box_radius_km of its nominal slot."""
        if self.nominal_r is None:
            return True
        return np.linalg.norm(self.r - self.nominal_r) <= box_radius_km

    def cooldown_remaining(self, current_time: float) -> float:
        """Seconds remaining on thruster cooldown (600s between burns)."""
        return max(0.0, 600.0 - (current_time - self.last_burn_time))