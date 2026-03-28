"""
Structured event logger for the ACM system.
Writes JSON-line logs to acm_events.log and also keeps an in-memory
ring buffer (last 500 events) that the snapshot endpoint can serve.

Usage (anywhere in the codebase):
    from app.logger import log_cdm, log_maneuver_planned, \
        log_maneuver_executed, log_recovery_scheduled, \
        log_recovery_executed, log_eol_triggered, get_recent_events
"""

import json
import logging
import os
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

# ── file handler ──────────────────────────────────────────────────────────────
LOG_PATH = os.environ.get("ACM_LOG_PATH", "acm_events.log")

_file_logger = logging.getLogger("acm.events")
_file_logger.setLevel(logging.DEBUG)
_file_logger.propagate = False

if not _file_logger.handlers:
    _fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(message)s"))   # raw JSON lines
    _file_logger.addHandler(_fh)

    _ch = logging.StreamHandler()
    _ch.setLevel(logging.INFO)
    _ch.setFormatter(logging.Formatter("[ACM] %(message)s"))
    _file_logger.addHandler(_ch)

# ── in-memory ring buffer ─────────────────────────────────────────────────────
_RING_SIZE = 500
_ring: Deque[Dict[str, Any]] = deque(maxlen=_RING_SIZE)


# ── internal writer ───────────────────────────────────────────────────────────
def _emit(event_type: str, payload: Dict[str, Any]) -> None:
    record: Dict[str, Any] = {
        "event": event_type,
        "ts": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    _ring.append(record)
    _file_logger.info(json.dumps(record, default=str))


# ── public API ────────────────────────────────────────────────────────────────

def log_cdm(
    sat_id: str,
    debris_id: str,
    tca_sim_time: float,
    predicted_miss_km: float,
    severity: str,
    sim_time_now: float,
) -> None:
    """
    Log a Conjunction Data Message event.

    Args:
        sat_id:               satellite identifier, e.g. "SAT-Alpha-04"
        debris_id:            debris identifier, e.g. "DEB-99421"
        tca_sim_time:         simulation seconds at Time of Closest Approach
        predicted_miss_km:    miss distance at TCA in kilometres
        severity:             "YELLOW" | "RED" | "CRITICAL"
        sim_time_now:         current simulation clock (seconds)
    """
    _emit("CDM_DETECTED", {
        "sat_id": sat_id,
        "debris_id": debris_id,
        "tca_sim_time_s": round(tca_sim_time, 2),
        "tca_in_s": round(tca_sim_time - sim_time_now, 2),
        "miss_distance_km": round(predicted_miss_km, 6),
        "severity": severity,
    })


def log_maneuver_planned(
    sat_id: str,
    burn_id: str,
    burn_sim_time: float,
    delta_v_kms: Dict[str, float],
    fuel_before_kg: float,
    fuel_after_kg: float,
    maneuver_type: str = "EVASION",
) -> None:
    """
    Log a maneuver that has been planned and queued (not yet executed).

    Args:
        sat_id:          satellite identifier
        burn_id:         unique burn label, e.g. "EVASION_BURN_1"
        burn_sim_time:   scheduled execution time (simulation seconds)
        delta_v_kms:     ΔV vector in km/s  {"x": ..., "y": ..., "z": ...}
        fuel_before_kg:  fuel mass before this burn
        fuel_after_kg:   predicted fuel mass after burn (Tsiolkovsky)
        maneuver_type:   "EVASION" | "RECOVERY" | "GRAVEYARD"
    """
    dv = delta_v_kms
    magnitude_ms = (dv["x"]**2 + dv["y"]**2 + dv["z"]**2) ** 0.5 * 1000.0
    _emit("MANEUVER_PLANNED", {
        "sat_id": sat_id,
        "burn_id": burn_id,
        "maneuver_type": maneuver_type,
        "burn_sim_time_s": round(burn_sim_time, 2),
        "delta_v_km_s": {k: round(v, 8) for k, v in dv.items()},
        "delta_v_magnitude_m_s": round(magnitude_ms, 4),
        "fuel_before_kg": round(fuel_before_kg, 4),
        "fuel_after_kg": round(fuel_after_kg, 4),
        "fuel_consumed_kg": round(fuel_before_kg - fuel_after_kg, 4),
    })


def log_maneuver_executed(
    sat_id: str,
    burn_id: str,
    delta_v_kms: Dict[str, float],
    fuel_remaining_kg: float,
    sim_time: float,
    success: bool = True,
    reason: Optional[str] = None,
) -> None:
    """
    Log a burn that has actually been applied to the satellite state vector.

    Args:
        sat_id:              satellite identifier
        burn_id:             burn label matching the planned entry
        delta_v_kms:         ΔV actually applied in km/s
        fuel_remaining_kg:   fuel mass after burn
        sim_time:            simulation clock at execution
        success:             False if burn was rejected / skipped
        reason:              optional rejection reason string
    """
    dv = delta_v_kms
    magnitude_ms = (dv["x"]**2 + dv["y"]**2 + dv["z"]**2) ** 0.5 * 1000.0
    payload: Dict[str, Any] = {
        "sat_id": sat_id,
        "burn_id": burn_id,
        "sim_time_s": round(sim_time, 2),
        "delta_v_km_s": {k: round(v, 8) for k, v in dv.items()},
        "delta_v_magnitude_m_s": round(magnitude_ms, 4),
        "fuel_remaining_kg": round(fuel_remaining_kg, 4),
        "success": success,
    }
    if reason:
        payload["reason"] = reason
    _emit("MANEUVER_EXECUTED", payload)


def log_recovery_scheduled(
    sat_id: str,
    burn_id: str,
    scheduled_sim_time: float,
    delta_v_kms: Dict[str, float],
    evasion_burn_id: str,
) -> None:
    """
    Log a recovery burn being queued after a successful evasion.

    Args:
        sat_id:               satellite identifier
        burn_id:              recovery burn label
        scheduled_sim_time:   when the recovery burn will fire (sim seconds)
        delta_v_kms:          planned ΔV vector in km/s
        evasion_burn_id:      the evasion burn this recovery is paired with
    """
    _emit("RECOVERY_SCHEDULED", {
        "sat_id": sat_id,
        "burn_id": burn_id,
        "paired_evasion_burn": evasion_burn_id,
        "scheduled_sim_time_s": round(scheduled_sim_time, 2),
        "delta_v_km_s": {k: round(v, 8) for k, v in delta_v_kms.items()},
    })


def log_recovery_executed(
    sat_id: str,
    burn_id: str,
    sim_time: float,
    distance_to_slot_km: float,
    fuel_remaining_kg: float,
    in_box: bool,
) -> None:
    """
    Log the outcome of a recovery burn.

    Args:
        sat_id:                 satellite identifier
        burn_id:                recovery burn label
        sim_time:               simulation clock at execution
        distance_to_slot_km:    distance to nominal slot after burn
        fuel_remaining_kg:      fuel mass after burn
        in_box:                 True if satellite is back within 10 km box
    """
    _emit("RECOVERY_EXECUTED", {
        "sat_id": sat_id,
        "burn_id": burn_id,
        "sim_time_s": round(sim_time, 2),
        "distance_to_slot_km": round(distance_to_slot_km, 4),
        "fuel_remaining_kg": round(fuel_remaining_kg, 4),
        "in_station_keeping_box": in_box,
    })


def log_eol_triggered(
    sat_id: str,
    fuel_remaining_kg: float,
    fuel_fraction: float,
    sim_time: float,
) -> None:
    """
    Log when a satellite crosses the 5% EOL fuel threshold.

    Args:
        sat_id:              satellite identifier
        fuel_remaining_kg:   actual kg remaining
        fuel_fraction:       fraction 0.0–1.0
        sim_time:            simulation clock
    """
    _emit("EOL_TRIGGERED", {
        "sat_id": sat_id,
        "fuel_remaining_kg": round(fuel_remaining_kg, 4),
        "fuel_fraction_pct": round(fuel_fraction * 100, 2),
        "sim_time_s": round(sim_time, 2),
        "action": "GRAVEYARD_BURN_SCHEDULED",
    })


def log_graveyard_executed(
    sat_id: str,
    sim_time: float,
    fuel_remaining_kg: float,
) -> None:
    """Log the execution of a graveyard orbit insertion burn."""
    _emit("GRAVEYARD_EXECUTED", {
        "sat_id": sat_id,
        "sim_time_s": round(sim_time, 2),
        "fuel_remaining_kg": round(fuel_remaining_kg, 4),
        "new_status": "EOL",
    })


def get_recent_events(
    limit: int = 100,
    event_type: Optional[str] = None,
    sat_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Return recent events from the in-memory ring buffer.
    Newest events last (chronological order).

    Args:
        limit:       maximum number of events to return
        event_type:  optional filter, e.g. "CDM_DETECTED"
        sat_id:      optional filter by satellite ID
    """
    events = list(_ring)

    if event_type:
        events = [e for e in events if e.get("event") == event_type]
    if sat_id:
        events = [e for e in events if e.get("sat_id") == sat_id]

    return events[-limit:]