from fastapi import FastAPI
from app.api.telemetry import router as telemetry_router
from app.api.simulate import router as simulate_router
from app.api.maneuver import router as maneuver_router

app = FastAPI(
    title="Autonomous Constellation Manager",
    description="ACM backend — telemetry ingestion, conjunction prediction, autonomous maneuver planning",
    version="1.0.0",
)

app.include_router(telemetry_router)
app.include_router(simulate_router)
app.include_router(maneuver_router)


@app.get("/")
def root():
    return {"status": "ACM Running"}


# ── Visualization snapshot endpoint (required by spec §6.3) ───────────────────
# Returns compressed satellite + debris positions for the frontend dashboard.
from fastapi.responses import JSONResponse
from app.config import satellites, debris
import numpy as np


@app.get("/api/visualization/snapshot")
def snapshot():
    from datetime import datetime
    from app.config import get_sim_time

    def eci_to_latlon(r):
        """Approximate ECI → lat/lon/alt for visualization only."""
        x, y, z = r
        r_norm = float(np.linalg.norm(r))
        lat = float(np.degrees(np.arcsin(z / r_norm))) if r_norm > 0 else 0.0
        lon = float(np.degrees(np.arctan2(y, x)))
        alt = round(r_norm - 6378.137, 2)  # altitude above Earth surface in km
        return lat, lon, alt

    sat_list = []
    for sat in satellites.values():
        lat, lon, alt = eci_to_latlon(sat.r)
        sat_list.append({
            "id": sat.id,
            "lat": round(lat, 4),
            "lon": round(lon, 4),
            "alt_km": alt,
            "fuel_kg": round(sat.fuel, 3),
            "status": sat.status,
        })

    # Flattened tuple format per spec: [ID, lat, lon, alt]
    debris_cloud = []
    for deb in debris.values():
        lat, lon, alt = eci_to_latlon(deb.r)
        debris_cloud.append([deb.id, round(lat, 3), round(lon, 3), alt])

    return {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "sim_time_s": get_sim_time(),
        "satellites": sat_list,
        "debris_cloud": debris_cloud,
    }

#--Ground station, maneuver, and station-keeping API routers (required by spec §6.2) ───────────────────
    from fastapi.middleware.cors import CORSMiddleware

    from app.api.ground_stations import router as gs_router
    from app.api.maneuver        import router as maneuver_router
    from app.api.station_keeping import router as sk_router
 
    app = FastAPI(title="ACM Backend", version="1.0.0")
 
    app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],   # your React frontend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
 

    app.include_router(gs_router,       prefix="/api/ground-stations",  tags=["Ground Stations"])
    app.include_router(maneuver_router, prefix="/api/maneuver",         tags=["Maneuver"])
    app.include_router(sk_router,       prefix="/api/station-keeping",  tags=["Station Keeping"])