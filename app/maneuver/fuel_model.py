import numpy as np

# Propulsion constants (per spec)
ISP = 300.0       # seconds (specific impulse)
G0 = 9.80665      # m/s^2 (standard gravity)

# Per spec limits
MAX_DELTA_V_KMS = 0.015   # km/s = 15 m/s per burn
THRUSTER_COOLDOWN = 600.0  # seconds between burns


def fuel_consumed(current_mass_kg: float, delta_v_kms: float) -> float:
    """
    Tsiolkovsky rocket equation — compute propellant mass consumed.

    current_mass_kg: total wet mass at time of burn (kg) — MUST use current mass,
                     not initial, since mass decreases with each burn.
    delta_v_kms: magnitude of delta-v in km/s

    Returns fuel consumed in kg.
    """
    # Convert km/s → m/s for Tsiolkovsky
    dv_ms = delta_v_kms * 1000.0

    delta_m = current_mass_kg * (1 - np.exp(-dv_ms / (ISP * G0)))

    return delta_m


def max_delta_v(current_mass_kg: float, fuel_kg: float) -> float:
    """
    Maximum achievable delta-v given current fuel reserves.
    Returns delta-v in km/s.
    """
    if fuel_kg <= 0:
        return 0.0

    # Tsiolkovsky inverted: dv = Isp * g0 * ln(m_wet / m_dry)
    m_wet = current_mass_kg
    m_dry = current_mass_kg - fuel_kg

    if m_dry <= 0:
        return 0.0

    dv_ms = ISP * G0 * np.log(m_wet / m_dry)

    return dv_ms / 1000.0  # m/s → km/s