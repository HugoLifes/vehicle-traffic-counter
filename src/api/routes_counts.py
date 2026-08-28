"""
Endpoints de estado del motor, carriles y conteos agregados.
"""

from fastapi import APIRouter, HTTPException

from src.engine.counting_service import get_service
from src.storage import traffic_db

router = APIRouter(prefix="/api")


@router.get("/status")
def get_status():
    service = get_service()
    if service is None:
        raise HTTPException(503, "Motor de conteo no inicializado")
    return {
        "status": service.status,
        "last_error": service.last_error,
        "camera_source": service.camera_source,
        "frame_width": service.frame_width,
        "frame_height": service.frame_height,
        "fps_estimate": round(service.fps_estimate, 1),
    }


@router.get("/counts")
def get_counts():
    """
    Conteos agregados por carril, dirección y tipo de vehículo.
    Siempre se calculan desde la tabla `crossings` (fuente única de
    verdad) para que nunca queden desincronizados de lo realmente
    registrado.
    """
    rows = traffic_db.get_counts()
    lanes = {lane["id"]: lane for lane in traffic_db.list_lanes(active_only=False)}

    by_lane = {}
    for row in rows:
        lane_id = row["lane_id"]
        lane_name = lanes.get(lane_id, {}).get("name", f"Carril {lane_id}")
        entry = by_lane.setdefault(lane_id, {
            "lane_id": lane_id,
            "lane_name": lane_name,
            "in": 0, "out": 0, "total": 0,
            "by_vehicle_type": {}
        })
        entry[row["direction"]] = entry.get(row["direction"], 0) + row["total"]
        entry["total"] += row["total"]
        vt = entry["by_vehicle_type"].setdefault(row["vehicle_type"], {"in": 0, "out": 0})
        vt[row["direction"]] = vt.get(row["direction"], 0) + row["total"]

    return list(by_lane.values())
