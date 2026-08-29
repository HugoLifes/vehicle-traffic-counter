"""
Subida y gestión de videos para procesamiento por lote (no en vivo).

Acepta uno o varios archivos a la vez (drag-and-drop o selector),
valida el formato y los guarda en data/uploads/ asociados a un proyecto.
Los videos NO se procesan al subirlos: quedan esperando a que el usuario
calibre los carriles y presione "Empezar conteo".
"""

import json
import logging
import re
import uuid

import cv2
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse

from src.engine.video_job_processor import get_processor
from src.storage import traffic_db, traffic_metrics

router = APIRouter(prefix="/api/videos")

UPLOAD_DIR = Path("data/uploads")

# Formatos soportados: cualquiera que OpenCV/ffmpeg puedan decodificar,
# incluyendo .mkv (probado explícitamente con H.264 en contenedor Matroska).
ALLOWED_EXTENSIONS = {
    ".mp4", ".avi", ".mov", ".mkv", ".webm",
    ".flv", ".wmv", ".m4v", ".mpg", ".mpeg"
}


def _safe_stored_path(original_name: str) -> Path:
    ext = Path(original_name).suffix.lower()
    safe_stem = Path(original_name).stem.replace("/", "_").replace("\\", "_")[:80]
    unique_name = f"{uuid.uuid4().hex[:8]}_{safe_stem}{ext}"
    return UPLOAD_DIR / unique_name


@router.post("/upload")
async def upload_videos(
    files: List[UploadFile] = File(...),
    project_id: int = Form(...),
    start_times: str = Form("{}"),
):
    """
    Sube uno o varios videos a un proyecto. Los archivos con formato no
    soportado se rechazan individualmente sin tumbar el resto del lote.

    Los videos quedan en 'awaiting_calibration' — NO se procesan aquí.
    El usuario define los carriles sobre un frame real y luego presiona
    "Empezar conteo" (POST /api/projects/{id}/start-counting).

    Todos los videos de un mismo proyecto comparten sus carriles, así que
    varios segmentos de la misma hora se unen en un solo reporte por
    intervalos.

    start_times: JSON {nombre_de_archivo: "YYYY-MM-DD HH:MM:SS"} — hora
        real en que empieza cada video (no cuándo se sube/procesa).
        Es lo que permite construir el reporte 8:00-8:15, 8:15-8:30...
    """
    project = traffic_db.get_project(project_id)
    if project is None:
        raise HTTPException(404, "Proyecto no encontrado")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    try:
        start_time_map = json.loads(start_times) if start_times else {}
    except json.JSONDecodeError:
        start_time_map = {}

    accepted = []
    rejected = []

    for upload in files:
        ext = Path(upload.filename or "").suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            rejected.append({
                "filename": upload.filename,
                "reason": f"Formato '{ext or 'desconocido'}' no soportado. "
                          f"Formatos aceptados: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            })
            continue

        stored_path = _safe_stored_path(upload.filename)
        size_bytes = 0
        try:
            with open(stored_path, "wb") as out_file:
                while chunk := await upload.read(1024 * 1024):
                    out_file.write(chunk)
                    size_bytes += len(chunk)
        except Exception as e:
            logging.exception(f"Error guardando {upload.filename}")
            rejected.append({"filename": upload.filename, "reason": f"Error al guardar: {e}"})
            continue

        job_id = traffic_db.create_video_job(
            original_name=upload.filename,
            stored_path=str(stored_path),
            size_bytes=size_bytes,
            source_label=project["name"],
            project_id=project_id,
            video_start_time=start_time_map.get(upload.filename),
            interval_minutes=project["interval_minutes"],
            status="awaiting_calibration",
        )
        accepted.append(traffic_db.get_video_job(job_id))

    return {"accepted": accepted, "rejected": rejected}


@router.get("")
def list_videos(project_id: Optional[int] = None):
    return traffic_db.list_video_jobs(project_id=project_id)


@router.get("/report")
def get_interval_report(project_id: int, minutes: int = 15):
    return traffic_db.get_interval_counts(project_id, minutes)


@router.get("/metrics")
def get_metrics(project_id: int, minutes: int = 15):
    """Métricas de ingeniería de tránsito: FHP, hora pico, composición."""
    return traffic_metrics.get_project_metrics(project_id, minutes)


@router.delete("/{job_id}")
def delete_video(job_id: int):
    from src.api.routes_video_frames import cerrar_captura

    job = traffic_db.get_video_job(job_id)
    if job is None:
        raise HTTPException(404, "Video no encontrado")
    if job["status"] == "processing":
        raise HTTPException(409, "No se puede borrar un video que se está procesando ahora mismo")

    # La mesa de calibración deja el archivo abierto para poder recorrerlo
    # cuadro a cuadro. En Windows no se puede borrar un archivo abierto, así
    # que primero se suelta.
    cerrar_captura(job_id)

    for path_str in (job["stored_path"], job.get("output_video_path")):
        if path_str:
            path = Path(path_str)
            if path.exists():
                path.unlink()
    traffic_db.delete_video_job(job_id)
    return {"deleted": job_id}


RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


@router.get("/live-frame")
def live_frame():
    """
    Último cuadro anotado del video que se está procesando ahora mismo.
    Permite ver en vivo lo que la IA está detectando, en vez de esperar a
    que termine el archivo completo. Devuelve 204 cuando no hay nada
    procesándose (el visor lo interpreta como "en reposo", no como error).
    """
    processor = get_processor()
    if processor is None:
        return Response(status_code=204)

    frame, job_id = processor.get_live_frame()
    if frame is None:
        return Response(status_code=204)

    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
    if not ok:
        return Response(status_code=204)

    return Response(
        content=buf.tobytes(),
        media_type="image/jpeg",
        headers={"X-Job-Id": str(job_id), "Cache-Control": "no-store"},
    )


@router.get("/{job_id}/video")
def get_video(job_id: int, request: Request):
    """
    Sirve el video anotado (cajas, IDs, línea de conteo) para que el
    usuario vea qué detectó la IA. Soporta 'Range' porque el <video>
    del navegador lo necesita para poder adelantar/atrasar.
    """
    job = traffic_db.get_video_job(job_id)
    if job is None or not job.get("output_video_path"):
        raise HTTPException(404, "Todavía no hay video procesado para este trabajo")

    path = Path(job["output_video_path"])
    if not path.exists():
        raise HTTPException(404, "El archivo de video ya no existe en disco")

    file_size = path.stat().st_size
    range_header = request.headers.get("range")

    start, end = 0, file_size - 1
    status_code = 200
    if range_header:
        match = RANGE_RE.match(range_header)
        if match:
            if match.group(1):
                start = int(match.group(1))
            if match.group(2):
                end = int(match.group(2))
            status_code = 206

    chunk_size = end - start + 1

    def iterfile():
        with open(path, "rb") as f:
            f.seek(start)
            remaining = chunk_size
            while remaining > 0:
                data = f.read(min(1024 * 1024, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(chunk_size),
    }
    return StreamingResponse(iterfile(), status_code=status_code, media_type="video/mp4", headers=headers)
