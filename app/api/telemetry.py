from fastapi import APIRouter
from pydantic import BaseModel
from typing import List

from app.models.satellite import Satellite
from app.models.debris import Debris
from app.config import satellites, debris
from app.collision.conjunction import detect_conjunctions

router = APIRouter()


class Vector(BaseModel):
    x: float
    y: float
    z: float


class ObjectState(BaseModel):
    id: str
    type: str
    r: Vector
    v: Vector


class TelemetryRequest(BaseModel):
    timestamp: str
    objects: List[ObjectState]


@router.post("/api/telemetry")
def ingest(data: TelemetryRequest):

    for obj in data.objects:
        pos = [obj.r.x, obj.r.y, obj.r.z]
        vel = [obj.v.x, obj.v.y, obj.v.z]

        # ── Case-insensitive type routing ──────────────────────────────────
        # Spec sends "DEBRIS" uppercase; test payloads may use lowercase.
        obj_type = obj.type.upper()

        if obj_type == "SATELLITE":
            satellites[obj.id] = Satellite(obj.id, pos, vel)

        elif obj_type == "DEBRIS":
            debris[obj.id] = Debris(obj.id, pos, vel)

    # ── Count current active warnings for response ─────────────────────────
    # Only run if we actually have both satellites and debris to check
    active_warnings = 0
    if satellites and debris:
        warnings = detect_conjunctions()
        active_warnings = len(warnings)

    return {
        "status": "ACK",
        "processed_count": len(data.objects),
        "active_cdm_warnings": active_warnings,   # required by spec
    }