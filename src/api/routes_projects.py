"""
Proyectos de aforo — una intersección/punto de medición.

Un proyecto es el dueño de todo lo demás: sus carriles calibrados, sus
videos y sus conteos. Antes esto era un texto libre que se re-escribía en
cada carga, así que un error de tipeo separaba los datos en silencio; con
el proyecto como entidad real la empresa acumula el histórico de aforos
de cada intersección a lo largo del tiempo.
"""

import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.api.routes_video_frames import cerrar_captura
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
    traffic_db.log_event(project_id, "proyecto", "Se creó la intersección", name)
    return traffic_db.get_project(project_id)


@router.get("/{project_id}")
def get_project(project_id: int):
    project = traffic_db.get_project(project_id)
    if project is None:
        raise HTTPException(404, "Proyecto no encontrado")
    return project


@router.put("/{project_id}")
def update_project(project_id: int, project: ProjectUpdate):
    antes = traffic_db.get_project(project_id)
    if antes is None:
        raise HTTPException(404, "Proyecto no encontrado")

    cambios = project.model_dump(exclude_none=True)
    traffic_db.update_project(project_id, **cambios)

    # Se anota QUÉ cambió, no solo que hubo un cambio: "se editó el
    # proyecto" no ayuda a explicar por qué dos reportes difieren.
    detalle = ", ".join(
        f"{campo}: '{antes.get(campo)}' → '{valor}'"
        for campo, valor in cambios.items()
        if antes.get(campo) != valor
    )
    if detalle:
        traffic_db.log_event(project_id, "proyecto", "Se editaron los datos", detalle)
    return traffic_db.get_project(project_id)


@router.delete("/{project_id}")
def delete_project(project_id: int):
    if traffic_db.get_project(project_id) is None:
        raise HTTPException(404, "Proyecto no encontrado")

    # Los videos abiertos por el visor de cuadros hay que cerrarlos antes
    # de borrar el archivo: en Windows no se puede eliminar un archivo que
    # otro proceso tiene abierto, y el borrado fallaría a medias.
    for job in traffic_db.list_video_jobs(project_id=project_id):
        cerrar_captura(job["id"])

    borrados = traffic_db.delete_project(project_id)

    eliminados = 0
    for ruta in borrados.pop("archivos", []):
        try:
            Path(ruta).unlink(missing_ok=True)
            eliminados += 1
        except OSError as e:
            # Que un archivo quede atrás no debe abortar el borrado: el
            # proyecto ya no existe en la base y eso es lo que importa.
            logging.warning(f"No se pudo borrar {ruta}: {e}")
    borrados["archivos_eliminados"] = eliminados
    return {"deleted": project_id, **borrados}


@router.get("/{project_id}/calibration-status")
def calibration_status(project_id: int):
    """
    Si los conteos ya hechos corresponden a la calibración actual.

    Editar las líneas después de procesar no cambia nada por sí solo: los
    cruces guardados siguen siendo los de la geometría anterior, y el
    video anotado sigue teniendo las líneas viejas quemadas en la imagen.
    Sin este dato no había forma de notarlo desde la interfaz — y como el
    botón de contar solo aparece cuando hay videos esperando, un proyecto
    ya procesado tampoco se podía volver a contar.
    """
    if traffic_db.get_project(project_id) is None:
        raise HTTPException(404, "Proyecto no encontrado")
    obsoletos = traffic_db.get_stale_jobs(project_id)
    return {
        "calibrated_at": traffic_db.get_calibration_time(project_id),
        "stale": len(obsoletos),
        "awaiting": len(traffic_db.get_awaiting_calibration_jobs(project_id)),
    }


@router.post("/{project_id}/recount")
def recount(project_id: int):
    """
    Vuelve a contar los videos ya procesados con la calibración actual.

    Los cruces anteriores de cada video se borran al reprocesarlo (lo hace
    el propio procesador con delete_crossings_for_job), así que los
    conteos se reemplazan en vez de sumarse.
    """
    if traffic_db.get_project(project_id) is None:
        raise HTTPException(404, "Proyecto no encontrado")
    if not traffic_db.list_lanes(project_id=project_id):
        raise HTTPException(409, "Este proyecto no tiene carriles definidos")

    # Se reprocesan TODOS los terminados, no solo los obsoletos: si el
    # usuario pide volver a contar, lo que quiere es que el aforo completo
    # salga de una sola calibración.
    conn_jobs = [
        j for j in traffic_db.list_video_jobs(project_id=project_id)
        if j["status"] == "done"
    ]
    if not conn_jobs:
        raise HTTPException(409, "Este proyecto no tiene videos procesados que volver a contar")

    processor = get_processor()
    for job in conn_jobs:
        traffic_db.update_video_job(job["id"], status="queued", processed_frames=0)
        if processor:
            processor.enqueue(job["id"])
    traffic_db.log_event(
        project_id, "conteo", "Se volvió a contar todo",
        f"{len(conn_jobs)} videos reencolados con la calibración actual",
    )
    return {"requeued": len(conn_jobs)}


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
    origen = traffic_db.get_project(data.from_project_id)
    traffic_db.log_event(
        project_id, "calibracion", "Se copió la calibración de otra intersección",
        f"Desde '{origen['name']}': {len(origen_lanes)} carriles, {len(origen_zones)} zonas",
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
