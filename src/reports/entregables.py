"""
Entregables de un aforo: el paquete que se le manda al cliente.

Nace de Campos Elíseos (oct-2026): la empresa pidió "los 3 días" y el Excel
de la plataforma era uno solo con todo; los tres por día se armaron a mano,
copiando la base y borrando los otros días. Aquí eso es un botón:

  · el Excel completo (el mismo de "Descargar Excel");
  · un Excel por día, con su RESUMEN y su hora de máxima demanda;
  · la lista de revisión antes de entregar (videos sin contar, con error,
    sin hora, horas no medibles, sin ubicación…).

Cada Excel por día se genera en un PROCESO APARTE sobre una base temporal
que solo tiene ese proyecto y ese día: `traffic_db` usa una ruta y una
conexión globales, y cambiarlas dentro del servidor se las cambiaría también
a la cola y a cualquier otra petición en curso. Las hojas, las reglas y el
formato son exactamente los del Excel completo, porque es la misma función.

    python -m src.reports.entregables dia --proyecto 24 --fecha 2026-09-29 --salida x.xlsx
"""

import argparse
import logging
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from src.storage import traffic_db

DIRECTORIO = Path("data/entregables")

# Qué se copia a la base de un día: lo del proyecto, y de lo fechado, ese día.
_TABLAS = [
    ("projects", "id = :p"),
    ("zones", "project_id = :p"),
    ("lane_configs", "project_id = :p"),
    ("video_jobs", "project_id = :p AND substr(video_start_time, 1, 10) = :f"),
    ("crossings", "lane_id IN (SELECT id FROM o.lane_configs WHERE project_id = :p) "
                  "AND substr(timestamp, 1, 10) = :f"),
    ("movimientos", "project_id = :p AND substr(timestamp, 1, 10) = :f"),
    ("diagnosticos", "project_id = :p"),
]


def dias_del_aforo(project_id: int) -> List[str]:
    """Los días con algo contado (cruces de línea o movimientos)."""
    conn = traffic_db.get_connection()
    dias = {r[0] for r in conn.execute(
        """SELECT DISTINCT substr(c.timestamp, 1, 10) FROM crossings c
           JOIN lane_configs l ON l.id = c.lane_id
           WHERE l.project_id = ? AND c.timestamp IS NOT NULL""", (project_id,))}
    dias |= {r[0] for r in conn.execute(
        """SELECT DISTINCT substr(timestamp, 1, 10) FROM movimientos
           WHERE project_id = ? AND timestamp IS NOT NULL""", (project_id,))}
    return sorted(d for d in dias if d)


def revision(project_id: int) -> List[Dict]:
    """Lo que conviene saber antes de entregar, de lo más grave a lo menos.
    `nivel`: 'error' impide confiar en el número, 'aviso' lo matiza."""
    conn = traffic_db.get_connection()
    p = traffic_db.get_project(project_id) or {}
    estados = dict(conn.execute(
        "SELECT status, COUNT(*) FROM video_jobs WHERE project_id = ? GROUP BY status",
        (project_id,)).fetchall())
    sin_hora = conn.execute(
        """SELECT COUNT(*) FROM video_jobs WHERE project_id = ? AND status = 'done'
           AND video_start_time IS NULL""", (project_id,)).fetchone()[0]
    con_aviso = conn.execute(
        """SELECT COUNT(*) FROM video_jobs WHERE project_id = ? AND aviso IS NOT NULL
           AND aviso != ''""", (project_id,)).fetchone()[0]
    salida = []
    if estados.get("error"):
        salida.append({"nivel": "error", "texto": f"{estados['error']} videos con error: lo que traen no está contado."})
    pendientes = estados.get("queued", 0) + estados.get("processing", 0)
    if pendientes:
        salida.append({"nivel": "error", "texto": f"{pendientes} videos todavía en la cola: el aforo no está completo."})
    if sin_hora:
        salida.append({"nivel": "error", "texto": f"{sin_hora} videos contados sin hora de inicio: sus vehículos no caen en ningún cuarto de hora."})
    if estados.get("awaiting_calibration"):
        salida.append({"nivel": "aviso", "texto": f"{estados['awaiting_calibration']} videos subidos sin contar (fuera de las horas que se pidieron, o sin calibrar)."})
    if con_aviso:
        salida.append({"nivel": "aviso", "texto": f"{con_aviso} videos con un aviso al contarse (zona, línea o archivo cortado): revísalos en Subir videos."})
    if p.get("latitude") is None:
        salida.append({"nivel": "aviso", "texto": "La intersección no está ubicada en el mapa."})
    if not estados.get("done"):
        salida.append({"nivel": "error", "texto": "Todavía no hay ningún video contado."})
    return salida


def _seguro(texto: str) -> str:
    return re.sub(r"[^\w\-]+", "_", texto, flags=re.UNICODE).strip("_")[:60] or "aforo"


def _base_del_dia(origen: Path, destino: Path, project_id: int, fecha: str) -> None:
    """Una base nueva con el esquema de la plataforma y solo ese proyecto en
    ese día. Las columnas se copian por NOMBRE: en la base real se fueron
    agregando con _ensure_column y su orden no es el de una base nueva."""
    traffic_db.DB_PATH = destino
    traffic_db.init_schema()
    conn = traffic_db.get_connection()
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("ATTACH DATABASE ? AS o", (str(origen),))
    for tabla, donde in _TABLAS:
        nuevas = {r[1] for r in conn.execute(f"PRAGMA main.table_info({tabla})")}
        viejas = [r[1] for r in conn.execute(f"PRAGMA o.table_info({tabla})")]
        cols = ", ".join(c for c in viejas if c in nuevas)
        if not cols:
            continue
        conn.execute(f"INSERT INTO main.{tabla} ({cols}) SELECT {cols} FROM o.{tabla} WHERE {donde}",
                     {"p": project_id, "f": fecha})
    conn.commit()
    conn.execute("DETACH DATABASE o")


def excel_del_dia(project_id: int, fecha: str, salida: Path) -> None:
    """Corre en su propio proceso (ver el encabezado)."""
    origen = Path(traffic_db.DB_PATH).resolve()
    with tempfile.TemporaryDirectory() as tmp:
        _base_del_dia(origen, Path(tmp) / "dia.db", project_id, fecha)
        from src.reports import aforo_excel
        aforo_excel.generar(project_id, str(salida))


# --- Preparación en segundo plano -------------------------------------------
# Un paquete con días direccionales puede tardar minutos (cada día decide sus
# recorridos), así que se arma en un hilo y la pantalla pregunta cómo va.

_estado: Dict[int, Dict] = {}
_candado = threading.Lock()


def estado(project_id: int) -> Dict:
    with _candado:
        e = dict(_estado.get(project_id) or {})
    zip_ = _ruta_zip(project_id)
    if not e and zip_.exists():
        e = {"estado": "listo", "archivo": zip_.name,
             "fecha": datetime.fromtimestamp(zip_.stat().st_mtime).strftime("%Y-%m-%d %H:%M")}
    return e or {"estado": "sin_preparar"}


def _ruta_zip(project_id: int) -> Path:
    p = traffic_db.get_project(project_id) or {"name": f"aforo_{project_id}"}
    return DIRECTORIO / str(project_id) / f"{_seguro(p['name'])}_entregable.zip"


def preparar(project_id: int) -> Dict:
    with _candado:
        if (_estado.get(project_id) or {}).get("estado") == "preparando":
            return dict(_estado[project_id])
        dias = dias_del_aforo(project_id)
        _estado[project_id] = {"estado": "preparando", "paso": "Excel completo", "hechos": 0,
                               "total": 1 + len(dias)}
    threading.Thread(target=_armar, args=(project_id, dias), daemon=True,
                     name=f"entregable-{project_id}").start()
    return estado(project_id)


def _armar(project_id: int, dias: List[str]) -> None:
    from src.reports import aforo_excel
    p = traffic_db.get_project(project_id)
    base = _seguro(p["name"])
    carpeta = DIRECTORIO / str(project_id)
    trabajo = carpeta / "armando"
    shutil.rmtree(trabajo, ignore_errors=True)
    trabajo.mkdir(parents=True, exist_ok=True)
    errores = []

    def avanzar(paso: str):
        with _candado:
            _estado[project_id]["paso"] = paso
            _estado[project_id]["hechos"] += 1

    try:
        aforo_excel.generar(project_id, str(trabajo / f"{base}_completo.xlsx"))
        for fecha in dias:
            avanzar(f"Excel del {fecha}")
            r = subprocess.run(
                [sys.executable, "-m", "src.reports.entregables", "dia", "--proyecto", str(project_id),
                 "--fecha", fecha, "--salida", str(trabajo / f"{base}_{fecha}.xlsx")],
                capture_output=True, text=True, timeout=3600, cwd=Path.cwd())
            if r.returncode != 0:
                errores.append(f"{fecha}: {(r.stderr or r.stdout).strip().splitlines()[-1:] or ['sin detalle']}")
                logging.error(f"Entregable {project_id} {fecha}: {r.stderr[-2000:]}")
        lineas = ["REVISIÓN ANTES DE ENTREGAR", f"{p['name']}", ""]
        for r in revision(project_id):
            lineas.append(("[!] " if r["nivel"] == "error" else "[i] ") + r["texto"])
        if errores:
            lineas += ["", "No se pudo generar:"] + errores
        (trabajo / "LEEME.txt").write_text("\r\n".join(lineas) + "\r\n", encoding="utf-8")
        destino = _ruta_zip(project_id)
        tmp = destino.with_suffix(".tmp")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(trabajo.iterdir()):
                z.write(f, f.name)
        tmp.replace(destino)
        with _candado:
            _estado.pop(project_id, None)
        if errores:
            with _candado:
                _estado[project_id] = {"estado": "listo", "archivo": destino.name, "errores": errores,
                                       "fecha": datetime.now().strftime("%Y-%m-%d %H:%M")}
        traffic_db.log_event(project_id, "entregable", "Se preparó el paquete de entrega",
                             f"{1 + len(dias)} archivos")
    except Exception as e:
        logging.exception(f"No se pudo preparar el entregable del proyecto {project_id}")
        with _candado:
            _estado[project_id] = {"estado": "error", "error": str(e)[:300]}
    finally:
        shutil.rmtree(trabajo, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dia")
    d.add_argument("--proyecto", type=int, required=True)
    d.add_argument("--fecha", required=True)
    d.add_argument("--salida", required=True)
    a = ap.parse_args()
    if a.cmd == "dia":
        excel_del_dia(a.proyecto, a.fecha, Path(a.salida))


if __name__ == "__main__":
    main()
