"""
Zonas: polígonos dibujados sobre el video que delimitan la calzada.

Una línea de conteo dice DÓNDE se cuenta; una zona dice CUÁL calzada es.
Hacen falta las dos porque en perspectiva las dos calzadas se superponen
en la imagen: una sola línea vertical las cruza a ambas, y sin las zonas
no hay forma de saber si un cruce fue de la calzada de ida o la de vuelta.
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.storage import traffic_db

router = APIRouter(prefix="/api/zones", tags=["zones"])

TIPOS = ("calzada", "excluir")


class ZoneCreate(BaseModel):
    project_id: int
    name: str
    points: List[List[float]]     # mínimo 3 vértices
    kind: str = "calzada"


class ZoneUpdate(BaseModel):
    name: Optional[str] = None
    points: Optional[List[List[float]]] = None
    kind: Optional[str] = None


def _validar(points: Optional[List[List[float]]], kind: Optional[str]):
    if points is not None and len(points) < 3:
        raise HTTPException(400, "Una zona necesita al menos 3 puntos para cerrar un área")
    if kind is not None and kind not in TIPOS:
        raise HTTPException(400, f"Tipo de zona no válido: {kind}. Usa uno de {TIPOS}")


@router.get("")
def list_zones(project_id: int):
    return traffic_db.list_zones(project_id=project_id)


@router.post("")
def create_zone(zone: ZoneCreate):
    _validar(zone.points, zone.kind)
    if traffic_db.get_project(zone.project_id) is None:
        raise HTTPException(404, "Proyecto no encontrado")

    zone_id = traffic_db.create_zone(
        project_id=zone.project_id,
        name=zone.name,
        points=zone.points,
        kind=zone.kind,
    )
    return {"id": zone_id, "name": zone.name}


@router.put("/{zone_id}")
def update_zone(zone_id: int, zone: ZoneUpdate):
    _validar(zone.points, zone.kind)
    traffic_db.update_zone(zone_id, name=zone.name, kind=zone.kind, points=zone.points)
    return {"updated": zone_id}


@router.delete("/{zone_id}")
def delete_zone(zone_id: int):
    traffic_db.delete_zone(zone_id)
    return {"deleted": zone_id}
