"""
La carpeta de entrada: videos que llegan SIN pasar por el navegador.

Por WinSCP (SFTP, cuenta `juarez` encerrada en /srv/entrada/juarez) o en un
disco conectado al Jetson. El navegador por la dirección pública pasa por el
relevo de Tailscale (~25 KB/s medidos desde Juárez); por SFTP sobre Tailscale
va a la velocidad real del internet de quien sube, retoma si se corta y
arrastra carpetas enteras.

En el contenedor es `data/entrada`, montada de SOLO LECTURA: la plataforma no
puede borrar ni cambiar lo que suban. Importar COPIA cada video al disco de
los videos (`data/uploads`) y comprueba el tamaño; el original se queda donde
está. Un video ya importado a una intersección no se vuelve a importar a la
misma (se reconoce por ruta, tamaño y fecha del archivo).
"""

import hashlib
import logging
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

DIRECTORIO = Path("data/entrada")
EXTENSIONES = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv", ".wmv", ".m4v", ".mpg", ".mpeg"}

_HMS = re.compile(r"(?<!\d)(\d{2})[-_:.](\d{2})[-_:.](\d{2})(?!\d)")
_MINUTO = re.compile(r"^(\d{1,2})(?:-\d+)?$")            # 00.mp4 … 59.mp4
_HORA_CARPETA = re.compile(r"^(\d{1,2})(?:h|hrs?|[-_:.]00)?$", re.I)  # 14, 14h, 14-00
_FECHA = (
    (re.compile(r"(?<!\d)(20\d{2})[-_.]?(\d{2})[-_.]?(\d{2})(?!\d)"), (1, 2, 3)),   # 2026-10-05, 20261005
    (re.compile(r"(?<!\d)(\d{2})[-_.](\d{2})[-_.](20\d{2})(?!\d)"), (3, 2, 1)),     # 05-10-2026
)


def _fecha_de(partes: List[str]) -> Optional[str]:
    for parte in reversed(partes):
        for patron, (a, m, d) in _FECHA:
            g = patron.search(parte)
            if g:
                try:
                    return datetime(int(g.group(a)), int(g.group(m)), int(g.group(d))).strftime("%Y-%m-%d")
                except ValueError:
                    continue
    return None


def hora_de(ruta_relativa: str) -> Dict[str, Optional[str]]:
    """Fecha y hora de inicio que se pueden leer de la ruta, si se puede.

    `14-56-00.mp4` da 14:56:00. `14/05.mp4` (carpeta por hora y archivo por
    minuto, como graba la cámara de Juárez) da 14:05:00. La fecha sale de
    cualquier carpeta que la tenga (`2026-10-05`, `20261005`, `05-10-2026`)."""
    partes = Path(ruta_relativa).parts
    nombre = Path(partes[-1]).stem
    hora = None
    # Sin la fecha: en `2026-09-19_14-56-00` el patrón de la hora agarraba
    # "09-19_14".
    sin_fecha = nombre
    for patron, _ in _FECHA:
        sin_fecha = patron.sub(" ", sin_fecha)
    g = _HMS.search(sin_fecha)
    if g and int(g.group(1)) < 24 and int(g.group(2)) < 60 and int(g.group(3)) < 60:
        hora = f"{g.group(1)}:{g.group(2)}:{g.group(3)}"
    else:
        m = _MINUTO.match(nombre)
        h = _HORA_CARPETA.match(partes[-2]) if len(partes) > 1 else None
        if m and h and int(m.group(1)) < 60 and int(h.group(1)) < 24:
            hora = f"{int(h.group(1)):02d}:{int(m.group(1)):02d}:00"
    return {"fecha": _fecha_de(list(partes[:-1]) + [nombre]), "hora": hora}


def _seguro(ruta_relativa: str) -> Path:
    """La ruta dentro de la carpeta de entrada; nada de `..` para salirse."""
    base = DIRECTORIO.resolve()
    ruta = (DIRECTORIO / ruta_relativa).resolve()
    if base != ruta and base not in ruta.parents:
        raise ValueError("Ruta fuera de la carpeta de entrada")
    return ruta


def visible(ruta_relativa: str) -> str:
    """La ruta como la piensa quien subió: sin `juarez/videos/` delante (la
    carpeta de su cuenta de WinSCP)."""
    partes = Path(ruta_relativa).parts
    if len(partes) > 2 and partes[1] == "videos":
        partes = partes[2:]
    return "/".join(partes)


def huella(ruta_relativa: str, tamano: int, mtime: float, proyecto_id: int) -> str:
    clave = f"entrada|{proyecto_id}|{ruta_relativa}|{tamano}|{int(mtime)}"
    return "entrada-" + hashlib.sha256(clave.encode()).hexdigest()[:28]


def listar(proyecto_id: Optional[int] = None) -> Dict:
    """Los videos de la carpeta de entrada, con la hora que se lee de su ruta
    y, si se da el proyecto, cuáles ya se importaron a él."""
    from src.storage import traffic_db
    if not DIRECTORIO.exists():
        return {"disponible": False, "archivos": []}
    importados = {}
    if proyecto_id is not None:
        importados = {r[0]: r[1] for r in traffic_db.get_connection().execute(
            "SELECT subida_id, id FROM video_jobs WHERE project_id = ? AND subida_id LIKE 'entrada-%'",
            (proyecto_id,))}
    archivos = []
    for ruta in sorted(DIRECTORIO.rglob("*")):
        if not ruta.is_file() or ruta.suffix.lower() not in EXTENSIONES or ruta.name.startswith("."):
            continue
        try:
            st = ruta.stat()
        except OSError:
            continue
        rel = ruta.relative_to(DIRECTORIO).as_posix()
        archivos.append({
            "ruta": rel, "nombre": visible(rel), "tamano": st.st_size,
            "modificado": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
            **hora_de(rel),
            "importado": (importados.get(huella(rel, st.st_size, st.st_mtime, proyecto_id))
                          if proyecto_id is not None else None),
        })
    return {"disponible": True, "archivos": archivos}


# Una importación a la vez: copiar al disco USB es lo que la limita, y dos en
# paralelo solo se estorban.
_estado: Dict = {"activa": False}
_candado = threading.Lock()


def estado() -> Dict:
    with _candado:
        return dict(_estado)


def importar(proyecto_id: int, pedidos: List[Dict], destino: Path) -> Dict:
    """Arranca la copia en segundo plano. `pedidos`: [{ruta, inicio}]."""
    from src.storage import traffic_db
    proyecto = traffic_db.get_project(proyecto_id)
    if proyecto is None:
        raise LookupError("La intersección ya no existe.")
    with _candado:
        if _estado.get("activa"):
            raise RuntimeError("Ya hay una importación en curso; espera a que termine.")
        rutas = [_seguro(p["ruta"]) for p in pedidos]
        total = sum(r.stat().st_size for r in rutas)
        _estado.clear()
        _estado.update(activa=True, proyecto_id=proyecto_id, total=len(pedidos), hechos=0,
                       bytes_total=total, bytes_hechos=0, actual=None, errores=[], videos=[],
                       omitidos=0)
    hilo = threading.Thread(target=_copiar, args=(proyecto, pedidos, rutas, destino),
                            name="importar-entrada", daemon=True)
    hilo.start()
    return estado()


def _copiar(proyecto, pedidos, rutas, destino: Path):
    from src.storage import traffic_db
    for pedido, ruta in zip(pedidos, rutas):
        rel = pedido["ruta"]
        temporal = None
        with _candado:
            _estado["actual"] = rel
        try:
            st = ruta.stat()
            marca = huella(rel, st.st_size, st.st_mtime, proyecto["id"])
            ya = traffic_db.get_connection().execute(
                "SELECT id FROM video_jobs WHERE subida_id = ?", (marca,)).fetchone()
            if ya:
                with _candado:
                    _estado["omitidos"] += 1
                    _estado["bytes_hechos"] += st.st_size
                continue
            stem = re.sub(r'[/\\:*?"<>|]', "_", Path(rel).with_suffix("").as_posix().replace("/", "_"))[:80]
            final = destino / f"{uuid.uuid4().hex[:8]}_{stem}{ruta.suffix.lower()}"
            temporal = final.with_suffix(final.suffix + ".importando")
            with open(ruta, "rb") as src, open(temporal, "wb") as dst:
                while True:
                    trozo = src.read(8 * 1024 * 1024)
                    if not trozo:
                        break
                    dst.write(trozo)
                    with _candado:
                        _estado["bytes_hechos"] += len(trozo)
            # La copia tiene que pesar lo mismo que el original: un disco que
            # se llenó o se desconectó a la mitad deja un video cortado que
            # contaría de menos sin dar error.
            copiado = temporal.stat().st_size
            if copiado != st.st_size:
                temporal.unlink(missing_ok=True)
                raise IOError(f"la copia quedó de {copiado} bytes y el original tiene {st.st_size}")
            temporal.replace(final)
            job_id = traffic_db.create_video_job(
                original_name=visible(rel).replace("/", " / "),
                stored_path=str(final), size_bytes=st.st_size, source_label=proyecto["name"],
                project_id=proyecto["id"], video_start_time=pedido.get("inicio"),
                interval_minutes=proyecto["interval_minutes"], status="awaiting_calibration")
            traffic_db.update_video_job(job_id, subida_id=marca)
            with _candado:
                _estado["videos"].append(job_id)
        except Exception as e:
            logging.exception(f"No se pudo importar {rel}")
            if temporal is not None:
                temporal.unlink(missing_ok=True)
            with _candado:
                _estado["errores"].append({"ruta": rel, "motivo": str(e)})
        finally:
            with _candado:
                _estado["hechos"] += 1
    n = len(_estado["videos"])
    if n:
        traffic_db.log_event(proyecto["id"], "video", "Se importaron videos de la carpeta de entrada",
                             f"{n} videos")
    with _candado:
        _estado["activa"] = False
        _estado["actual"] = None
