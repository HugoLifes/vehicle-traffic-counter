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
from pathlib import Path

DIRECTORIO = Path("data/uploads")
MARCA = ".disco_aforo"
# Debajo de esto no se acepta una subida nueva: un video de campo pesa hasta
# 3.3 GB y un disco lleno a medio archivo deja un parcial inservible.
LIBRE_MINIMO = 5 * 1024 ** 3


def exigido() -> bool:
    return os.environ.get("AFORO_DISCO_VIDEOS") == "1"


def estado() -> dict:
    conectado = (DIRECTORIO / MARCA).exists()
    try:
        uso = shutil.disk_usage(DIRECTORIO)
        libre, total = uso.free, uso.total
    except OSError:
        libre = total = 0
    problema = None
    if exigido() and not conectado:
        problema = ("El disco externo de los videos no está conectado. Conéctalo al equipo y "
                    "reinicia la plataforma; mientras tanto no se pueden subir videos.")
    elif libre < LIBRE_MINIMO:
        problema = (f"Quedan {libre / 1024 ** 3:.1f} GB libres para videos. Libera espacio antes "
                    "de subir más.")
    return {
        "exigido": exigido(),
        "conectado": conectado,
        "libre_gb": round(libre / 1024 ** 3, 1),
        "total_gb": round(total / 1024 ** 3, 1),
        "problema": problema,
    }


def problema_para_subir():
    """El motivo por el que no se debe subir nada ahora, o None."""
    return estado()["problema"]
