"""
Almacenamiento SQLite del sistema: carriles/líneas de conteo y cruces
registrados. No se guarda video ni imágenes aquí, solo eventos
estructurados.

Cada módulo (visual_context.py, validator.py, etc.) es responsable de
crear sus propias tablas con CREATE TABLE IF NOT EXISTS usando
get_connection(), para que cada fase agregue su almacenamiento sin
tocar este archivo.
"""

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Dict, List, Optional

DB_PATH = Path("data/traffic.db")

_local = threading.local()


def _ensure_column(conn, table: str, column: str, ddl: str):
    """
    CREATE TABLE IF NOT EXISTS no agrega columnas nuevas a una tabla que ya
    existe, así que las bases creadas con una versión anterior del esquema
    necesitan un ALTER TABLE explícito. Idempotente.
    """
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def get_connection() -> sqlite3.Connection:
    """
    Conexión SQLite por hilo (el motor de conteo corre en su propio
    hilo, la API corre en el hilo/loop de uvicorn). WAL permite lecturas
    concurrentes mientras el motor escribe cruces.
    """
    if not hasattr(_local, "conn"):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        _local.conn = conn
    return _local.conn


def init_schema():
    """Crear tablas base (proyectos, carriles y cruces) si no existen."""
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            latitude REAL,
            longitude REAL,
            address TEXT,
            interval_minutes INTEGER NOT NULL DEFAULT 15,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS lane_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            camera_source TEXT NOT NULL,
            project_id INTEGER REFERENCES projects(id),
            name TEXT NOT NULL,
            line_type TEXT NOT NULL,
            points_json TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS crossings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lane_id INTEGER NOT NULL REFERENCES lane_configs(id),
            track_id INTEGER NOT NULL,
            direction TEXT NOT NULL,
            vehicle_type TEXT NOT NULL,
            confidence REAL,
            timestamp TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_crossings_lane ON crossings(lane_id)"
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS video_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_name TEXT NOT NULL,
            stored_path TEXT NOT NULL UNIQUE,
            size_bytes INTEGER NOT NULL DEFAULT 0,
            source_label TEXT NOT NULL DEFAULT 'sin-nombre',
            project_id INTEGER REFERENCES projects(id),
            video_start_time TEXT,
            fps REAL,
            interval_minutes INTEGER NOT NULL DEFAULT 15,
            output_video_path TEXT,
            status TEXT NOT NULL DEFAULT 'queued',
            error TEXT,
            total_frames INTEGER,
            processed_frames INTEGER NOT NULL DEFAULT 0,
            uploaded_at TEXT NOT NULL DEFAULT (datetime('now')),
            started_at TEXT,
            finished_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS geocode_cache (
            query TEXT PRIMARY KEY,
            response_json TEXT NOT NULL,
            cached_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # Bases creadas antes de que existieran los proyectos
    _ensure_column(conn, "lane_configs", "project_id", "INTEGER REFERENCES projects(id)")
    _ensure_column(conn, "video_jobs", "project_id", "INTEGER REFERENCES projects(id)")
    conn.commit()

    _migrate_labels_to_projects(conn)


def _migrate_labels_to_projects(conn):
    """
    Migración idempotente: antes, videos y carriles se agrupaban por un texto
    libre (`video_jobs.source_label` / `lane_configs.camera_source`). Ahora el
    dueño es un proyecto real. Se crea un proyecto por cada etiqueta distinta
    que ya existiera y se rellena project_id, para que nadie pierda los aforos
    que ya había corrido.
    """
    labels = set()
    for row in conn.execute(
        "SELECT DISTINCT source_label AS label FROM video_jobs WHERE project_id IS NULL"
    ):
        if row["label"]:
            labels.add(row["label"])
    for row in conn.execute(
        "SELECT DISTINCT camera_source AS label FROM lane_configs WHERE project_id IS NULL"
    ):
        if row["label"]:
            labels.add(row["label"])

    if not labels:
        return

    for label in labels:
        conn.execute(
            "INSERT OR IGNORE INTO projects (name, description) VALUES (?, ?)",
            (label, "Creado automáticamente al migrar desde el nombre de sesión anterior")
        )
        project_id = conn.execute(
            "SELECT id FROM projects WHERE name = ?", (label,)
        ).fetchone()["id"]
        conn.execute(
            "UPDATE video_jobs SET project_id = ? WHERE source_label = ? AND project_id IS NULL",
            (project_id, label)
        )
        conn.execute(
            "UPDATE lane_configs SET project_id = ? WHERE camera_source = ? AND project_id IS NULL",
            (project_id, label)
        )
    conn.commit()
    logging.info(f"Migrados {len(labels)} nombres de sesión a proyectos")


# --- Proyectos (intersecciones) --------------------------------------------

def create_project(name: str, description: Optional[str] = None,
                    latitude: Optional[float] = None, longitude: Optional[float] = None,
                    address: Optional[str] = None, interval_minutes: int = 15) -> int:
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO projects (name, description, latitude, longitude, address, interval_minutes)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (name, description, latitude, longitude, address, interval_minutes)
    )
    conn.commit()
    return cur.lastrowid


def list_projects() -> List[Dict]:
    """
    Proyectos con sus estadísticas acumuladas — es lo que hace útil tener
    proyectos: la empresa ve cuánto aforo lleva medido en cada intersección
    a lo largo del tiempo, no solo la corrida de hoy.
    """
    conn = get_connection()
    rows = conn.execute("""
        SELECT p.*,
               (SELECT COUNT(*) FROM video_jobs v WHERE v.project_id = p.id) AS video_count,
               (SELECT COUNT(*) FROM video_jobs v WHERE v.project_id = p.id
                    AND v.status = 'awaiting_calibration') AS awaiting_count,
               (SELECT COUNT(*) FROM lane_configs l WHERE l.project_id = p.id AND l.active = 1) AS lane_count,
               (SELECT COUNT(*) FROM crossings c
                    JOIN lane_configs l ON c.lane_id = l.id
                    WHERE l.project_id = p.id) AS crossing_count
        FROM projects p
        ORDER BY p.name
    """).fetchall()
    return [dict(row) for row in rows]


def get_project(project_id: int) -> Optional[Dict]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return dict(row) if row else None


def update_project(project_id: int, **fields):
    allowed = {"name", "description", "latitude", "longitude", "address", "interval_minutes"}
    fields = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not fields:
        return
    conn = get_connection()
    set_clause = ", ".join(f"{key} = ?" for key in fields)
    params = list(fields.values()) + [project_id]
    conn.execute(
        f"UPDATE projects SET {set_clause}, updated_at = datetime('now') WHERE id = ?",
        params
    )
    conn.commit()


def delete_project(project_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()


# --- Carriles / líneas de conteo -------------------------------------------

def create_lane(
    camera_source: str,
    name: str,
    line_type: str,
    points: List[List[float]],
    project_id: Optional[int] = None
) -> int:
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO lane_configs (camera_source, project_id, name, line_type, points_json)
           VALUES (?, ?, ?, ?, ?)""",
        (camera_source, project_id, name, line_type, json.dumps(points))
    )
    conn.commit()
    return cur.lastrowid


def list_lanes(camera_source: Optional[str] = None, active_only: bool = True,
                project_id: Optional[int] = None) -> List[Dict]:
    conn = get_connection()
    query = "SELECT * FROM lane_configs"
    conditions = []
    params = []
    if project_id is not None:
        conditions.append("project_id = ?")
        params.append(project_id)
    elif camera_source is not None:
        conditions.append("camera_source = ?")
        params.append(camera_source)
    if active_only:
        conditions.append("active = 1")
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY id"
    rows = conn.execute(query, params).fetchall()
    lanes = []
    for row in rows:
        lane = dict(row)
        lane["points"] = json.loads(lane.pop("points_json"))
        lanes.append(lane)
    return lanes


def update_lane(lane_id: int, name: Optional[str] = None,
                 line_type: Optional[str] = None,
                 points: Optional[List[List[float]]] = None):
    conn = get_connection()
    fields, params = [], []
    if name is not None:
        fields.append("name = ?")
        params.append(name)
    if line_type is not None:
        fields.append("line_type = ?")
        params.append(line_type)
    if points is not None:
        fields.append("points_json = ?")
        params.append(json.dumps(points))
    if not fields:
        return
    fields.append("updated_at = datetime('now')")
    params.append(lane_id)
    conn.execute(f"UPDATE lane_configs SET {', '.join(fields)} WHERE id = ?", params)
    conn.commit()


def delete_lane(lane_id: int):
    """Borrado lógico: se conserva el historial de cruces asociado."""
    conn = get_connection()
    conn.execute("UPDATE lane_configs SET active = 0 WHERE id = ?", (lane_id,))
    conn.commit()


# --- Cruces / conteos --------------------------------------------------

def record_crossing(lane_id: int, track_id: int, direction: str,
                     vehicle_type: str, confidence: float,
                     timestamp: Optional[str] = None):
    """
    timestamp: hora REAL del cruce en formato ISO ('YYYY-MM-DD HH:MM:SS').
    En la cámara en vivo se omite (usa la hora del reloj del sistema).
    En videos subidos SIEMPRE se pasa explícito, calculado como
    video_start_time + (frame/fps) — si no, todos los cruces quedarían
    con la hora en que se PROCESÓ el archivo en vez de la hora en que
    ocurrieron de verdad, y los reportes por intervalo saldrían mal.
    """
    conn = get_connection()
    if timestamp:
        conn.execute(
            """INSERT INTO crossings (lane_id, track_id, direction, vehicle_type, confidence, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (lane_id, track_id, direction, vehicle_type, confidence, timestamp)
        )
    else:
        conn.execute(
            """INSERT INTO crossings (lane_id, track_id, direction, vehicle_type, confidence)
               VALUES (?, ?, ?, ?, ?)""",
            (lane_id, track_id, direction, vehicle_type, confidence)
        )
    conn.commit()


def get_counts(lane_id: Optional[int] = None) -> List[Dict]:
    """
    Conteos agregados por carril, dirección y tipo de vehículo.
    Se calculan siempre desde la tabla `crossings` (fuente única de verdad),
    no se mantiene un contador separado que se pueda desincronizar.
    """
    conn = get_connection()
    query = """
        SELECT lane_id, direction, vehicle_type, COUNT(*) as total
        FROM crossings
    """
    params = []
    if lane_id is not None:
        query += " WHERE lane_id = ?"
        params.append(lane_id)
    query += " GROUP BY lane_id, direction, vehicle_type"
    rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


# --- Videos subidos (procesamiento por lote, no en vivo) ---------------

def create_video_job(
    original_name: str, stored_path: str, size_bytes: int = 0,
    source_label: str = "sin-nombre", video_start_time: Optional[str] = None,
    interval_minutes: int = 15, project_id: Optional[int] = None,
    status: str = "awaiting_calibration"
) -> int:
    """
    status por defecto es 'awaiting_calibration': el video NO se procesa al
    subirlo. Primero el usuario define los carriles sobre un frame real, y
    recién entonces presiona "Empezar conteo". Así el conteo nunca depende de
    una línea inventada que quizá no cruza la vía en esa cámara.
    """
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO video_jobs
           (original_name, stored_path, size_bytes, source_label, project_id,
            video_start_time, interval_minutes, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (original_name, stored_path, size_bytes, source_label, project_id,
         video_start_time, interval_minutes, status)
    )
    conn.commit()
    return cur.lastrowid


def list_video_jobs(project_id: Optional[int] = None) -> List[Dict]:
    conn = get_connection()
    if project_id is not None:
        rows = conn.execute(
            "SELECT * FROM video_jobs WHERE project_id = ? ORDER BY id DESC", (project_id,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM video_jobs ORDER BY id DESC").fetchall()
    return [dict(row) for row in rows]


def get_awaiting_calibration_jobs(project_id: int) -> List[Dict]:
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM video_jobs
           WHERE project_id = ? AND status = 'awaiting_calibration'
           ORDER BY video_start_time, id""",
        (project_id,)
    ).fetchall()
    return [dict(row) for row in rows]


def get_video_job(job_id: int) -> Optional[Dict]:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM video_jobs WHERE id = ?", (job_id,)
    ).fetchone()
    return dict(row) if row else None


def get_queued_video_jobs() -> List[Dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM video_jobs WHERE status IN ('queued', 'processing') ORDER BY id"
    ).fetchall()
    return [dict(row) for row in rows]


def update_video_job(job_id: int, **fields):
    """
    Actualiza cualquier combinación de columnas de video_jobs.
    Ej: update_video_job(5, status='processing', started_at=...)
    """
    if not fields:
        return
    conn = get_connection()
    set_clause = ", ".join(f"{key} = ?" for key in fields)
    params = list(fields.values()) + [job_id]
    conn.execute(f"UPDATE video_jobs SET {set_clause} WHERE id = ?", params)
    conn.commit()


def delete_video_job(job_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM video_jobs WHERE id = ?", (job_id,))
    conn.commit()


def mark_video_job_started(job_id: int):
    conn = get_connection()
    conn.execute(
        "UPDATE video_jobs SET status='processing', started_at=datetime('now') WHERE id = ?",
        (job_id,)
    )
    conn.commit()


def mark_video_job_finished(job_id: int):
    conn = get_connection()
    conn.execute(
        "UPDATE video_jobs SET status='done', finished_at=datetime('now') WHERE id = ?",
        (job_id,)
    )
    conn.commit()


def get_video_jobs_by_project(project_id: int) -> List[Dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM video_jobs WHERE project_id = ? ORDER BY video_start_time",
        (project_id,)
    ).fetchall()
    return [dict(row) for row in rows]


def get_interval_counts(project_id: int, interval_minutes: int = 15) -> Dict:
    """
    Conteos agrupados en intervalos de tiempo REALES (ej. 8:00-8:15,
    8:15-8:30...), la salida clásica de un estudio de aforo manual.

    El rango de intervalos se calcula a partir de los videos del proyecto
    (video_start_time -> video_start_time + duración), así un intervalo de
    15 min sin ningún vehículo aparece igual con conteo 0 en vez de
    desaparecer del reporte. Varios segmentos del mismo proyecto se unen
    aquí por su hora real — es lo que permite subir el aforo de una hora en
    partes de 10 min y verlo como un solo estudio continuo. Si el proyecto
    no tiene videos con hora de inicio (ej. cámara en vivo), se usa el rango
    de cruces observados como respaldo.
    """
    import datetime as _dt

    conn = get_connection()
    lanes = list_lanes(project_id=project_id, active_only=False)
    if not lanes:
        return {"lanes": [], "interval_minutes": interval_minutes}

    lane_ids = [lane["id"] for lane in lanes]
    placeholders = ",".join("?" * len(lane_ids))

    # 1. Determinar el rango de tiempo a cubrir
    range_start = range_end = None
    jobs = get_video_jobs_by_project(project_id)
    for job in jobs:
        if not job.get("video_start_time"):
            continue
        start = _dt.datetime.fromisoformat(job["video_start_time"])
        duration_s = (job["total_frames"] / job["fps"]) if job.get("fps") and job.get("total_frames") else 0
        end = start + _dt.timedelta(seconds=duration_s)
        range_start = start if range_start is None else min(range_start, start)
        range_end = end if range_end is None else max(range_end, end)

    if range_start is None:
        row = conn.execute(
            f"SELECT MIN(timestamp) as lo, MAX(timestamp) as hi FROM crossings WHERE lane_id IN ({placeholders})",
            lane_ids
        ).fetchone()
        if not row["lo"]:
            return {"lanes": [{"lane_id": l["id"], "lane_name": l["name"], "intervals": []} for l in lanes],
                    "interval_minutes": interval_minutes}
        range_start = _dt.datetime.fromisoformat(row["lo"])
        range_end = _dt.datetime.fromisoformat(row["hi"]) + _dt.timedelta(seconds=1)

    # 2. Construir los cajones (buckets) vacíos, alineados a la hora en punto
    bucket_start = range_start.replace(
        minute=(range_start.minute // interval_minutes) * interval_minutes,
        second=0, microsecond=0
    )
    buckets = []
    cursor = bucket_start
    delta = _dt.timedelta(minutes=interval_minutes)
    while cursor < range_end:
        buckets.append(cursor)
        cursor += delta
    if not buckets:
        buckets = [bucket_start]

    # 3. Traer todos los cruces del rango y clasificarlos en su cajón
    rows = conn.execute(
        f"""SELECT lane_id, direction, vehicle_type, timestamp FROM crossings
            WHERE lane_id IN ({placeholders})
            ORDER BY timestamp""",
        lane_ids
    ).fetchall()

    result_lanes = []
    for lane in lanes:
        interval_map = {b: {"in": 0, "out": 0, "total": 0, "by_vehicle_type": {}} for b in buckets}
        for row in rows:
            if row["lane_id"] != lane["id"]:
                continue
            ts = _dt.datetime.fromisoformat(row["timestamp"])
            offset_minutes = (ts - bucket_start).total_seconds() / 60
            idx = int(offset_minutes // interval_minutes)
            if idx < 0 or idx >= len(buckets):
                continue
            bucket = interval_map[buckets[idx]]
            bucket[row["direction"]] += 1
            bucket["total"] += 1
            vt = bucket["by_vehicle_type"].setdefault(row["vehicle_type"], {"in": 0, "out": 0})
            vt[row["direction"]] += 1

        result_lanes.append({
            "lane_id": lane["id"],
            "lane_name": lane["name"],
            "intervals": [
                {
                    "start": b.strftime("%Y-%m-%d %H:%M:%S"),
                    "end": (b + delta).strftime("%Y-%m-%d %H:%M:%S"),
                    **interval_map[b]
                }
                for b in buckets
            ]
        })

    return {"lanes": result_lanes, "interval_minutes": interval_minutes}
