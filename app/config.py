# app/config.py
# Global simulation state — shared across all modules

from typing import Dict

# ── Object registries ──────────────────────────────────────────────────────────
# Populated by POST /api/telemetry
satellites: Dict[str, object] = {}   # sat_id → Satellite
debris: Dict[str, object] = {}       # deb_id → Debris

# ── Simulation clock ───────────────────────────────────────────────────────────
# Tracks elapsed simulation time in seconds (float).
# Used for cooldown checks, burn scheduling, and LOS windows.
_sim_time: float = 0.0


def get_sim_time() -> float:
    return _sim_time


def advance_sim_time(delta: float) -> float:
    global _sim_time
    _sim_time += delta
    return _sim_time


def reset_sim_time():
    global _sim_time
    _sim_time = 0.0