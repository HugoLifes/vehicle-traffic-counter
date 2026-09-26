"""
Respaldo diario de la base de datos.

Todo lo que el sistema sabe —proyectos, calibraciones, zonas, cruces, la
revisión de los pesados— vive en un solo archivo, data/traffic.db. Hasta el
26-sep-2026 no tenía ningún respaldo: un disco que se llena a media
escritura, un apagón o un borrado por error se llevaban un aforo de 24 h ya
contado y calibrado, que son días de equipo.

Se usa la copia en línea de SQLite (`Connection.backup`): es consistente
aunque la cola esté escribiendo cruces en ese momento, cosa que copiar el
archivo no garantiza con la base en modo WAL. Cada copia se comprueba
(`PRAGMA quick_check`) antes de darla por buena, y se conservan las últimas
`CONSERVAR`.

Restaurar (con el contenedor detenido):

    docker compose -f docker-compose.jetson.yml stop
    cp data/respaldos/traffic_AAAA-MM-DD_HHMM.db data/traffic.db
    rm -f data/traffic.db-wal data/traffic.db-shm
    docker compose -f docker-compose.jetson.yml start
"""
import logging
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from src.storage import traffic_db

CONSERVAR = 14
CADA_HORAS = 24
PREFIJO = "traffic_"


def carpeta() -> Path:
    return Path(traffic_db.DB_PATH).parent / "respaldos"


def listar() -> List[Path]:
    """Respaldos existentes, del más viejo al más nuevo."""
    return sorted(carpeta().glob(f"{PREFIJO}*.db"))


def respaldar(conservar: int = CONSERVAR) -> Optional[Path]:
    """Hace una copia comprobada de la base. Devuelve la ruta, o None si
    falló (el fallo se registra; nunca tumba a quien lo llama)."""
    origen = Path(traffic_db.DB_PATH)
    if not origen.exists():
        return None
    destino_dir = carpeta()
    destino_dir.mkdir(parents=True, exist_ok=True)
    destino = destino_dir / f"{PREFIJO}{datetime.now():%Y-%m-%d_%H%M}.db"
    temporal = destino.with_suffix(".parcial")
    try:
        fuente = sqlite3.connect(f"file:{origen}?mode=ro", uri=True, timeout=60.0)
        copia = sqlite3.connect(temporal)
        with copia:
            fuente.backup(copia)
        fuente.close()
        estado = copia.execute("PRAGMA quick_check").fetchone()[0]
        copia.close()
        if estado != "ok":
            logging.error(f"El respaldo {destino.name} no pasó la comprobación: {estado}")
            temporal.unlink(missing_ok=True)
            return None
        temporal.replace(destino)
    except Exception:
        logging.exception("No se pudo respaldar la base de datos")
        temporal.unlink(missing_ok=True)
        return None
    for viejo in listar()[:-conservar] if conservar > 0 else []:
        viejo.unlink(missing_ok=True)
    logging.info(f"Respaldo de la base: {destino} ({destino.stat().st_size // 1024} KB)")
    return destino


def _hace_falta() -> bool:
    existentes = listar()
    if not existentes:
        return True
    return time.time() - existentes[-1].stat().st_mtime >= CADA_HORAS * 3600


def iniciar_automatico(parar: threading.Event) -> threading.Thread:
    """Hilo que respalda al arrancar si el último respaldo tiene más de un
    día, y después una vez al día."""
    def ciclo():
        while not parar.is_set():
            if _hace_falta():
                respaldar()
            parar.wait(3600)
    hilo = threading.Thread(target=ciclo, name="respaldos", daemon=True)
    hilo.start()
    return hilo
