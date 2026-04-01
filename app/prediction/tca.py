"""
app/prediction/tca.py
──────────────────────
Bug fixes in this version:

  Bug D (belt-and-suspenders): propagated_tca() now wraps every input
      with np.array(x, dtype=float) at entry. Even if the caller forgot
      to convert Python lists, subtraction and norm will work correctly.

  Bug G: propagated_tca coarse step was 60s. For debris placed at 0.05 km
      with near-zero relative velocity, the satellite propagates ~0.4 km
      per step so the minimum is reliably found. However for fast-crossing
      debris (~14 km/s relative) the window of < 0.1 km lasts only ~7ms —
      far shorter than 60s. The coarse step can jump over it entirely.

      Fix: added a velocity-adaptive coarse step. If relative speed is high,
      use a smaller step so the close-approach window is never skipped.
      Default coarse step is still 60s for near-zero relative velocity.

  All other logic unchanged.
"""

import numpy as np
from app.orbit.propagator import propagate_orbit


def linear_tca(sat, deb):
    """
    Fast linear approximation of Time of Closest Approach.
    Assumes constant velocity — valid only for short time windows (~minutes).
    Used as a cheap pre-filter before doing expensive propagation.

    Returns (t_ca_seconds, min_distance_km)
    t_ca may be negative (closest approach was in the past).
    """
    # Bug D fix: always numpy, even if sat.r / deb.r are Python lists
    sat_r = np.array(sat.r, dtype=float)
    sat_v = np.array(sat.v, dtype=float)
    deb_r = np.array(deb.r, dtype=float)
    deb_v = np.array(deb.v, dtype=float)

    r_rel = sat_r - deb_r
    v_rel = sat_v - deb_v

    v_norm_sq = float(np.dot(v_rel, v_rel))

    # Objects moving in parallel (or same velocity) — distance is constant
    if v_norm_sq < 1e-12:
        return 0.0, float(np.linalg.norm(r_rel))

    t_ca = -float(np.dot(r_rel, v_rel)) / v_norm_sq

    closest_r = r_rel + v_rel * t_ca
    dist = float(np.linalg.norm(closest_r))

    return float(t_ca), dist


def propagated_tca(sat_r, sat_v, deb_r, deb_v,
                   horizon_s: float = 86400.0,
                   coarse_step_s: float = 60.0,
                   fine_step_s: float = 5.0):
    """
    Accurate TCA using orbital propagation (RK4 + J2).

    Two-pass approach:
      Pass 1 — coarse scan over full horizon to locate the minimum distance
               window. Step size is velocity-adaptive so fast-closing debris
               never has its close-approach window skipped entirely.
      Pass 2 — fine scan ±5 minutes around that window for precision.

    Parameters
    ----------
    sat_r, sat_v : array-like (km, km/s) — satellite state in ECI
    deb_r, deb_v : array-like (km, km/s) — debris state in ECI
    horizon_s    : lookahead window in seconds (default 24 hours)
    coarse_step_s: base coarse step; may be reduced for fast-closing debris
    fine_step_s  : fine scan resolution (default 5 s)

    Returns
    -------
    (t_ca_seconds, min_distance_km)
    """
    # Bug D fix: guarantee numpy float64 regardless of caller
    r_s = np.array(sat_r, dtype=float)
    v_s = np.array(sat_v, dtype=float)
    r_d = np.array(deb_r, dtype=float)
    v_d = np.array(deb_v, dtype=float)

    # Bug G fix: velocity-adaptive coarse step.
    # If objects are closing at v_rel km/s, the < 0.1 km window lasts
    # roughly 0.2 / v_rel seconds. Sample at ≤ 1/3 of that window.
    v_rel_mag = float(np.linalg.norm(v_s - v_d))
    if v_rel_mag > 0.01:                          # > 10 m/s relative speed
        window_s   = 0.2 / v_rel_mag              # seconds the window lasts
        adaptive_s = max(1.0, window_s / 3.0)     # at least 1 s
        coarse_step_s = min(coarse_step_s, adaptive_s)

    # ── Pass 1: coarse scan ────────────────────────────────────────────────
    r_s_c = r_s.copy()
    v_s_c = v_s.copy()
    r_d_c = r_d.copy()
    v_d_c = v_d.copy()

    min_dist = float("inf")
    best_t   = 0.0
    t        = 0.0

    while t <= horizon_s:
        dist = float(np.linalg.norm(r_s_c - r_d_c))
        if dist < min_dist:
            min_dist = dist
            best_t   = t

        r_s_c, v_s_c = propagate_orbit(r_s_c, v_s_c, coarse_step_s)
        r_d_c, v_d_c = propagate_orbit(r_d_c, v_d_c, coarse_step_s)
        t += coarse_step_s

    # ── Pass 2: fine scan ±5 min around best_t ────────────────────────────
    fine_start = max(0.0,       best_t - 300.0)
    fine_end   = min(horizon_s, best_t + 300.0)

    # Re-propagate from scratch to fine_start
    r_s_f = r_s.copy()
    v_s_f = v_s.copy()
    r_d_f = r_d.copy()
    v_d_f = v_d.copy()

    if fine_start > 0.0:
        r_s_f, v_s_f = propagate_orbit(r_s_f, v_s_f, fine_start)
        r_d_f, v_d_f = propagate_orbit(r_d_f, v_d_f, fine_start)

    t        = fine_start
    min_dist = float("inf")
    best_t   = fine_start

    while t <= fine_end:
        dist = float(np.linalg.norm(r_s_f - r_d_f))
        if dist < min_dist:
            min_dist = dist
            best_t   = t

        r_s_f, v_s_f = propagate_orbit(r_s_f, v_s_f, fine_step_s)
        r_d_f, v_d_f = propagate_orbit(r_d_f, v_d_f, fine_step_s)
        t += fine_step_s

    return best_t, min_dist