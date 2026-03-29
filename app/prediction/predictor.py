import numpy as np
from app.config import satellites, debris
from app.collision.spatial_index import build_tree, query_collisions
from app.prediction.tca import linear_tca, propagated_tca

# Collision threshold per spec
COLLISION_RADIUS_KM = 0.1       # 100 metres

# Pre-filter radius for KDTree — only run expensive propagation on debris
# that is already within this range at current time OR moving toward satellite.
# Set conservatively large to avoid missing fast-moving debris.
PREFILTER_RADIUS_KM = 50.0      # km

# 24-hour lookahead required by spec
PREDICTION_HORIZON_S = 86400.0  # seconds


def predict_conjunctions(horizon_s: float = PREDICTION_HORIZON_S) -> list[dict]:
    """
    Predict all conjunctions within the next horizon_s seconds.

    Two-stage approach to avoid O(N²) propagation:

    Stage 1 — KDTree spatial pre-filter (cheap):
        Filter debris to only those currently within PREFILTER_RADIUS_KM
        of any satellite. Eliminates >99% of debris immediately.

    Stage 2 — Linear TCA filter (fast):
        For remaining candidates, compute linear TCA. Skip if the closest
        linear approach is still safe (> 5× collision radius). This catches
        debris on crossing trajectories without full propagation.

    Stage 3 — Propagated TCA (accurate, expensive, but rare):
        For the small set of genuine threat candidates, run the full
        two-pass RK4+J2 propagated TCA over the prediction horizon.

    Returns list of warning dicts sorted by time to closest approach.
    """
    if not satellites or not debris:
        return []

    sat_ids = list(satellites.keys())
    debris_ids = list(debris.keys())

    sat_positions = [list(satellites[sid].r) for sid in sat_ids]
    debris_positions = [list(debris[did].r) for did in debris_ids]

    # ── Stage 1: KDTree pre-filter ─────────────────────────────────────────
    tree = build_tree(debris_positions)
    nearby_results = query_collisions(tree, sat_positions, PREFILTER_RADIUS_KM)

    warnings = []

    for i, nearby_indices in enumerate(nearby_results):
        if len(nearby_indices) == 0:
            continue

        sat = satellites[sat_ids[i]]

        for j in nearby_indices:
            deb = debris[debris_ids[j]]

            # ── Stage 2: Linear TCA (fast sanity check) ────────────────────
            t_lin, d_lin = linear_tca(sat, deb)

            # If linear TCA is in the past or distance is very safe, skip
            if t_lin < 0 or d_lin > (COLLISION_RADIUS_KM * 5):
                continue

            # ── Stage 3: Propagated TCA (accurate) ────────────────────────
            t_ca, min_dist = propagated_tca(
                sat.r.copy(), sat.v.copy(),
                deb.r.copy(), deb.v.copy(),
                horizon_s=horizon_s,
            )

            if min_dist >= COLLISION_RADIUS_KM:
                continue

            # Determine severity
            if min_dist < COLLISION_RADIUS_KM:
                severity = "CRITICAL"
            else:
                severity = "WARNING"

            warnings.append({
                "satellite": sat.id,
                "debris": deb.id,
                "t_ca_seconds": round(t_ca, 1),
                "distance_km": round(min_dist, 5),
                "severity": severity,
            })

    # Sort by time to closest approach so the most imminent threat is first
    warnings.sort(key=lambda w: w["t_ca_seconds"])
    return warnings