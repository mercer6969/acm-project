# app/api/visualization.py
from fastapi import APIRouter
from app.config import satellites, debris, get_sim_time
import math

router = APIRouter()

_cache = {"timestamp": None, "data": None}

def _ecef_to_latlon(x, y, z):
    r = math.sqrt(x*x + y*y + z*z)
    lat = math.degrees(math.asin(z / r))
    lon = math.degrees(math.atan2(y, x))
    return lat, lon

@router.get("/api/visualization/snapshot")
def get_snapshot():
    sim_time = get_sim_time()
    if _cache["timestamp"] == sim_time and _cache["data"] is not None:
        return _cache["data"]

    sats = []
    for sat in satellites.values():
        lat, lon = _ecef_to_latlon(sat.r[0], sat.r[1], sat.r[2])
        sats.append({
            "id": sat.id,
            "lat": lat,
            "lon": lon,
            "fuel_kg": sat.fuel,
            "status": sat.status,
        })

    # Send only 10% of debris (every 10th)
    debris_list = []
    for i, deb in enumerate(debris.values()):
        if i % 10 == 0:
            lat, lon = _ecef_to_latlon(deb.r[0], deb.r[1], deb.r[2])
            debris_list.append([deb.id, lat, lon, deb.r[2] - 6378.137])  # alt km

    result = {
        "timestamp": sim_time,
        "satellites": sats,
        "debris_cloud": debris_list,
    }
    _cache["timestamp"] = sim_time
    _cache["data"] = result
    return result