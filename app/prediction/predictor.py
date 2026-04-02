"""
app/prediction/predictor.py
– Immediate distance check + brute‑force fallback
"""

import numpy as np
from app.config import debris, satellites
from app.collision.spatial_index import build_tree, query_collisions
from app.prediction.tca import linear_tca, propagated_tca

COLLISION_RADIUS_KM = 0.1
PREFILTER_RADIUS_KM = 50.0
LINEAR_SAFE_KM = 2.0
PREDICTION_HORIZON_S = 86400.0

def predict_conjunctions(horizon_s: float = PREDICTION_HORIZON_S) -> list:
    if not satellites or not debris:
        return []

    sat_ids = list(satellites.keys())
    debris_ids = list(debris.keys())

    # Build KDTree
    debris_positions = [list(debris[did].r) for did in debris_ids]
    tree = build_tree(debris_positions)
    sat_positions = [list(satellites[sid].r) for sid in sat_ids]
    nearby_results = query_collisions(tree, sat_positions, PREFILTER_RADIUS_KM)

    warnings = []

    for i, nearby_indices in enumerate(nearby_results):
        sat = satellites[sat_ids[i]]
        sat_r = np.array(sat.r, dtype=float)
        sat_v = np.array(sat.v, dtype=float)

        # Candidates from KDTree
        candidate_indices = set(int(j) for j in nearby_indices) if len(nearby_indices) > 0 else set()

        # SAFETY NET: if KDTree returned nothing, brute‑force check all debris
        if len(candidate_indices) == 0:
            # Brute‑force all debris (only runs if KDTree fails)
            for j, deb_id in enumerate(debris_ids):
                deb = debris[deb_id]
                deb_r = np.array(deb.r, dtype=float)
                dist = float(np.linalg.norm(sat_r - deb_r))
                if dist < PREFILTER_RADIUS_KM:
                    candidate_indices.add(j)
        # Now process all candidates
        for j in candidate_indices:
            deb = debris[debris_ids[j]]
            deb_r = np.array(deb.r, dtype=float)
            deb_v = np.array(deb.v, dtype=float)

            # Stage 0: immediate collision
            cur_dist = float(np.linalg.norm(sat_r - deb_r))
            if cur_dist < COLLISION_RADIUS_KM:
                warnings.append({
                    "satellite": sat.id,
                    "debris": deb.id,
                    "t_ca_seconds": 0.0,
                    "distance_km": round(cur_dist, 6),
                    "severity": "CRITICAL",
                })
                continue

            # Stage 2: linear TCA
            t_lin, d_lin = linear_tca(sat, deb)
            if d_lin > LINEAR_SAFE_KM:
                continue

            # Stage 3: propagated TCA
            t_ca, min_dist = propagated_tca(
                sat_r, sat_v, deb_r, deb_v, horizon_s=horizon_s
            )
            if min_dist >= COLLISION_RADIUS_KM:
                continue

            severity = "CRITICAL" if min_dist < COLLISION_RADIUS_KM else \
                       "RED" if min_dist < 1.0 else "YELLOW"
            warnings.append({
                "satellite": sat.id,
                "debris": deb.id,
                "t_ca_seconds": round(t_ca, 1),
                "distance_km": round(min_dist, 6),
                "severity": severity,
            })

    warnings.sort(key=lambda w: w["t_ca_seconds"])
    return warnings