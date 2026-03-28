import os
import math
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# ── Routers ────────────────────────────────────────────────────────────────────
from app.api.telemetry       import router as telemetry_router
from app.api.simulate        import router as simulate_router
from app.api.maneuver        import router as maneuver_router
from app.api.ground_stations import router as gs_router
from app.api.station_keeping import router as sk_router

# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Autonomous Constellation Manager",
    description="ACM — telemetry ingestion, conjunction prediction, autonomous maneuver planning",
    version="1.0.0",
)

# ── CORS — allows React frontend on port 3000 to call the API ─────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register all routers ───────────────────────────────────────────────────────
app.include_router(telemetry_router)
app.include_router(simulate_router)
app.include_router(maneuver_router,  prefix="/api/maneuver",         tags=["Maneuver"])
app.include_router(gs_router,        prefix="/api/ground-stations",  tags=["Ground Stations"])
app.include_router(sk_router,        prefix="/api/station-keeping",  tags=["Station Keeping"])


# ── Visualization snapshot (spec §6.3) ─────────────────────────────────────────
from app.config import satellites, debris, get_sim_time

@app.get("/api/visualization/snapshot")
def snapshot():
    """
    Compressed fleet snapshot for the 3D frontend.

    GST fix (Issue 3):
    ECI is inertial — fixed to stars. ECEF rotates with Earth.
    We convert using GST computed from simulation elapsed time,
    NOT wall-clock time. This means fast-forwarding via /simulate/step
    keeps satellites at the correct Earth-relative longitude.
    """
    sim_time_s = get_sim_time()

    # Greenwich Sidereal Time at J2000 + Earth rotation since sim start
    GST0_DEG  = 280.46061837          # GST at J2000 epoch (degrees)
    EARTH_ROT = 360.98564724 / 86164.1  # degrees per second
    gst_deg   = (GST0_DEG + EARTH_ROT * sim_time_s) % 360

    def eci_to_latlon(r):
        x, y, z = float(r[0]), float(r[1]), float(r[2])
        r_norm  = math.sqrt(x*x + y*y + z*z)
        if r_norm < 1.0:
            return 0.0, 0.0, 0.0
        lat     = math.degrees(math.asin(max(-1.0, min(1.0, z / r_norm))))
        lon_eci = math.degrees(math.atan2(y, x))
        # Subtract GST to rotate from ECI to ECEF
        lon     = (lon_eci - gst_deg + 180) % 360 - 180
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
            "fuel_kg": round(float(sat.fuel), 3),
            "status":  sat.status,
        })

    # Flattened tuple format per spec §6.3: [ID, lat, lon, alt]
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


# ── Health check ───────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ACM Running"}


# ── Serve React frontend static build (Issue 9) ────────────────────────────────
# Active only inside Docker where /acm/static/ exists after multi-stage build.
# In local dev, frontend runs on port 3000 via Vite — no change needed.
STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")

if os.path.isdir(STATIC_DIR):
    assets_dir = os.path.join(STATIC_DIR, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/")
    def serve_root():
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        # Let API routes pass through — only intercept frontend paths
        if any(full_path.startswith(p) for p in ["api/", "docs", "openapi", "health"]):
            raise HTTPException(status_code=404)
        index = os.path.join(STATIC_DIR, "index.html")
        if os.path.isfile(index):
            return FileResponse(index)
        raise HTTPException(status_code=404, detail="Frontend not built")

else:
    # Local dev fallback
    @app.get("/")
    def root():
        return {"status": "ACM Running — frontend on http://localhost:3000"}