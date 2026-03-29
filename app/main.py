"""
app/main.py
Bug 10 fix: health endpoint returns same response at both / and /health
            so stress test calling GET / always gets {"status": "ACM Running"}.
Also: registers los_router so /api/los/check is available.
"""

import math
import os
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.ground_stations import router as gs_router
from app.api.los              import router as los_router
from app.api.maneuver         import router as maneuver_router
from app.api.simulate         import router as simulate_router
from app.api.station_keeping  import router as sk_router
from app.api.telemetry        import router as telemetry_router

app = FastAPI(
    title="Autonomous Constellation Manager",
    description="ACM — telemetry ingestion, conjunction prediction, autonomous maneuver planning",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(telemetry_router)
app.include_router(simulate_router)
app.include_router(maneuver_router,   tags=["Maneuver"])
app.include_router(gs_router,         prefix="/api/ground-stations", tags=["Ground Stations"])
app.include_router(sk_router,         prefix="/api/station-keeping", tags=["Station Keeping"])
app.include_router(los_router,        tags=["LOS"])


# ── Visualization snapshot (spec §6.3) ────────────────────────────────────────

from app.config import debris, get_sim_time, get_unix_time, satellites


@app.get("/api/visualization/snapshot")
def snapshot():
    """
    Compressed fleet snapshot for the 3D frontend.
    GST computed from simulation epoch (Bug 8 fix) so satellites appear
    at correct Earth-relative longitudes after sim fast-forward.
    """
    sim_time_s = get_sim_time()

    # Use same formula as los.py for consistency
    from app.api.los import _gast_radians
    gast = _gast_radians(get_unix_time())
    gast_deg = math.degrees(gast)

    def eci_to_latlon(r):
        x, y, z = float(r[0]), float(r[1]), float(r[2])
        r_norm = math.sqrt(x*x + y*y + z*z)
        if r_norm < 1.0:
            return 0.0, 0.0, 0.0
        lat     = math.degrees(math.asin(max(-1.0, min(1.0, z / r_norm))))
        lon_eci = math.degrees(math.atan2(y, x))
        lon     = (lon_eci - gast_deg + 180) % 360 - 180
        alt     = round(r_norm - 6378.137, 2)
        return round(lat, 4), round(lon, 4), alt

    sat_list = []
    for sat in satellites.values():
        lat, lon, alt = eci_to_latlon(sat.r)
        sat_list.append({
            "id":      sat.id,
            "lat":     lat,
            "lon":     lon,
            "alt_km":  alt,
            "r":       list(sat.r),      # ECI for LOS scanning in stress test
            "fuel_kg": round(float(sat.fuel), 3),
            "status":  sat.status,
        })

    debris_cloud = []
    for deb in debris.values():
        lat, lon, alt = eci_to_latlon(deb.r)
        debris_cloud.append([deb.id, round(lat, 3), round(lon, 3), alt])

    return {
        "timestamp":    datetime.utcnow().isoformat() + "Z",
        "sim_time_s":   sim_time_s,
        "satellites":   sat_list,
        "debris_cloud": debris_cloud,
    }


# ── Health check — Bug 10 fix ─────────────────────────────────────────────────
# Respond at both / and /health with same body so both stress test
# (calls /) and Docker health checks (calls /health) pass.

STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")

if os.path.isdir(STATIC_DIR):
    assets_dir = os.path.join(STATIC_DIR, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/health")
    def health_docker():
        return {"status": "ACM Running"}

    @app.get("/")
    def serve_root():
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        if any(full_path.startswith(p)
               for p in ["api/", "docs", "openapi", "health"]):
            raise HTTPException(status_code=404)
        index = os.path.join(STATIC_DIR, "index.html")
        if os.path.isfile(index):
            return FileResponse(index)
        raise HTTPException(status_code=404)

else:
    # Local dev — both / and /health return the same body
    @app.get("/")
    @app.get("/health")
    def root():
        return {"status": "ACM Running"}