"""
CRUD de carriles/líneas de conteo, usado por la UI de calibración.

Los carriles se guardan siempre como línea de 2 puntos ("diagonal"):
el motor de conteo ya sabe determinar la dirección de cruce con
producto cruzado para cualquier orientación, así que no hace falta
que el usuario elija "horizontal" o "vertical" — solo dibuja la línea
donde de verdad cruzan los vehículos en su cámara.
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.engine.counting_service import get_service
from src.storage import traffic_db

router = APIRouter(prefix="/api/lanes")


class LaneCreate(BaseModel):
    project_id: int
    name: str
    points: List[List[float]]  # exactamente 2 puntos [[x1,y1],[x2,y2]]
    # Calzada a la que pertenece. Sin ella la línea cuenta todo lo que la
    # cruce, incluidos los vehículos de la otra calzada.
    zone_id: Optional[int] = None


class LaneUpdate(BaseModel):
    name: Optional[str] = None
    points: Optional[List[List[float]]] = None
    # 0 desata la línea de su calzada; None deja el valor como estaba.
    zone_id: Optional[int] = None


def _maybe_reload_live(camera_source: Optional[str]):
    """Si el carril editado pertenece a la fuente en vivo actual, avisa
    al motor para que recargue sin reiniciar el proceso."""
    service = get_service()
    if service and camera_source and service.camera_source == camera_source:
        service.reload_lanes()


@router.get("")
def list_lanes(project_id: int):
    return traffic_db.list_lanes(project_id=project_id)


@router.post("")
def create_lane(lane: LaneCreate):
    if len(lane.points) != 2:
        raise HTTPException(400, "Una línea de conteo necesita exactamente 2 puntos")

    project = traffic_db.get_project(lane.project_id)
    if project is None:
        raise HTTPException(404, "Proyecto no encontrado")

    lane_id = traffic_db.create_lane(
        camera_source=project["name"],
        project_id=lane.project_id,
        name=lane.name,
        line_type="diagonal",
        points=lane.points,
        zone_id=lane.zone_id,
    )
    _maybe_reload_live(project["name"])
    traffic_db.log_event(
        lane.project_id, "calibracion", "Se agregó un carril",
        f"'{lane.name}' en {[[round(c) for c in pt] for pt in lane.points]}",
    )
    return {"id": lane_id, "name": lane.name}


@router.put("/{lane_id}")
def update_lane(lane_id: int, lane: LaneUpdate):
    lanes = traffic_db.list_lanes(active_only=False)
    existing = next((l for l in lanes if l["id"] == lane_id), None)
    if existing is None:
        raise HTTPException(404, "Carril no encontrado")
    if lane.points is not None and len(lane.points) != 2:
        raise HTTPException(400, "Una línea de conteo necesita exactamente 2 puntos")

    traffic_db.update_lane(
        lane_id,
        name=lane.name,
        line_type="diagonal" if lane.points is not None else None,
        points=lane.points,
        zone_id=lane.zone_id,
    )
    _maybe_reload_live(existing.get("camera_source"))
    # Mover una línea después de contar es justo lo que hace que dos
    # reportes del mismo proyecto no coincidan, así que se anota.
    cambios = []
    if lane.name is not None and lane.name != existing["name"]:
        cambios.append(f"nombre: '{existing['name']}' → '{lane.name}'")
    if lane.points is not None:
        cambios.append("se movió la línea")
    if cambios:
        traffic_db.log_event(
            existing.get("project_id"), "calibracion",
            f"Se editó el carril '{existing['name']}'", "; ".join(cambios),
        )
    return {"updated": lane_id}


@router.delete("/{lane_id}")
def delete_lane(lane_id: int):
    lanes = traffic_db.list_lanes(active_only=False)
    existing = next((l for l in lanes if l["id"] == lane_id), None)
    if existing is None:
        raise HTTPException(404, "Carril no encontrado")

    traffic_db.delete_lane(lane_id)
    _maybe_reload_live(existing.get("camera_source"))
    traffic_db.log_event(
        existing.get("project_id"), "calibracion", "Se eliminó un carril", existing["name"]
    )
    return {"deleted": lane_id}
