"""
app/prediction/predictor.py
────────────────────────────
Bug fixes in this version:
  – Stage 0: immediate collision check for debris already inside 100 m.
  – Fixed ambiguous truth value error with NumPy arrays.
  – Added debug prints to verify detection.
"""

import numpy as np
from app.config import debris, satellites
from app.collision.spatial_index import build_tree, query_collisions
from app.prediction.tca import linear_tca, propagated_tca

COLLISION_RADIUS_KM = 0.1        # 100 metres
PREFILTER_RADIUS_KM = 50.0       # km
LINEAR_SAFE_KM = 2.0
PREDICTION_HORIZON_S = 86400.0


def predict_conjunctions(horizon_s: float = PREDICTION_HORIZON_S) -> list:
    if not satellites or not debris:
        return []

    sat_ids = list(satellites.keys())
    debris_ids = list(debris.keys())

    sat_positions = [list(satellites[sid].r) for sid in sat_ids]
    debris_positions = [list(debris[did].r) for did in debris_ids]

    # Stage 1: KDTree pre‑filter
    tree = build_tree(debris_positions)
    nearby_results = query_collisions(tree, sat_positions, PREFILTER_RADIUS_KM)

    warnings = []

    for i, nearby_indices in enumerate(nearby_results):
        # Check if the array is empty (works for both list and numpy array)
        if len(nearby_indices) == 0:
            continue

        sat = satellites[sat_ids[i]]
        sat_r = np.array(sat.r, dtype=float)
        sat_v = np.array(sat.v, dtype=float)

        for j in nearby_indices:
            # Ensure j is integer index (numpy arrays may return scalar)
            j_idx = int(j)
            deb = debris[debris_ids[j_idx]]
            deb_r = np.array(deb.r, dtype=float)
            deb_v = np.array(deb.v, dtype=float)

            # Stage 0: immediate collision check
            cur_dist = float(np.linalg.norm(sat_r - deb_r))
            if cur_dist < COLLISION_RADIUS_KM:
                warnings.append({
                    "satellite":    sat.id,
                    "debris":       deb.id,
                    "t_ca_seconds": 0.0,
                    "distance_km":  round(cur_dist, 6),
                    "severity":     "CRITICAL",
                })
                # No further processing for this debris
                continue

            # Stage 2: linear TCA filter
            t_lin, d_lin = linear_tca(sat, deb)
            if d_lin > LINEAR_SAFE_KM:
                continue

            # Stage 3: propagated TCA
            t_ca, min_dist = propagated_tca(
                sat_r, sat_v, deb_r, deb_v, horizon_s=horizon_s
            )

            if min_dist >= COLLISION_RADIUS_KM:
                continue

            if min_dist < COLLISION_RADIUS_KM:
                severity = "CRITICAL"
            elif min_dist < 1.0:
                severity = "RED"
            else:
                severity = "YELLOW"

            warnings.append({
                "satellite":    sat.id,
                "debris":       deb.id,
                "t_ca_seconds": round(t_ca, 1),
                "distance_km":  round(min_dist, 6),
                "severity":     severity,
            })

    # Optional debug print – will appear in the backend console
    if warnings:
        print(f"[DEBUG] predict_conjunctions found {len(warnings)} warnings")
        for w in warnings[:5]:  # show first 5
            print(f"  {w['satellite']} → {w['debris']} dist={w['distance_km']}km severity={w['severity']}")

    warnings.sort(key=lambda w: w["t_ca_seconds"])
    return warnings