"""
Lectura de cuadros arbitrarios de un video subido.

Es lo que hace posible calibrar sobre el video en movimiento en vez de
sobre un cuadro fijo del centro: el usuario puede recorrer la grabación,
pausar donde el tránsito se ve claro y dibujar ahí sus líneas.

Por qué no se sirve el archivo entero al navegador y se deja que él lo
reproduzca: los aforos llegan en .mkv, .avi o .wmv, contenedores que los
navegadores no reproducen de forma fiable, y los videos todavía sin
procesar no tienen una versión en H.264 (ese transcodificado ocurre
DESPUÉS de contar, y calibrar va antes). Transcodificar diez minutos de
video solo para poder elegir un cuadro sería mucho más caro que esto.

El costo real medido sobre el material del proyecto (640x360, 15 fps,
10 min por segmento):

    abrir + buscar + leer en cada petición   40.0 ms
    captura abierta, buscar + leer           11.7 ms
    captura abierta, cuadro siguiente         0.3 ms
    codificar JPEG calidad 80                 1.8 ms

Esa última fila es la que decide el diseño: si se mantiene la captura
abierta y se detecta que el cuadro pedido es el siguiente al anterior,
reproducir sale prácticamente gratis. Buscar solo cuesta cuando el
usuario salta con la barra de tiempo, que es justo cuando no importa.
"""

import threading
from collections import OrderedDict
from typing import Dict, Optional

import cv2
from fastapi import APIRouter, HTTPException, Response

from src.storage import traffic_db

router = APIRouter(prefix="/api/frames")

# Cuántos videos se mantienen abiertos a la vez. Cada captura abierta
# retiene un descriptor de archivo y algo de memoria del decodificador;
# tres cubre el caso real (recorrer un video mientras se comparan un par
# de segmentos vecinos) sin acumular archivos abiertos indefinidamente.
_MAX_ABIERTOS = 3

_capturas: "OrderedDict[int, dict]" = OrderedDict()
_lock = threading.Lock()


def _abrir(job_id: int) -> dict:
    """
    Devuelve la entrada de captura de un video, abriéndola si hace falta.

    La entrada guarda `siguiente`: el índice del cuadro que la captura
    entregaría con un read() sin buscar. Es lo que permite distinguir
    "reproducir" de "saltar".
    """
    entrada = _capturas.get(job_id)
    if entrada is not None:
        _capturas.move_to_end(job_id)
        return entrada

    job = traffic_db.get_video_job(job_id)
    if job is None:
        raise HTTPException(404, "Ese video no existe")

    cap = cv2.VideoCapture(job["stored_path"])
    if not cap.isOpened():
        cap.release()
        raise HTTPException(
            404,
            "No se pudo abrir el archivo de video. Puede que se haya movido o "
            "que el formato no sea legible."
        )

    entrada = {
        "cap": cap,
        "siguiente": 0,
        "fps": cap.get(cv2.CAP_PROP_FPS) or 25.0,
        "total": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0,
        "ancho": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "alto": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
    }
    _capturas[job_id] = entrada

    while len(_capturas) > _MAX_ABIERTOS:
        _, vieja = _capturas.popitem(last=False)
        vieja["cap"].release()

    return entrada


def cerrar_captura(job_id: int) -> None:
    """Suelta el archivo de un video. La llama el borrado de videos:
    en Windows no se puede eliminar un archivo que sigue abierto."""
    with _lock:
        entrada = _capturas.pop(job_id, None)
    if entrada is not None:
        entrada["cap"].release()


def _metadatos(job: Dict) -> Optional[Dict]:
    """Duración y dimensiones de un video, leídas de su cabecera."""
    cap = cv2.VideoCapture(job["stored_path"])
    if not cap.isOpened():
        cap.release()
        return None
    fps = cap.get(cv2.CAP_PROP_FPS) or 0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    ancho = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    alto = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    if not fps or not total:
        return None
    return {
        "job_id": job["id"],
        "nombre": job["original_name"],
        "estado": job["status"],
        "fps": round(fps, 3),
        "total_frames": total,
        "duracion_s": round(total / fps, 2),
        "ancho": ancho,
        "alto": alto,
        "hora_inicio": job.get("video_start_time"),
    }


@router.get("/videos")
def listar_videos(project_id: int):
    """
    Videos de una intersección con lo necesario para armar la línea de
    tiempo: duración, fps y dimensiones.

    Se saltan los que no se pueden abrir en vez de fallar la petición
    entera: un archivo dañado no debería impedir calibrar sobre los demás.
    """
    if traffic_db.get_project(project_id) is None:
        raise HTTPException(404, "Esa intersección no existe")

    salida = []
    for job in traffic_db.get_video_jobs_by_project(project_id):
        meta = _metadatos(job)
        if meta is not None:
            salida.append(meta)
    return salida


@router.get("/frame")
def obtener_frame(job_id: int, frame: int = 0, calidad: int = 80):
    """
    Un cuadro concreto del video, por índice.

    Va por índice de cuadro y no por segundos a propósito: calibrar exige
    poder avanzar de uno en uno para encontrar el instante en que el
    vehículo cruza, y con segundos en coma flotante el mismo valor puede
    caer en un cuadro o en el siguiente según cómo redondee.
    """
    with _lock:
        entrada = _abrir(job_id)
        cap = entrada["cap"]
        total = entrada["total"]

        if total and frame >= total:
            frame = total - 1
        if frame < 0:
            frame = 0

        # Si el cuadro pedido es justo el siguiente, no se busca: leer de
        # corrido cuesta 0.3 ms contra 11.7 ms de una búsqueda. Es lo que
        # hace que reproducir se sienta fluido.
        if frame != entrada["siguiente"]:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame)

        ok, imagen = cap.read()

        if not ok:
            # La cola del archivo no siempre es alcanzable. En MKV (que es
            # como llegan estos aforos) el total de cuadros de la cabecera
            # está estimado a partir de la duración por los fps, y suele
            # sobrar: en el material de este proyecto declara 9001 cuadros
            # y solo 8988 se pueden leer.
            #
            # Arrastrar la barra hasta el final es lo más normal del mundo,
            # así que en vez de devolver un error se retrocede al cuadro
            # legible más cercano. El retroceso crece al doble cada vez
            # para no gastar una búsqueda por cuadro: nueve intentos cubren
            # 128 cuadros y cuestan poco más de 100 ms, y solo ocurre en la
            # cola del video.
            for retroceso in (1, 2, 4, 8, 16, 32, 64, 128):
                candidato = frame - retroceso
                if candidato < 0:
                    break
                cap.set(cv2.CAP_PROP_POS_FRAMES, candidato)
                ok, imagen = cap.read()
                if ok:
                    frame = candidato
                    break

        if not ok:
            entrada["siguiente"] = 0
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            raise HTTPException(416, "No hay ningún cuadro legible en esa posición")

        entrada["siguiente"] = frame + 1
        fps = entrada["fps"]
        alto, ancho = imagen.shape[:2]

    ok, buf = cv2.imencode(".jpg", imagen, [cv2.IMWRITE_JPEG_QUALITY, max(30, min(95, calidad))])
    if not ok:
        raise HTTPException(500, "No se pudo codificar el cuadro")

    return Response(
        content=buf.tobytes(),
        media_type="image/jpeg",
        headers={
            # El cliente necesita saber qué cuadro recibió de verdad: pudo
            # pedir uno más allá del final y recibir el último.
            "X-Frame-Index": str(frame),
            "X-Frame-Time": f"{frame / fps:.3f}",
            "X-Video-Fps": f"{fps:.3f}",
            "X-Video-Total-Frames": str(total),
            "X-Video-Width": str(ancho),
            "X-Video-Height": str(alto),
            # Cada cuadro es inmutable: el mismo índice del mismo video da
            # siempre la misma imagen, así que el navegador puede
            # guardarlo y el recorrido hacia atrás sale de su caché.
            "Cache-Control": "private, max-age=3600",
        },
    )
