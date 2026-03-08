import numpy as np
from app.config import satellites, debris
from app.collision.spatial_index import build_tree, query_collisions

# Per spec: collision threshold is 100 meters = 0.1 km
COLLISION_RADIUS = 0.1   # km

# Warn early if debris is within this range (5 km = yellow warning zone)
WARNING_RADIUS = 5.0     # km


def detect_conjunctions() -> list[dict]:
    """
    Use KDTree spatial index to find all satellite-debris pairs
    within COLLISION_RADIUS (critical) or WARNING_RADIUS (caution).

    Returns list of warning dicts sorted by distance (closest first).
    """
    if not satellites or not debris:
        return []

    sat_ids = list(satellites.keys())
    debris_ids = list(debris.keys())

    sat_positions = [satellites[sid].r.tolist() for sid in sat_ids]
    debris_positions = [debris[did].r.tolist() for did in debris_ids]

    # Build KDTree over debris positions — O(N log N) query instead of O(N^2)
    tree = build_tree(debris_positions)

    # Query with the larger warning radius, then filter by severity
    results = query_collisions(tree, sat_positions, WARNING_RADIUS)

    warnings = []

    for i, nearby_indices in enumerate(results):
        sat = satellites[sat_ids[i]]

        for j in nearby_indices:
            deb = debris[debris_ids[j]]

            dist = float(np.linalg.norm(sat.r - deb.r))

            if dist < COLLISION_RADIUS:
                severity = "CRITICAL"
            elif dist < 1.0:
                severity = "RED"
            elif dist < WARNING_RADIUS:
                severity = "YELLOW"
            else:
                continue  # shouldn't happen but be safe

            warnings.append({
                "satellite": sat_ids[i],
                "debris": debris_ids[j],
                "distance_km": round(dist, 4),
                "severity": severity
            })

    # Sort by distance so the most dangerous conjunctions are handled first
    warnings.sort(key=lambda w: w["distance_km"])

    return warnings