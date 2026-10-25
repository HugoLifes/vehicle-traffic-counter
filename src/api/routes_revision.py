"""
Cola de vehículos a revisar (src/engine/revision.py): los dudosos de un
proyecto con su recorte, y lo que decide quien revisa.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from src.engine import revision
from src.storage import traffic_db

router = APIRouter(prefix="/api/projects", tags=["revision"])


class Decision(BaseModel):
    tipo: str          # 'cruce' | 'movimiento'
    id: int
    decision: str      # una clase de `opciones`, o 'descartar'


def _proyecto(project_id: int):
    if not traffic_db.get_project(project_id):
        raise HTTPException(404, "Proyecto no encontrado")


@router.get("/{project_id}/revision")
def cola(project_id: int, motivo: Optional[str] = None, limite: int = 40, desde: int = 0):
    _proyecto(project_id)
    if motivo and motivo not in revision.PRIORIDAD:
        raise HTTPException(400, f"Motivo desconocido: {motivo}")
    return revision.cola(project_id, motivo=motivo, limite=max(1, min(limite, 200)),
                         desde=max(0, desde))


@router.post("/{project_id}/revision")
def decidir(project_id: int, d: Decision):
    _proyecto(project_id)
    try:
        return revision.decidir(project_id, d.tipo, d.id, d.decision)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{project_id}/revision/quitar-dobles")
def quitar_dobles(project_id: int):
    _proyecto(project_id)
    return revision.quitar_dobles(project_id)


@router.post("/{project_id}/revision/devolver-dobles")
def devolver_dobles(project_id: int):
    _proyecto(project_id)
    return revision.devolver_dobles(project_id)


@router.post("/{project_id}/revision/restaurar/{descartado_id}")
def restaurar(project_id: int, descartado_id: int):
    _proyecto(project_id)
    try:
        traffic_db.restaurar_descartado(project_id, descartado_id)
    except KeyError as e:
        raise HTTPException(404, str(e))
    return {"ok": True}


@router.get("/{project_id}/revision/recorte/{tipo}/{item_id}.jpg")
def recorte(project_id: int, tipo: str, item_id: int, pareja: Optional[int] = None):
    _proyecto(project_id)
    if tipo not in ("cruce", "movimiento"):
        raise HTTPException(400, "tipo debe ser 'cruce' o 'movimiento'")
    datos = revision.recorte_jpeg(tipo, item_id, pareja)
    if datos is None:
        raise HTTPException(404, "No se pudo leer ese cuadro del video")
    # El recorte de un vehículo no cambia: el navegador lo puede guardar.
    return Response(datos, media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=86400"})
