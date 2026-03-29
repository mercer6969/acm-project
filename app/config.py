# app/config.py
# Global simulation state — shared across all modules

from typing import Dict

# ── Object registries ──────────────────────────────────────────────────────────
satellites: Dict[str, object] = {}   # sat_id → Satellite
debris:     Dict[str, object] = {}   # deb_id → Debris

# ── Simulation clock ───────────────────────────────────────────────────────────
# Tracks elapsed simulation time in seconds (float).
_sim_time: float = 0.0

# ── Absolute simulation epoch (Bug 8 fix) ─────────────────────────────────────
# The simulation starts at 2026-03-12T08:00:00Z = Unix 1741766400.0
# This is used by los.py to convert sim elapsed time → Unix timestamp
# so GAST (Greenwich Apparent Sidereal Time) is computed correctly.
# Without this, passing sim_time=600 to _gast_radians gives a wildly
# wrong Earth rotation angle, breaking all LOS calculations.
SIM_EPOCH_UNIX: float = 1741766400.0   # 2026-03-12T08:00:00Z


def get_sim_time() -> float:
    """Return elapsed simulation time in seconds."""
    return _sim_time


def get_unix_time() -> float:
    """
    Return current simulation time as a Unix timestamp.
    Use this wherever real-world sidereal time is needed (LOS checks, GST).
    """
    return SIM_EPOCH_UNIX + _sim_time


def advance_sim_time(delta: float) -> float:
    global _sim_time
    _sim_time += delta
    return _sim_time


def reset_sim_time():
    global _sim_time
    _sim_time = 0.0