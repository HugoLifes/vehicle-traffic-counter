"""
Proyectos de aforo — una intersección/punto de medición.

Un proyecto es el dueño de todo lo demás: sus carriles calibrados, sus
videos y sus conteos. Antes esto era un texto libre que se re-escribía en
cada carga, así que un error de tipeo separaba los datos en silencio; con
el proyecto como entidad real la empresa acumula el histórico de aforos
de cada intersección a lo largo del tiempo.
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.engine.video_job_processor import get_processor
from src.storage import traffic_db

router = APIRouter(prefix="/api/projects")


class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    address: Optional[str] = None
    interval_minutes: int = 15


class CopyCalibration(BaseModel):
    from_project_id: int


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    address: Optional[str] = None
    interval_minutes: Optional[int] = None


@router.get("")
def list_projects():
    return traffic_db.list_projects()


@router.post("")
def create_project(project: ProjectCreate):
    name = project.name.strip()
    if not name:
        raise HTTPException(400, "El proyecto necesita un nombre")

    existing = [p for p in traffic_db.list_projects() if p["name"].lower() == name.lower()]
    if existing:
        raise HTTPException(409, f"Ya existe un proyecto llamado '{name}'")

    project_id = traffic_db.create_project(
        name=name,
        description=project.description,
        latitude=project.latitude,
        longitude=project.longitude,
        address=project.address,
        interval_minutes=project.interval_minutes,
    )
    return traffic_db.get_project(project_id)


@router.get("/{project_id}")
def get_project(project_id: int):
    project = traffic_db.get_project(project_id)
    if project is None:
        raise HTTPException(404, "Proyecto no encontrado")
    return project


@router.put("/{project_id}")
def update_project(project_id: int, project: ProjectUpdate):
    if traffic_db.get_project(project_id) is None:
        raise HTTPException(404, "Proyecto no encontrado")
    traffic_db.update_project(project_id, **project.model_dump(exclude_none=True))
    return traffic_db.get_project(project_id)


@router.delete("/{project_id}")
def delete_project(project_id: int):
    if traffic_db.get_project(project_id) is None:
        raise HTTPException(404, "Proyecto no encontrado")
    traffic_db.delete_project(project_id)
    return {"deleted": project_id}


@router.post("/{project_id}/copy-calibration")
def copy_calibration(project_id: int, data: CopyCalibration):
    """
    Copia los carriles y las zonas de otra intersección a esta.

    La cámara de un punto de medición no se mueve entre grabaciones, así
    que la calibración es la misma sesión tras sesión. Volver a dibujarla
    a mano cada vez no solo es trabajo repetido: es una fuente de error,
    porque dos líneas trazadas a ojo en días distintos NO quedan en el
    mismo píxel y los conteos dejan de ser comparables entre sesiones.

    Se copia la geometría, no el histórico: los conteos de la intersección
    de origen se quedan donde están.
    """
    if project_id == data.from_project_id:
        raise HTTPException(400, "El proyecto de origen y el de destino son el mismo")
    for pid in (project_id, data.from_project_id):
        if traffic_db.get_project(pid) is None:
            raise HTTPException(404, f"Proyecto {pid} no encontrado")

    destino = traffic_db.get_project(project_id)
    origen_lanes = traffic_db.list_lanes(project_id=data.from_project_id)
    origen_zones = traffic_db.list_zones(project_id=data.from_project_id)
    if not origen_lanes and not origen_zones:
        raise HTTPException(409, "La intersección de origen no tiene nada calibrado que copiar")

    # Se rechaza si el destino ya tiene algo, en vez de duplicarlo en
    # silencio: acabar con dos juegos de líneas superpuestas cuenta cada
    # vehículo dos veces y no hay nada en pantalla que lo delate.
    if traffic_db.list_lanes(project_id=project_id) or traffic_db.list_zones(project_id=project_id):
        raise HTTPException(
            409,
            "Esta intersección ya tiene carriles o zonas. Bórralos antes de copiar, "
            "para no terminar con dos juegos de líneas encimadas contando doble."
        )

    for lane in origen_lanes:
        traffic_db.create_lane(
            camera_source=destino["name"], project_id=project_id,
            name=lane["name"], line_type=lane["line_type"], points=lane["points"],
        )
    for zone in origen_zones:
        traffic_db.create_zone(
            project_id=project_id, name=zone["name"],
            points=zone["points"], kind=zone["kind"],
        )
    return {"lanes": len(origen_lanes), "zones": len(origen_zones)}


@router.post("/{project_id}/start-counting")
def start_counting(project_id: int):
    """
    Arranca el conteo de los videos que estaban esperando calibración.

    Se rechaza si el proyecto no tiene carriles definidos: contar sin
    carriles calibrados daría números que no corresponden a ningún cruce
    real de la vía, que es justo lo que este paso previo evita.
    """
    project = traffic_db.get_project(project_id)
    if project is None:
        raise HTTPException(404, "Proyecto no encontrado")

    lanes = traffic_db.list_lanes(project_id=project_id)
    if not lanes:
        raise HTTPException(
            409,
            "Este proyecto todavía no tiene carriles definidos. Dibuja al menos "
            "una línea de conteo en la pestaña Calibrar antes de empezar."
        )

    pending = traffic_db.get_awaiting_calibration_jobs(project_id)
    if not pending:
        raise HTTPException(409, "No hay videos esperando calibración en este proyecto")

    processor = get_processor()
    for job in pending:
        traffic_db.update_video_job(job["id"], status="queued")
        if processor:
            processor.enqueue(job["id"])

    return {"started": len(pending), "lanes": len(lanes)}
