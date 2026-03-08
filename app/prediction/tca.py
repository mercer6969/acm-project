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
    r_rel = sat.r - deb.r
    v_rel = sat.v - deb.v

    v_norm_sq = np.dot(v_rel, v_rel)

    # Objects moving in parallel — distance is constant
    if v_norm_sq < 1e-12:
        return 0.0, float(np.linalg.norm(r_rel))

    t_ca = -np.dot(r_rel, v_rel) / v_norm_sq

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
      Pass 1 — coarse scan over full horizon to find the minimum distance window
      Pass 2 — fine scan ±5 minutes around that window for precision

    horizon_s:     lookahead window in seconds (default 24 hours)
    coarse_step_s: time resolution for pass 1 (default 60s)
    fine_step_s:   time resolution for pass 2 (default 5s)

    Returns (t_ca_seconds, min_distance_km)
    """
    # ── Pass 1: coarse scan ────────────────────────────────────────────────
    r_s = sat_r.copy()
    v_s = sat_v.copy()
    r_d = deb_r.copy()
    v_d = deb_v.copy()

    min_dist = float("inf")
    best_t = 0.0
    t = 0.0

    while t <= horizon_s:
        dist = float(np.linalg.norm(r_s - r_d))
        if dist < min_dist:
            min_dist = dist
            best_t = t

        r_s, v_s = propagate_orbit(r_s, v_s, coarse_step_s)
        r_d, v_d = propagate_orbit(r_d, v_d, coarse_step_s)
        t += coarse_step_s

    # ── Pass 2: fine scan ±5 min around best_t ────────────────────────────
    fine_start = max(0.0, best_t - 300.0)
    fine_end = min(horizon_s, best_t + 300.0)

    # Re-propagate from scratch to fine_start
    r_s = sat_r.copy()
    v_s = sat_v.copy()
    r_d = deb_r.copy()
    v_d = deb_v.copy()

    if fine_start > 0:
        r_s, v_s = propagate_orbit(r_s, v_s, fine_start)
        r_d, v_d = propagate_orbit(r_d, v_d, fine_start)

    t = fine_start
    min_dist = float("inf")
    best_t = fine_start

    while t <= fine_end:
        dist = float(np.linalg.norm(r_s - r_d))
        if dist < min_dist:
            min_dist = dist
            best_t = t

        r_s, v_s = propagate_orbit(r_s, v_s, fine_step_s)
        r_d, v_d = propagate_orbit(r_d, v_d, fine_step_s)
        t += fine_step_s

    return best_t, min_dist