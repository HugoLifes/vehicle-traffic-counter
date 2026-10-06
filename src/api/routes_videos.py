"""
Subida y gestión de videos para procesamiento por lote (no en vivo).

Acepta uno o varios archivos a la vez (drag-and-drop o selector),
valida el formato y los guarda en data/uploads/ asociados a un proyecto.
Los videos NO se procesan al subirlos: quedan esperando a que el usuario
calibre los carriles y presione "Empezar conteo".
"""

import asyncio
import json
import logging
import re
import uuid

import cv2
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse

from src.engine.video_job_processor import get_processor
from src.storage import disco_videos, traffic_db, traffic_metrics

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
    # Sin los caracteres que NTFS no acepta: los videos viven en un disco
    # externo con NTFS, y un nombre con ':' o '?' fallaría al guardar.
    safe_stem = re.sub(r'[/\\:*?"<>|]', "_", Path(original_name).stem)[:80]
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
    _exigir_disco()

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

    if accepted:
        traffic_db.log_event(
            project_id, "video",
            f"Se subieron {len(accepted)} videos" if len(accepted) > 1 else "Se subió un video",
            ", ".join(a["original_name"] for a in accepted[:8])
            + (f" y {len(accepted) - 8} más" if len(accepted) > 8 else ""),
        )
    return {"accepted": accepted, "rejected": rejected}


# --- Subida por pedazos --------------------------------------------------
#
# Un video de campo pesa 3.3 GB y por la dirección pública sube a ~1 MB/s:
# casi una hora en UNA petición. Cualquier corte —un reinicio de la
# plataforma, un tropiezo de la red— la tiraba entera y la pantalla decía
# "el servidor respondió 502" sin que nada llegara (1-oct-2026). Por pedazos,
# un corte cuesta un pedazo: el navegador lo reintenta, y si se cierra la
# página, volver a elegir el mismo archivo sigue donde se quedó.

PARCIALES = UPLOAD_DIR / "parciales"
PEDAZO_MAXIMO = 64 * 1024 * 1024
# Lo que quedó a medias y nadie retomó en este tiempo se borra.
VIGENCIA_PARCIAL_S = 3 * 24 * 3600
_ID_SUBIDA = re.compile(r"^[0-9a-f]{32}$")


def _ruta_parcial(subida_id: str) -> Path:
    if not _ID_SUBIDA.match(subida_id):
        raise HTTPException(400, "Identificador de subida inválido")
    return PARCIALES / f"{subida_id}.part"


def _limpiar_parciales():
    import time
    ahora = time.time()
    for p in PARCIALES.glob("*"):
        try:
            if ahora - p.stat().st_mtime > VIGENCIA_PARCIAL_S:
                p.unlink()
        except OSError:
            pass


# El mismo archivo no se escribe dos veces a la vez. Con un doble clic en
# "Subir" (o dos pestañas, o un pedazo que el navegador dio por perdido pero
# el relevo de internet seguía entregando) dos subidas del mismo archivo caían
# en el mismo parcial: una tumbaba a la otra con 409 en cada pedazo y al final
# a una de las dos le salía "No se pudo subir. [object Object]" (2-oct-2026,
# los primeros videos de Juárez). Un candado por subida: la segunda espera.
_candados: Dict[str, asyncio.Lock] = {}
_FORMATO_INICIO = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2})(?::(\d{2}))?$")


def _exigir_disco():
    """Sin el disco de videos (o sin espacio) no se acepta nada: ver
    src/storage/disco_videos.py."""
    problema = disco_videos.problema_para_subir()
    if problema:
        raise HTTPException(507, detail={"mensaje": problema})


@router.get("/almacenamiento")
def almacenamiento():
    """Dónde y cuánto cabe: la pantalla de Subir avisa si el disco de los
    videos no está conectado o se está llenando."""
    return disco_videos.estado()


def _candado(subida_id: str) -> asyncio.Lock:
    return _candados.setdefault(subida_id, asyncio.Lock())


def _job_de_subida(subida_id: str) -> Optional[dict]:
    """El video que ya registró esta subida, si lo hay: volver a terminarla
    (otra pestaña, un reintento) devuelve ese mismo video en vez de fallar o
    duplicarlo."""
    fila = traffic_db.get_connection().execute(
        "SELECT id FROM video_jobs WHERE subida_id = ? ORDER BY id LIMIT 1", (subida_id,)).fetchone()
    return traffic_db.get_video_job(fila[0]) if fila else None


def _inicio_valido(inicio) -> Optional[str]:
    """'AAAA-MM-DD HH:MM[:SS]' normalizado a segundos; None si viene vacío.
    Una hora mal escrita se rechaza con su motivo: un video sin hora no cae en
    ningún intervalo del reporte."""
    if not inicio:
        return None
    m = _FORMATO_INICIO.match(str(inicio).strip())
    if not m or int(m.group(2)) > 23 or int(m.group(3)) > 59 or int(m.group(4) or 0) > 59:
        raise HTTPException(400, detail={"mensaje": f"La hora de inicio «{inicio}» no es válida; "
                                                     "usa fecha y hora, por ejemplo 2026-09-19 14:56:00."})
    return f"{m.group(1)} {m.group(2)}:{m.group(3)}:{m.group(4) or '00'}"


@router.post("/subida/iniciar")
def iniciar_subida(datos: dict):
    """Abre (o retoma) la subida de un archivo. Devuelve cuántos bytes ya
    tiene el servidor: 0 si es nueva, más si se está retomando, y el tamaño
    completo con `ya_subido` si este mismo archivo ya quedó registrado.

    La identidad sale del proyecto, el nombre, el tamaño y la fecha del
    archivo en el equipo de quien sube: el mismo archivo elegido otra vez
    cae en la misma subida."""
    import hashlib
    proyecto_id = int(datos.get("project_id") or 0)
    nombre = str(datos.get("nombre") or "")
    tamano = int(datos.get("tamano") or 0)
    if traffic_db.get_project(proyecto_id) is None:
        raise HTTPException(404, detail={"mensaje": "La intersección ya no existe."})
    ext = Path(nombre).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(415, detail={"mensaje": f"Formato '{ext or 'desconocido'}' no soportado. "
                                         f"Formatos aceptados: {', '.join(sorted(ALLOWED_EXTENSIONS))}"})
    if tamano <= 0:
        raise HTTPException(400, detail={"mensaje": "El archivo está vacío."})
    _inicio_valido(datos.get("inicio"))
    _exigir_disco()
    PARCIALES.mkdir(parents=True, exist_ok=True)
    _limpiar_parciales()
    clave = f"{proyecto_id}|{nombre}|{tamano}|{datos.get('modificado') or ''}"
    subida_id = hashlib.sha256(clave.encode()).hexdigest()[:32]
    hecho = _job_de_subida(subida_id)
    if hecho is not None:
        return {"subida_id": subida_id, "recibido": tamano, "ya_subido": hecho["id"]}
    ruta = _ruta_parcial(subida_id)
    recibido = ruta.stat().st_size if ruta.exists() else 0
    if recibido > tamano and not _candado(subida_id).locked():
        ruta.unlink()
        recibido = 0
    return {"subida_id": subida_id, "recibido": min(recibido, tamano)}


async def _rechazar(request: Request, codigo: int, detalle: dict):
    """Rechaza un pedazo DESPUÉS de leerlo. Contestar sin leer el cuerpo
    cierra la conexión con el pedazo a medio enviar, y el navegador no ve el
    409 sino "conexión anulada": nunca se entera de que debía esperar o
    seguir desde otro punto (medido por la dirección pública, 5-oct-2026)."""
    leido = 0
    async for trozo in request.stream():
        leido += len(trozo)
        if leido > PEDAZO_MAXIMO:
            break
    raise HTTPException(codigo, detail=detalle)


@router.put("/subida/{subida_id}")
async def recibir_pedazo(subida_id: str, offset: int, request: Request):
    """Un pedazo del archivo, que tiene que caer justo donde termina lo que
    ya hay. Si no (un reintento de un pedazo que sí había llegado), responde
    409 con lo que el servidor tiene, y el navegador sigue desde ahí. Si otra
    subida del mismo archivo está escribiendo, 409 con `ocupado` y espera."""
    ruta = _ruta_parcial(subida_id)
    candado = _candado(subida_id)
    problema = disco_videos.problema_para_subir()
    if problema:
        await _rechazar(request, 507, {"mensaje": problema})
    if candado.locked():
        actual = ruta.stat().st_size if ruta.exists() else 0
        await _rechazar(request, 409, {
            "recibido": actual, "ocupado": True,
            "mensaje": "Este archivo ya se está subiendo (otra pestaña o un doble clic): "
                       "esta subida espera a que termine."})
    async with candado:
        if not ruta.exists():
            hecho = _job_de_subida(subida_id)
            if hecho is not None:
                await _rechazar(request, 409, {"recibido": hecho["size_bytes"],
                                               "mensaje": "Este archivo ya estaba subido."})
        actual = ruta.stat().st_size if ruta.exists() else 0
        if offset != actual:
            await _rechazar(request, 409, {"recibido": actual,
                                           "mensaje": "El servidor ya tenía otra parte del archivo."})
        escrito = 0
        with open(ruta, "ab") as f:
            async for trozo in request.stream():
                escrito += len(trozo)
                if escrito > PEDAZO_MAXIMO:
                    f.truncate(actual)
                    raise HTTPException(413, detail={"mensaje": "Pedazo demasiado grande."})
                f.write(trozo)
        return {"recibido": actual + escrito}


@router.post("/subida/{subida_id}/terminar")
async def terminar_subida(subida_id: str, datos: dict):
    """Cierra la subida y registra el video como lo hace /upload. Terminar
    otra vez la misma subida devuelve el video ya registrado."""
    ruta = _ruta_parcial(subida_id)
    proyecto_id = int(datos.get("project_id") or 0)
    nombre = str(datos.get("nombre") or "")
    tamano = int(datos.get("tamano") or 0)
    project = traffic_db.get_project(proyecto_id)
    if project is None:
        raise HTTPException(404, detail={"mensaje": "La intersección ya no existe."})
    inicio = _inicio_valido(datos.get("inicio"))
    candado = _candado(subida_id)
    if candado.locked():
        raise HTTPException(409, detail={
            "recibido": ruta.stat().st_size if ruta.exists() else 0, "ocupado": True,
            "mensaje": "Este archivo todavía se está subiendo desde otra pestaña."})
    async with candado:
        hecho = _job_de_subida(subida_id)
        if hecho is not None:
            # Lo que una segunda subida del mismo archivo alcanzó a escribir.
            ruta.unlink(missing_ok=True)
            return {"accepted": [hecho], "rejected": []}
        if not ruta.exists():
            raise HTTPException(404, detail={"mensaje": "El servidor no tiene este archivo; vuelve a "
                                                         "elegirlo para subirlo de nuevo."})
        recibido = ruta.stat().st_size
        if recibido != tamano:
            raise HTTPException(409, detail={"recibido": recibido,
                                             "mensaje": f"Faltan {tamano - recibido} bytes del archivo."})
        destino = _safe_stored_path(nombre)
        ruta.replace(destino)
        job_id = traffic_db.create_video_job(
            original_name=nombre,
            stored_path=str(destino),
            size_bytes=recibido,
            source_label=project["name"],
            project_id=proyecto_id,
            video_start_time=inicio,
            interval_minutes=project["interval_minutes"],
            status="awaiting_calibration",
        )
        traffic_db.update_video_job(job_id, subida_id=subida_id)
        traffic_db.log_event(proyecto_id, "video", "Se subió un video", nombre)
        return {"accepted": [traffic_db.get_video_job(job_id)], "rejected": []}


@router.put("/{job_id}/inicio")
def poner_inicio(job_id: int, datos: dict):
    """La hora real en que empieza un video ya subido y todavía sin contar.
    Sin ella sus cruces no caen en ningún intervalo del reporte (los videos
    de Juárez se llaman por el minuto, 00.mp4 … 59.mp4, y la hora no sale
    del nombre)."""
    job = traffic_db.get_video_job(job_id)
    if job is None:
        raise HTTPException(404, detail={"mensaje": "Video no encontrado."})
    if job["status"] not in ("awaiting_calibration", "queued", "error"):
        raise HTTPException(409, detail={
            "mensaje": "Este video ya se contó o se está contando: cambiar su hora movería sus "
                       "cruces. Bórralo y vuelve a subirlo con la hora correcta."})
    inicio = _inicio_valido(datos.get("inicio"))
    if inicio is None:
        raise HTTPException(400, detail={"mensaje": "Falta la fecha y la hora de inicio."})
    traffic_db.update_video_job(job_id, video_start_time=inicio)
    traffic_db.log_event(job.get("project_id"), "video", "Se corrigió la hora de un video",
                         f"{job['original_name']}: {inicio}")
    return traffic_db.get_video_job(job_id)


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
    traffic_db.log_event(
        job.get("project_id"), "video", "Se eliminó un video", job["original_name"]
    )
    return {"deleted": job_id}


RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


@router.get("/{job_id}/diagnostico")
def leer_diagnostico(job_id: int):
    """El diagnóstico guardado de este video, si ya se hizo."""
    d = traffic_db.get_diagnostico(job_id)
    if d is None:
        raise HTTPException(404, "Este video todavía no tiene diagnóstico de encuadre")
    return d


@router.post("/{job_id}/diagnostico", status_code=202)
def diagnosticar(job_id: int, rastreo: bool = True, direccional: bool = False,
                 minutos: float = 1.0):
    """
    ¿Sirve este encuadre para aforar? Se mide ANTES de contar.

    Dos etapas: la primera mira unos cuadros (tamaño del vehículo,
    exposición, nitidez, confianza) y la segunda rastrea un minuto para ver
    dónde nacen y mueren los rastros. La primera sola no alcanza: calificaba
    mejor a un cruce que después falló (41 px pero con un puente tapando dos
    accesos) que al único que funcionó.

    Entra a la cola de la GPU y responde enseguida; el avance se lee en
    `video_jobs.diag_estado` y el resultado en GET .../diagnostico. Antes se
    calculaba aquí mismo y, para no correr dos trabajos de GPU a la vez
    (NvMapMemAllocInternalTagged error 12 en el Orin), se rechazaba con 409
    mientras hubiera algo contándose: desde la pantalla parecía que el botón
    no servía. Va delante de los conteos en la cola, así que no espera a que
    termine un aforo entero.
    """
    job = traffic_db.get_video_job(job_id)
    if job is None:
        raise HTTPException(404, "Video no encontrado")
    if not Path(job["stored_path"]).exists():
        raise HTTPException(409, "El archivo de este video ya no está en disco")
    if job.get("diag_estado") in ("en_cola", "revisando"):
        return {"job_id": job_id, "diag_estado": job["diag_estado"]}
    procesador = get_processor()
    if procesador is None:
        raise HTTPException(503, "El procesador de video no está disponible")
    procesador.diagnosticar(job_id, rastreo=rastreo, direccional=direccional, minutos=minutos)
    return {"job_id": job_id, "diag_estado": "en_cola"}


@router.post("/{job_id}/anotar", status_code=202)
def anotar(job_id: int):
    """Genera el video con detecciones de un video ya contado, con el dibujo
    de presentacion.py, sin recontarlo (recontar borra sus cruces y la
    revisión de los pesados). Entra a la cola de la GPU detrás de lo que haya."""
    job = traffic_db.get_video_job(job_id)
    if job is None:
        raise HTTPException(404, "Video no encontrado")
    if job["status"] != "done":
        raise HTTPException(409, "El video todavía no está contado")
    if job.get("anotado_estado") in ("en_cola", "generando"):
        return {"job_id": job_id, "anotado_estado": job["anotado_estado"]}
    procesador = get_processor()
    if procesador is None:
        raise HTTPException(503, "El procesador de video no está disponible")
    procesador.anotar(job_id)
    return {"job_id": job_id, "anotado_estado": "en_cola"}


@router.get("/live-frame")
def live_frame(visto: Optional[int] = None):
    """
    Último cuadro anotado del video que se está procesando ahora mismo.
    Permite ver en vivo lo que la IA está detectando, en vez de esperar a
    que termine el archivo completo. Devuelve 204 cuando no hay nada
    procesándose (el visor lo interpreta como "en reposo", no como error).
    """
    processor = get_processor()
    if processor is None:
        return Response(status_code=204)

    seq = processor.get_live_seq()
    frame, job_id = processor.get_live_frame()
    if frame is None:
        return Response(status_code=204)
    # El visor ya tiene este cuadro: no se vuelve a mandar (X-Sin-Cambio).
    if visto is not None and visto == seq:
        return Response(status_code=204, headers={"X-Sin-Cambio": "1", "X-Cuadro": str(seq)})

    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
    if not ok:
        return Response(status_code=204)

    return Response(
        content=buf.tobytes(),
        media_type="image/jpeg",
        headers={"X-Job-Id": str(job_id), "X-Cuadro": str(seq), "Cache-Control": "no-store"},
    )


@router.get("/{job_id}/video")
def get_video(job_id: int, request: Request):
    """
    Sirve el video con detecciones para que el usuario vea qué contó la IA.
    Soporta 'Range' porque el <video> del navegador lo necesita para poder
    adelantar/atrasar.
    """
    job = traffic_db.get_video_job(job_id)
    if job is None or not job.get("output_video_path"):
        raise HTTPException(404, "Todavía no hay video procesado para este trabajo")
    return _servir_video(Path(job["output_video_path"]), request)


# Contenedores que un navegador reproduce. Si el códec de adentro no le sirve
# (un .mp4 en H.265), la mesa de trabajo lo nota al cargarlo y vuelve a pedir
# cuadro por cuadro; por eso basta con la extensión y no se abre el archivo.
VIDEO_NAVEGADOR = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime",
                   ".webm": "video/webm"}


@router.get("/{job_id}/original")
def get_original(job_id: int, request: Request):
    """
    La grabación original, para reproducirla en la mesa de trabajo como
    video. Pedirla cuadro por cuadro no da: por internet cada cuadro de
    2560x1440 tarda 2.6 s y el video se veía en cámara lenta (1-oct-2026).
    """
    job = traffic_db.get_video_job(job_id)
    if job is None:
        raise HTTPException(404, "Video no encontrado")
    path = Path(job["stored_path"])
    tipo = VIDEO_NAVEGADOR.get(path.suffix.lower())
    if tipo is None:
        raise HTTPException(415, "El navegador no reproduce este formato; se ve cuadro por cuadro")
    return _servir_video(path, request, tipo)


def _servir_video(path: Path, request: Request, media_type: str = "video/mp4"):
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
                end = min(int(match.group(2)), file_size - 1)
            status_code = 206
    if start >= file_size:
        raise HTTPException(416, "Rango fuera del archivo",
                            headers={"Content-Range": f"bytes */{file_size}"})

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
        "Accept-Ranges": "bytes",
        "Content-Length": str(chunk_size),
    }
    if status_code == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
    return StreamingResponse(iterfile(), status_code=status_code, media_type=media_type,
                             headers=headers)
