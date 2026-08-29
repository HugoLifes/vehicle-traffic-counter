"""
Snapshot de un frame para calibrar los carriles.

Para un proyecto con videos subidos, abre uno de sus archivos y toma un
frame de la mitad — no hace falta procesar el video para poder calibrar
sobre él, que es justo el punto de calibrar ANTES de contar. Para la
cámara en vivo, usa el último frame que ya tiene el motor en memoria.
"""

import cv2
from fastapi import APIRouter, HTTPException, Response

from src.engine.counting_service import get_service
from src.storage import traffic_db

router = APIRouter(prefix="/api/camera")


def _frame_from_project_videos(project_id: int):
    jobs = traffic_db.get_video_jobs_by_project(project_id)
    for job in jobs:
        cap = cv2.VideoCapture(job["stored_path"])
        if not cap.isOpened():
            cap.release()
            continue
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
        cap.set(cv2.CAP_PROP_POS_FRAMES, total // 2)
        ret, frame = cap.read()
        cap.release()
        if ret:
            return frame
    return None


@router.get("/snapshot")
def snapshot(project_id: int):
    project = traffic_db.get_project(project_id)
    if project is None:
        raise HTTPException(404, "Proyecto no encontrado")

    frame = _frame_from_project_videos(project_id)

    # Si el proyecto no tiene videos, quizá es la cámara en vivo
    if frame is None:
        service = get_service()
        if service and service.camera_source == project["name"]:
            frame = service.get_latest_frame()

    if frame is None:
        raise HTTPException(
            404,
            "No hay un frame disponible para este proyecto todavía. "
            "Sube al menos un video para poder calibrar sobre él."
        )

    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise HTTPException(500, "No se pudo codificar el frame")
    return Response(content=buf.tobytes(), media_type="image/jpeg")


# Cachear el mapa de movimiento: recorrer el video cuesta varios segundos y
# la página de calibración lo puede pedir varias veces.
_heatmap_cache: dict = {}


@router.get("/heatmap")
def heatmap(project_id: int):
    """
    Mapa de por dónde pasan realmente los vehículos, acumulando la
    diferencia entre cuadros a lo largo del video.

    Existe porque el error de calibración más costoso no es dibujar mal la
    línea, sino dibujarla donde no pasa nadie — o peor, PARALELA al sentido
    de circulación, con lo que los vehículos avanzan a lo largo de la línea
    en vez de cruzarla y el conteo sale casi en cero. Viendo el rastro del
    tránsito antes de dibujar, esa clase de error se vuelve evidente.
    """
    if project_id in _heatmap_cache:
        return Response(content=_heatmap_cache[project_id], media_type="image/jpeg")

    jobs = traffic_db.get_video_jobs_by_project(project_id)
    if not jobs:
        raise HTTPException(404, "Este proyecto todavía no tiene videos")

    cap = cv2.VideoCapture(jobs[0]["stored_path"])
    if not cap.isOpened():
        cap.release()
        raise HTTPException(404, "No se pudo abrir el video del proyecto")

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    # Muestreo espaciado: con ~150 comparaciones repartidas por todo el video
    # el rastro ya queda nítido, y evita leerlo entero (que en un clip de 10
    # min tarda demasiado para una petición web).
    step = max(1, total // 150) if total else 30

    import numpy as np

    acc = None
    prev = None
    frames_used = 0
    for idx in range(0, total or 4500, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if not ret:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
        if prev is not None:
            diff = cv2.absdiff(gray, prev)
            acc = diff if acc is None else acc + diff
            frames_used += 1
        prev = gray
    cap.release()

    if acc is None or frames_used == 0:
        raise HTTPException(404, "No se pudo analizar el movimiento del video")

    acc /= frames_used
    # Realce: el tránsito nocturno deja diferencias débiles que sin amplificar
    # no se distinguirían del ruido del sensor.
    acc = np.clip(acc * 6, 0, 255).astype("uint8")
    colored = cv2.applyColorMap(acc, cv2.COLORMAP_JET)

    ok, buf = cv2.imencode(".jpg", colored, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        raise HTTPException(500, "No se pudo generar el mapa de movimiento")

    _heatmap_cache[project_id] = buf.tobytes()
    return Response(content=_heatmap_cache[project_id], media_type="image/jpeg")
