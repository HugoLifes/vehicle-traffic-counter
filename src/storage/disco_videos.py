"""
El disco externo donde viven los videos subidos.

En el Jetson, `data/uploads` es un montaje del disco USB de 2 TB
(`/mnt/videos/aforo/uploads`, ver docker-compose.jetson.yml), no una
carpeta del SSD. El riesgo de un montaje es que falle sin ruido: si el
disco no está conectado al arrancar, Docker monta la carpeta vacía del SSD
en su lugar y la plataforma sigue subiendo videos ahí, llenando el disco del
sistema, y los videos de antes "desaparecen" de la pantalla.

Por eso el disco lleva un archivo marca (`.disco_aforo`) que la carpeta vacía
del SSD no tiene. Con `AFORO_DISCO_VIDEOS=1` (solo en el compose del Jetson)
la plataforma exige la marca: sin ella rechaza las subidas con un mensaje que
dice qué hacer, y la prueba de aceptación falla. En la PC de desarrollo la
variable no está y nada cambia.
"""

import os
import shutil
import time
from pathlib import Path

DIRECTORIO = Path("data/uploads")
MARCA = ".disco_aforo"
# Debajo de esto no se acepta una subida nueva: un video de campo pesa hasta
# 3.3 GB y un disco lleno a medio archivo deja un parcial inservible.
LIBRE_MINIMO = 5 * 1024 ** 3


def exigido() -> bool:
    return os.environ.get("AFORO_DISCO_VIDEOS") == "1"


def _espacio():
    try:
        uso = shutil.disk_usage(DIRECTORIO)
        return uso.free, uso.total
    except OSError:
        return 0, 0


def problema_para_subir():
    """El motivo por el que no se debe subir nada ahora, o None. Barato: se
    llama en cada pedazo de cada subida."""
    if exigido() and not (DIRECTORIO / MARCA).exists():
        return ("El disco externo de los videos no está conectado. Conéctalo al equipo y "
                "reinicia la plataforma; mientras tanto no se pueden subir videos.")
    libre, _ = _espacio()
    if libre < LIBRE_MINIMO:
        return (f"Quedan {libre / 1024 ** 3:.1f} GB libres para videos. Libera espacio antes "
                "de subir más.")
    return None


_cache_usado = {"t": 0.0, "bytes": 0}


def estado() -> dict:
    """Lo que muestra la pantalla: capacidad, libre, cuánto ocupan los videos
    y cuántas horas de video caben todavía."""
    libre, total = _espacio()
    # Recorrer todos los videos del disco USB cuesta; se recalcula cada 5 min.
    if time.time() - _cache_usado["t"] > 300:
        _cache_usado.update(t=time.time(), bytes=usado_por_videos())
    gb_hora = gb_por_hora()
    return {
        "exigido": exigido(),
        "conectado": (DIRECTORIO / MARCA).exists(),
        "libre_gb": round(libre / 1024 ** 3, 1),
        "total_gb": round(total / 1024 ** 3, 1),
        "usado_videos_gb": round(_cache_usado["bytes"] / 1024 ** 3, 1),
        "gb_por_hora": gb_hora,
        # Cuánto video cabe todavía, al peso medio de lo que ya se subió.
        "horas_que_caben": round(libre / 1024 ** 3 / gb_hora) if gb_hora else None,
        "problema": problema_para_subir(),
    }


def gb_por_hora():
    """Peso medio de una hora de video, de los videos ya subidos y leídos
    (el frontal de 2560x1440 pesa ~1 GB/h; el lateral de 640x360, ~0.2).
    None si todavía no hay ninguno."""
    from src.storage import traffic_db
    fila = traffic_db.get_connection().execute(
        """SELECT SUM(size_bytes), SUM(total_frames / fps) FROM video_jobs
           WHERE fps > 0 AND total_frames > 0 AND size_bytes > 0""").fetchone()
    if not fila or not fila[0] or not fila[1]:
        return None
    return round(fila[0] / 1024 ** 3 / (fila[1] / 3600), 2)


def usado_por_videos() -> int:
    total = 0
    try:
        for p in DIRECTORIO.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
    except OSError:
        pass
    return total
