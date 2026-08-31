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
from src.engine.zones import (band_from_zones, filter_detections, load_zones,
                              zone_for_bbox)

router = APIRouter(prefix="/api/frames")

# Detector propio de la vista previa, aparte del que usa la cola de
# procesamiento: compartirlo obligaría a cambiarle la banda de detección
# en cada petición mientras está a media inferencia de otro video.
_detector = None
_detector_lock = threading.Lock()


def _detector_de_vista():
    global _detector
    with _detector_lock:
        if _detector is None:
            import yaml
            from src.detector import VehicleDetector
            with open("configs/platform.yaml", encoding="utf-8") as fh:
                cfg = yaml.safe_load(fh)
            det_cfg = cfg.get("detector", {})
            _detector = VehicleDetector(
                model_path=cfg.get("model_path", "models/yolov8s.pt"),
                confidence_threshold=cfg.get("confidence_threshold", 0.25),
                iou_threshold=det_cfg.get("iou_threshold", 0.5),
                input_size=det_cfg.get("input_size", 1280),
                device=cfg.get("device", "auto"),
                config=det_cfg,
            )
        return _detector

# Cuántos videos se mantienen abiertos a la vez. Cada captura abierta
# retiene un descriptor de archivo y algo de memoria del decodificador;
# tres cubre el caso real (recorrer un video mientras se comparan un par
# de segmentos vecinos) sin acumular archivos abiertos indefinidamente.
_MAX_ABIERTOS = 3

# La clave incluye la fuente: el mismo aforo tiene dos videos, el
# original y el anotado por la IA, y se recorren de forma independiente.
_capturas: "OrderedDict[tuple, dict]" = OrderedDict()
_lock = threading.Lock()

FUENTES = ("original", "procesado")


def _ruta(job: Dict, fuente: str) -> Optional[str]:
    if fuente == "procesado":
        return job.get("output_video_path")
    return job["stored_path"]


def _abrir(job_id: int, fuente: str) -> dict:
    """
    Devuelve la entrada de captura de un video, abriéndola si hace falta.

    La entrada guarda `siguiente`: el índice del cuadro que la captura
    entregaría con un read() sin buscar. Es lo que permite distinguir
    "reproducir" de "saltar".
    """
    clave = (job_id, fuente)
    entrada = _capturas.get(clave)
    if entrada is not None:
        _capturas.move_to_end(clave)
        return entrada

    job = traffic_db.get_video_job(job_id)
    if job is None:
        raise HTTPException(404, "Ese video no existe")

    ruta = _ruta(job, fuente)
    if not ruta:
        raise HTTPException(
            404,
            "Este video todavía no tiene versión con detecciones. Aparece "
            "cuando termina el conteo."
        )

    cap = cv2.VideoCapture(ruta)
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
    _capturas[clave] = entrada

    while len(_capturas) > _MAX_ABIERTOS:
        _, vieja = _capturas.popitem(last=False)
        vieja["cap"].release()

    return entrada


def cerrar_captura(job_id: int) -> None:
    """Suelta los archivos de un video, en sus dos fuentes. La llama el
    borrado de videos: en Windows no se puede eliminar un archivo que
    sigue abierto por el propio proceso."""
    with _lock:
        entradas = [_capturas.pop((job_id, f), None) for f in FUENTES]
    for entrada in entradas:
        if entrada is not None:
            entrada["cap"].release()


def _metadatos(job: Dict) -> Optional[Dict]:
    """Duración y dimensiones de un video, leídas de su cabecera."""
    from pathlib import Path as _Path

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
        # Se comprueba el archivo, no solo el estado del trabajo: un job
        # puede figurar como terminado y haber perdido su salida (borrada a
        # mano, disco lleno a mitad del transcodificado). Ofrecer una
        # pestaña que después falla es peor que no ofrecerla.
        "tiene_procesado": bool(
            job.get("output_video_path") and _Path(job["output_video_path"]).exists()
        ),
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
def obtener_frame(job_id: int, frame: int = 0, fuente: str = "original", calidad: int = 80):
    """
    Un cuadro concreto del video, por índice.

    Va por índice de cuadro y no por segundos a propósito: calibrar exige
    poder avanzar de uno en uno para encontrar el instante en que el
    vehículo cruza, y con segundos en coma flotante el mismo valor puede
    caer en un cuadro o en el siguiente según cómo redondee.

    `fuente` elige entre la grabación original y la versión que dibujó la
    IA. Recorrer la segunda con los mismos controles es lo que permite
    parar en el cuadro exacto de un cruce y comprobar si se contó.
    """
    if fuente not in FUENTES:
        raise HTTPException(400, f"Fuente desconocida. Usa una de: {', '.join(FUENTES)}")

    with _lock:
        entrada = _abrir(job_id, fuente)
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
            "X-Video-Source": fuente,
            # Cada cuadro es inmutable: el mismo índice del mismo video da
            # siempre la misma imagen, así que el navegador puede
            # guardarlo y el recorrido hacia atrás sale de su caché.
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.get("/detections")
def detecciones_de_cuadro(job_id: int, frame: int = 0):
    """
    Lo que el detector encuentra AHORA en un cuadro del video original.

    Existe porque la única forma de ver las detecciones era el video
    procesado, y ese archivo tiene las cajas y las líneas quemadas en la
    imagen desde que se procesó: si después se recalibró, muestra la
    geometría vieja y no hay manera de dibujar encima. De ahí la confusión
    de ver "otras líneas" al cambiar de vista.

    Esto devuelve las cajas como datos, calculadas en el momento con el
    modelo y las zonas actuales, para pintarlas sobre el video original —
    donde las líneas SÍ se pueden seguir editando. Sirve además para
    comprobar una calibración antes de gastar una hora reprocesando.
    """
    job = traffic_db.get_video_job(job_id)
    if job is None:
        raise HTTPException(404, "Video no encontrado")

    with _lock:
        entrada = _abrir(job_id, "original")
        cap = entrada["cap"]
        total = entrada["total"]
        if total and frame >= total:
            frame = total - 1
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, frame))
        ok, imagen = cap.read()
        # La captura compartida queda en otra posición: se marca para que
        # la lectura secuencial del reproductor no crea que va al día.
        entrada["siguiente"] = -1

    if not ok:
        raise HTTPException(416, "No hay ningún cuadro legible en esa posición")

    alto = imagen.shape[0]
    zonas = load_zones(job.get("project_id"))
    detector = _detector_de_vista()
    banda = band_from_zones(zonas, alto) if zonas else None
    detector.set_detection_band(banda)

    crudas, _ = detector.detect(imagen)
    dentro = filter_detections(zonas, crudas)
    ids_dentro = {id(d) for d in dentro}

    return {
        "frame": frame,
        "detections": [
            {
                "bbox": [round(v, 1) for v in d["bbox"]],
                "confidence": round(d["confidence"], 3),
                "class_name": d["class_name"],
                # Las descartadas por zona se devuelven marcadas en vez de
                # omitirse: ver QUÉ se está tirando es justo lo que permite
                # notar una zona mal dibujada antes de reprocesar.
                "en_zona": id(d) in ids_dentro,
                "zona_id": zone_for_bbox(zonas, d["bbox"]) if zonas else None,
            }
            for d in crudas
        ],
    }
