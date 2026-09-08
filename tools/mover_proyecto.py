#!/usr/bin/env python3
"""
Lleva un proyecto calibrado de una maquina a otra.

Existe porque la calibracion no se puede rehacer a ojo en el destino: una
zona mal dibujada recorta el conteo sin dar ningun error (medido: 107 -> 36
cruces). Lo que vale es el trazo exacto que ya se verifico, asi que se
traslada tal cual en vez de volver a dibujarlo.

NO viaja la base de datos entera. Copiar `traffic.db` de una maquina a otra
destruiria lo que el destino ya tenga — en el Jetson, los documentos del
RAG viven en el mismo archivo.

TAMPOCO viajan los cruces: son el resultado del conteo, no la
configuracion, y se recalculan al reprocesar. Traerlos solo serviria para
mezclar cifras de dos calibraciones distintas, que es justo el lio que la
interfaz ya marca como "calibracion anterior".

Uso, en el origen:
    python tools/mover_proyecto.py exportar --proyecto 11 \
        --salida data/proyecto_11.json

Luego se copian ese JSON y los videos de data/uploads al destino, y alli:
    python tools/mover_proyecto.py importar --archivo data/proyecto_11.json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BD = RAIZ / "data" / "traffic.db"
UPLOADS = RAIZ / "data" / "uploads"

FORMATO = 1  # version del JSON, por si el esquema cambia


def _conectar(bd: Path, escritura: bool = False) -> sqlite3.Connection:
    if not bd.exists():
        sys.exit(f"No existe la base {bd}")
    uri = f"file:{bd}" + ("" if escritura else "?mode=ro")
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


# --- exportar -----------------------------------------------------------


def exportar(a: argparse.Namespace) -> None:
    con = _conectar(a.bd)
    proyecto = con.execute("select * from projects where id=?", (a.proyecto,)).fetchone()
    if not proyecto:
        sys.exit(f"No existe el proyecto {a.proyecto}")

    zonas = [dict(r) for r in con.execute(
        "select name, kind, points_json, active from zones where project_id=? order by id",
        (a.proyecto,),
    )]

    # El carril guarda zone_id, que es un numero local de ESTA base. Se
    # traduce al nombre de la zona: es lo unico que significa lo mismo en
    # las dos maquinas. Sin esta traduccion la linea de la calzada del
    # fondo recogeria los vehiculos de la cercana.
    nombre_zona = {
        r["id"]: r["name"]
        for r in con.execute("select id, name from zones where project_id=?", (a.proyecto,))
    }
    filtro = "" if a.todo else " and active=1"
    carriles = []
    for r in con.execute(
        f"select name, line_type, points_json, active, zone_id from lane_configs "
        f"where project_id=?{filtro} order by id",
        (a.proyecto,),
    ):
        d = dict(r)
        d["zona"] = nombre_zona.get(d.pop("zone_id"))
        carriles.append(d)

    videos, sin_archivo = [], []
    for r in con.execute(
        "select original_name, stored_path, size_bytes, video_start_time, fps, "
        "interval_minutes, total_frames from video_jobs where project_id=? "
        "order by video_start_time",
        (a.proyecto,),
    ):
        d = dict(r)
        # Solo el nombre del archivo: la ruta absoluta del origen no
        # significa nada en el destino.
        d["archivo"] = Path(d.pop("stored_path")).name
        videos.append(d)
        if not (a.uploads / d["archivo"]).exists():
            sin_archivo.append(d["archivo"])

    paquete = {
        "formato": FORMATO,
        "exportado": datetime.now().isoformat(timespec="seconds"),
        "proyecto": {k: proyecto[k] for k in proyecto.keys() if k != "id"},
        "zonas": zonas,
        "carriles": carriles,
        "videos": videos,
    }
    a.salida.parent.mkdir(parents=True, exist_ok=True)
    a.salida.write_text(json.dumps(paquete, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Proyecto: {proyecto['name']}")
    print(f"  {len(zonas)} zonas, {len(carriles)} carriles"
          + ("" if a.todo else " (solo los activos; --todo incluye los demas)"))
    print(f"  {len(videos)} videos")
    for c in carriles:
        print(f"    linea {c['name']!r} -> zona {c['zona']!r}")
    if sin_archivo:
        print(f"\n  AVISO: {len(sin_archivo)} videos sin archivo en {a.uploads}:")
        for n in sin_archivo[:5]:
            print(f"    {n}")
    print(f"\nEscrito en {a.salida}")
    print(f"Falta copiar los videos de {a.uploads} al destino.")


# --- importar -----------------------------------------------------------


def importar(a: argparse.Namespace) -> None:
    paquete = json.loads(a.archivo.read_text(encoding="utf-8"))
    if paquete.get("formato") != FORMATO:
        sys.exit(f"Formato {paquete.get('formato')} desconocido; esta version lee {FORMATO}")

    con = _conectar(a.bd, escritura=True)
    p = dict(paquete["proyecto"])
    nombre = a.nombre or p["name"]

    if con.execute("select 1 from projects where name=?", (nombre,)).fetchone():
        sys.exit(
            f"Ya existe un proyecto llamado {nombre!r}. Usa --nombre para darle otro "
            f"y no mezclar dos calibraciones en el mismo proyecto."
        )

    faltan = [v["archivo"] for v in paquete["videos"] if not (a.uploads / v["archivo"]).exists()]
    if faltan and not a.sin_videos:
        print(f"Faltan {len(faltan)} de {len(paquete['videos'])} videos en {a.uploads}:")
        for n in faltan[:5]:
            print(f"  {n}")
        sys.exit("Copia los videos primero, o usa --sin-videos para registrar solo lo demas.")

    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with con:  # una sola transaccion: o entra el proyecto entero o no entra nada
        cur = con.execute(
            "insert into projects (name, description, latitude, longitude, address, "
            "interval_minutes, created_at, updated_at) values (?,?,?,?,?,?,?,?)",
            (nombre, p.get("description"), p.get("latitude"), p.get("longitude"),
             p.get("address"), p.get("interval_minutes") or 15, ahora, ahora),
        )
        pid = cur.lastrowid

        zonas_nuevas = {}
        for z in paquete["zonas"]:
            cur = con.execute(
                "insert into zones (project_id, name, kind, points_json, active, "
                "created_at, updated_at) values (?,?,?,?,?,?,?)",
                (pid, z["name"], z.get("kind"), z["points_json"], z.get("active", 1), ahora, ahora),
            )
            zonas_nuevas[z["name"]] = cur.lastrowid

        for c in paquete["carriles"]:
            zona = c.get("zona")
            if zona and zona not in zonas_nuevas:
                sys.exit(f"El carril {c['name']!r} apunta a la zona {zona!r}, que no viene en el paquete.")
            con.execute(
                "insert into lane_configs (camera_source, project_id, name, line_type, "
                "points_json, active, created_at, updated_at, zone_id) values (?,?,?,?,?,?,?,?,?)",
                (nombre, pid, c["name"], c.get("line_type"), c["points_json"],
                 c.get("active", 1), ahora, ahora, zonas_nuevas.get(zona)),
            )

        registrados = 0
        for v in paquete["videos"]:
            ruta = a.uploads / v["archivo"]
            if not ruta.exists():
                continue
            con.execute(
                "insert into video_jobs (original_name, stored_path, size_bytes, "
                "source_label, project_id, video_start_time, fps, interval_minutes, "
                "status, total_frames, processed_frames, uploaded_at) "
                "values (?,?,?,?,?,?,?,?,?,?,0,?)",
                (v["original_name"], str(ruta), v.get("size_bytes"), nombre, pid,
                 v.get("video_start_time"), v.get("fps"), v.get("interval_minutes"),
                 # Entra sin contar: la calibracion viaja, pero arrancar el
                 # conteo lo decide una persona mirando el encuadre.
                 "awaiting_calibration", v.get("total_frames"), ahora),
            )
            registrados += 1

    print(f"Proyecto {nombre!r} creado con id {pid}")
    print(f"  {len(zonas_nuevas)} zonas, {len(paquete['carriles'])} carriles, {registrados} videos")
    for c in paquete["carriles"]:
        print(f"    linea {c['name']!r} -> zona {c.get('zona')!r}")
    print("\nLos videos quedaron en 'esperando calibracion'. Revisa el encuadre en la")
    print("plataforma y presiona 'Empezar conteo' cuando las lineas se vean bien.")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--bd", type=Path, default=BD)
    p.add_argument("--uploads", type=Path, default=UPLOADS)
    sub = p.add_subparsers(dest="accion", required=True)

    e = sub.add_parser("exportar", help="saca la calibracion de un proyecto a un JSON")
    e.add_argument("--proyecto", type=int, required=True)
    e.add_argument("--salida", type=Path, required=True)
    e.add_argument("--todo", action="store_true",
                   help="incluir tambien carriles inactivos (intentos abandonados)")
    e.set_defaults(func=exportar)

    i = sub.add_parser("importar", help="mete ese JSON en la base de otra maquina")
    i.add_argument("--archivo", type=Path, required=True)
    i.add_argument("--nombre", help="renombrar el proyecto al importarlo")
    i.add_argument("--sin-videos", action="store_true",
                   help="registrar zonas y carriles aunque falten los videos")
    i.set_defaults(func=importar)

    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
