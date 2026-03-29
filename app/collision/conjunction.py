import numpy as np
from app.config import satellites, debris
from app.collision.spatial_index import build_tree, query_collisions

COLLISION_RADIUS = 0.1    # km (100 m per spec)
WARNING_RADIUS   = 5.0    # km (yellow warning zone)


def detect_conjunctions() -> list[dict]:
    """
    KDTree spatial index — O(N log N) instead of O(N²).
    Returns warning dicts sorted by distance (closest first).

    Bug fix: sat.r is a plain Python list, debris.r is numpy.
    Use list() on both — works for list and numpy alike.
    """
    if not satellites or not debris:
        return []

    sat_ids    = list(satellites.keys())
    debris_ids = list(debris.keys())

    # list() works for both Python list and numpy array
    sat_positions    = [list(satellites[sid].r) for sid in sat_ids]
    debris_positions = [list(debris[did].r)     for did in debris_ids]

    tree    = build_tree(debris_positions)
    results = query_collisions(tree, sat_positions, WARNING_RADIUS)

    warnings = []
    for i, nearby_indices in enumerate(results):
        sat = satellites[sat_ids[i]]
        for j in nearby_indices:
            deb  = debris[debris_ids[j]]
            dist = float(np.linalg.norm(
                np.array(list(sat.r)) - np.array(list(deb.r))
            ))
            if dist < COLLISION_RADIUS:
                severity = "CRITICAL"
            elif dist < 1.0:
                severity = "RED"
            elif dist < WARNING_RADIUS:
                severity = "YELLOW"
            else:
                continue
            warnings.append({
                "satellite":   sat_ids[i],
                "debris":      debris_ids[j],
                "distance_km": round(dist, 4),
                "severity":    severity,
            })

    warnings.sort(key=lambda w: w["distance_km"])
    return warnings