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
