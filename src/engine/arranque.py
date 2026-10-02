"""
Arranque de un archivo con los últimos segundos del anterior.

Un aforo de campo llega partido en archivos (de un minuto en el frontal de
Cd. Juárez, 730 al día). El vehículo que va cruzando la línea justo cuando
EMPIEZA un archivo no se contaba: el rastreador necesita ver la caja unos
cuadros antes de la línea, y al arrancar el archivo ese pasado no existe.
Medido sobre 574 videos: el segundo 0 de cada archivo trae el 80 % de los
cruces de un segundo normal, una pérdida neta de 0.3-0.5 % del aforo. Y se
ve: en el clip de presentación de las 14:56 una camioneta pasaba la línea en
el primer cuadro sin contarse.

Antes de contar un archivo se pasan por el detector y el rastreador los
últimos segundos del archivo ANTERIOR, sin registrar nada, para llegar al
cuadro 0 siguiendo ya a los vehículos. Lo que cruza en esos segundos ya lo
contó el archivo anterior, y aquí no se registra; lo que cruza después del
cuadro 0 se cuenta una sola vez, aquí.

Solo con archivos CONSECUTIVOS: si entre el final del anterior y el inicio
de este falta tiempo, el rastreador emparejaría a un vehículo con su
posición de hace segundos (o con otro), y un rastro que "sigue" entre dos
instantes que no se tocan puede cruzar la línea en falso.
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Iterator, Optional

import cv2

# Segundos del archivo anterior que se repasan. El rastreador confirma un
# rastro con 3 detecciones (min_hits) y el contador necesita verlo de un lado
# de la línea antes de verlo del otro: 3 s sobran para un vehículo que llega
# a 40-70 km/h.
SEGUNDOS_PREVIOS = 3.0
# Holgura entre el final del anterior y el inicio de este para tenerlos por
# continuos: los nombres de archivo dan la hora al segundo.
HOLGURA_S = 1.0


def archivo_previo_continuo(job: Dict) -> Optional[Dict]:
    """El video del mismo proyecto que termina justo cuando empieza este, o
    None si no hay uno continuo (o no se sabe la hora de alguno)."""
    from pathlib import Path

    from src.storage import traffic_db
    if not job.get("video_start_time") or not job.get("project_id"):
        return None
    fila = traffic_db.get_connection().execute(
        """SELECT id FROM video_jobs
           WHERE project_id = ? AND id != ? AND video_start_time IS NOT NULL
             AND video_start_time <= ?
           ORDER BY video_start_time DESC, id DESC LIMIT 1""",
        (job["project_id"], job["id"], job["video_start_time"])).fetchone()
    if fila is None:
        return None
    previo = traffic_db.get_video_job(fila[0])
    if not previo or not Path(previo["stored_path"]).exists():
        return None
    duracion = _duracion_s(previo)
    if duracion is None:
        return None
    fin = datetime.fromisoformat(previo["video_start_time"]) + timedelta(seconds=duracion)
    hueco = (datetime.fromisoformat(job["video_start_time"]) - fin).total_seconds()
    if abs(hueco) > HOLGURA_S:
        return None
    return previo


def _duracion_s(job: Dict) -> Optional[float]:
    """Duración del video: de la base si ya se contó, del archivo si no."""
    if job.get("total_frames") and job.get("fps"):
        return job["total_frames"] / job["fps"]
    cap = cv2.VideoCapture(job["stored_path"])
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    finally:
        cap.release()
    return total / fps if fps and total else None


def cuadros_finales(ruta: str, segundos: float = SEGUNDOS_PREVIOS) -> Iterator:
    """Los cuadros de los últimos `segundos` de un archivo, en orden.

    Se salta al punto con una sola búsqueda (decodifica desde el cuadro
    clave anterior, ~1 s de trabajo) en vez de leer el minuto entero.
    """
    cap = cv2.VideoCapture(ruta)
    try:
        if not cap.isOpened():
            return
        fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        desde = max(0, total - int(round(segundos * fps)))
        if desde:
            cap.set(cv2.CAP_PROP_POS_FRAMES, desde)
        n = 0
        while True:
            ok, cuadro = cap.read()
            if not ok:
                break
            yield cuadro
            n += 1
        if n == 0:
            logging.warning(f"Arranque: no se pudo leer el final de {ruta}")
    finally:
        cap.release()
