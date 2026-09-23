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
from collections import defaultdict
from datetime import datetime
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
        # timeout alto a propósito: con la cola escribiendo cruces y la API
        # insertando una subida de cientos de videos, el valor por omisión (5 s)
        # se agota y SQLite lanza "database is locked". Una vez eso mató el
        # hilo de la cola y dejó 741 videos sin procesar.
        conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=60.0)
        conn.execute("PRAGMA journal_mode=WAL")
        # SQLite declara las claves foráneas pero NO las aplica salvo que
        # se le pida explícitamente, y por conexión. Sin esto, un borrado
        # incompleto deja huérfanos en silencio: ya pasó con 95 cruces y 7
        # carriles que sobrevivieron al proyecto que los contenía.
        conn.execute("PRAGMA foreign_keys = ON")
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
    # De qué video salió cada cruce. Sin esto no se pueden borrar los cruces
    # anteriores al reprocesar un video, y los conteos se DUPLICAN cada vez
    # que se recalibra y se vuelve a contar — que es justo lo que se quiere
    # hacer cuando la primera calibración salió mal.
    _ensure_column(conn, "crossings", "job_id", "INTEGER")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_crossings_job ON crossings(job_id)"
    )
    # Alto de la caja del vehículo, en píxeles, en el momento del cruce.
    # Es la cifra que decide si el detector puede con el material: la
    # PT-914 y nuestra propia medición coinciden en que por debajo de unos
    # 40 px el detector empieza a perder vehículos, y con 18 px de día y 13
    # de noche —lo que da la cámara actual— eso ya está pasando. Guardarlo
    # en cada cruce convierte esa medición puntual en un dato continuo.
    _ensure_column(conn, "crossings", "bbox_height", "INTEGER")
    # Ancho de la caja en el cruce. Con la cámara de lado no decía nada del
    # tamaño real (un tractocamión visto de perfil es larguísimo y un autobús
    # también), pero DE FRENTE el ancho es el ancho del vehículo: 1.8 m un
    # sedán, 2.0 una pickup, 2.5 un camión. Junto con el alto da la silueta,
    # que es lo que separa una troca de un automóvil.
    _ensure_column(conn, "crossings", "bbox_width", "INTEGER")
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
    # Zonas: polígonos dibujados sobre el video que delimitan la calzada.
    #
    # Existen porque en perspectiva las dos calzadas se ven muy distintas —
    # la cercana ocupa media pantalla y la del fondo cabe en una franja de
    # 15 px — y el detector no tiene forma de saber cuál es cuál. Con el
    # polígono dibujado a mano, cada cruce se puede atribuir a su calzada,
    # y todo lo que cae fuera (banquetas, estacionamientos, el patio del
    # frente) deja de contarse.
    #
    # kind: 'calzada' cuenta y atribuye; 'excluir' descarta lo que caiga
    # dentro, para zonas donde hay movimiento que no es tránsito.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS zones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            name TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'calzada',
            points_json TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_zones_project ON zones(project_id)"
    )
    # En qué calzada ocurrió el cruce. Nulo cuando el proyecto no tiene
    # zonas dibujadas, que es el caso de todos los aforos anteriores.
    _ensure_column(conn, "crossings", "zone_id", "INTEGER")

    # Calzada a la que pertenece una línea de conteo.
    #
    # Sin esto, una línea cuenta CUALQUIER vehículo que la cruce, venga de
    # la calzada que venga. En perspectiva las dos calzadas se superponen,
    # así que una línea trazada sobre la calzada del fondo también recoge
    # los vehículos de la cercana: medido en un aforo real, la línea de
    # arriba se llevó 240 cruces que eran de abajo, y la de abajo se quedó
    # corta. Atar la línea a su calzada es lo que separa los dos flujos.
    #
    # Nulo = cuenta todo lo que la cruce, como antes.
    _ensure_column(conn, "lane_configs", "zone_id", "INTEGER")

    # Tramo de velocidad de la línea: una segunda línea y la distancia en el
    # pavimento entre las dos, como las dos mangueras del contador de ejes.
    # JSON {"linea": [[x, y], [x, y]], "distancia_m": 15.0}; nulo = la línea
    # solo cuenta.
    _ensure_column(conn, "lane_configs", "tramo_json", "TEXT")

    # Filtro de cajas repetidas ENTRE clases (agnostic NMS), por proyecto.
    #
    # El de YOLO compara solo dentro de cada clase, así que un mismo vehículo
    # detectado a la vez como 'car' y como 'truck' deja dos cajas con IoU de
    # 0.97 y la línea lo cuenta dos veces. Comparar entre clases lo arregla…
    # pero en material donde el vehículo mide 15 px y las cajas se encinan,
    # borra vehículos DISTINTOS. Medido:
    #
    #   cámara nueva (2560x1440, vehículo 150 px): 476 cajas repetidas -> 0,
    #       y los cruces de un minuto pasan de 34 a 32 (los duplicados).
    #   cámara vieja (640x360, vehículo 15-40 px): la calzada del fondo baja
    #       de 226 a 210 cruces, y esa ya iba corta contra el conteo manual.
    #
    # Por eso es por proyecto y por omisión queda apagado, como siempre.
    _ensure_column(conn, "projects", "nms_agnostico", "INTEGER DEFAULT 0")

    # Contar por TRAYECTORIA en vez de por instante (ver
    # src/engine/conteo_trayectoria.py): cada vehículo cuenta una sola vez
    # por línea, con los pedazos de su rastro ya unidos. Es la práctica
    # aceptada para que un cambio de identidad sobre la línea no cuente dos
    # veces. Por proyecto y apagado por omisión: los aforos ya validados
    # contra conteo manual se contaron por instante.
    # Escribir el video anotado cuesta ~25 % del tiempo de proceso (dibujar
    # 22 ms + escribir 15 de los ~150 ms por cuadro) MAS una pasada entera de
    # ffmpeg al final, y ocupa mas disco que el material original: medido en
    # el aforo frontal, 31.3 MB por minuto de video contra 16 del archivo de
    # la camara. Con 730 videos son 23 GB. Vale la pena para revisar un
    # aforo; no para un dia entero ya calibrado.
    _ensure_column(conn, "projects", "video_anotado", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(conn, "projects", "conteo_trayectoria", "INTEGER DEFAULT 0")
    # Segundos que tardó el vehículo en recorrer el tramo de su línea. Se
    # guarda el TIEMPO y no la velocidad: la velocidad sale de la distancia
    # vigente al reportar, así que corregir una distancia mal capturada
    # corrige todo sin volver a contar. Nulo cuando la línea no tiene tramo o
    # el rastro no atravesó las dos líneas.
    _ensure_column(conn, "crossings", "tiempo_tramo_s", "REAL")

    # Aforo direccional: un renglón por vehículo con su acceso de origen y
    # de destino. Va en tabla aparte y no en `crossings` porque no es un
    # cruce de línea: se decide al cerrar el video, cuando ya se pudieron
    # unir los pedazos de rastro que partió una oclusión
    # (src/engine/origen_destino.py). Destino u origen nulos = movimiento
    # incompleto, que se declara aparte en vez de adivinarse.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS movimientos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            job_id INTEGER REFERENCES video_jobs(id),
            origen_id INTEGER REFERENCES zones(id),
            destino_id INTEGER REFERENCES zones(id),
            vehicle_type TEXT NOT NULL,
            bbox_height INTEGER,
            confidence REAL,
            pedazos INTEGER NOT NULL DEFAULT 1,
            timestamp TEXT NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_movimientos_proyecto ON movimientos(project_id, timestamp)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_movimientos_job ON movimientos(job_id)"
    )
    # Recorrido compacto de cada vehículo (JSON, hasta 48 puntos). Con él el
    # informe decide el movimiento por trayectoria y no solo por las zonas
    # que pisó (src/engine/od_trayectoria.py). Los movimientos guardados
    # antes no lo tienen y se siguen decidiendo por zonas.
    _ensure_column(conn, "movimientos", "recorrido", "TEXT")

    # Diagnóstico del encuadre de un video: qué tan apto es para aforar,
    # medido ANTES de contarlo. Se guarda para no repetir el cálculo y para
    # que quede en el historial de la intersección: si el aforo sale bajo,
    # el diagnóstico dice si era esperable.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS diagnosticos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL UNIQUE REFERENCES video_jobs(id),
            project_id INTEGER REFERENCES projects(id),
            puntaje INTEGER NOT NULL,
            veredicto TEXT NOT NULL,
            color TEXT NOT NULL,
            etapa TEXT NOT NULL,
            datos TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # Registro de lo que se le ha hecho a cada intersección. Un aforo
    # sustenta decisiones de obra, así que tiene que poder responder
    # "¿de dónde salió esta cifra?": con qué calibración se contó, cuándo
    # se recalibró, qué videos entraron y cuáles se quitaron. Sin esto,
    # dos reportes distintos del mismo proyecto no se pueden explicar.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS project_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            kind TEXT NOT NULL,
            summary TEXT NOT NULL,
            detail TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_project ON project_events(project_id, id DESC)"
    )
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
                    address: Optional[str] = None, interval_minutes: int = 15,
                    nms_agnostico: bool = False,
                    conteo_trayectoria: bool = False,
                    video_anotado: bool = True) -> int:
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO projects (name, description, latitude, longitude, address,
                                 interval_minutes, nms_agnostico, conteo_trayectoria,
                                 video_anotado)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (name, description, latitude, longitude, address, interval_minutes,
         1 if nms_agnostico else 0, 1 if conteo_trayectoria else 0,
         1 if video_anotado else 0)
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
    # Las banderas del motor tambien se cambian aqui. Antes solo se podian
    # fijar al CREAR el proyecto, asi que un aforo ya subido no se podia
    # corregir sin rehacerlo: es la misma trampa de los valores que existen
    # pero no se leen, del otro lado.
    allowed = {"name", "description", "latitude", "longitude", "address",
               "interval_minutes", "nms_agnostico", "conteo_trayectoria",
               "video_anotado"}
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


def delete_project(project_id: int) -> Dict:
    """
    Borra el proyecto y TODO lo que colgaba de él.

    Antes esto solo quitaba la fila de `projects` y dejaba atrás los
    carriles, las zonas, los cruces y los video_jobs apuntando a un
    proyecto inexistente. El aforo desaparecía de la lista pero sus
    conteos seguían sumando en las vistas que agregan por carril, y los
    archivos subidos se quedaban ocupando disco para siempre — justo lo
    contrario de lo que se pide al borrar un proyecto para limpiar.

    Devuelve qué se borró, y los archivos a eliminar del disco: la base no
    es quien debe tocar el sistema de archivos.
    """
    conn = get_connection()
    jobs = conn.execute(
        "SELECT id, stored_path, output_video_path FROM video_jobs WHERE project_id = ?",
        (project_id,)
    ).fetchall()
    archivos = []
    for j in jobs:
        for ruta in (j["stored_path"], j["output_video_path"]):
            if ruta:
                archivos.append(ruta)

    borrados = {
        "crossings": conn.execute(
            """DELETE FROM crossings WHERE lane_id IN
               (SELECT id FROM lane_configs WHERE project_id = ?)""",
            (project_id,)
        ).rowcount,
        # Antes que videos y zonas: movimientos apunta a ambos con llave
        # foránea, y con foreign_keys activas borrarlos primero haría fallar
        # el borrado del proyecto entero.
        "movimientos": conn.execute(
            "DELETE FROM movimientos WHERE project_id = ?", (project_id,)
        ).rowcount,
        "diagnosticos": conn.execute(
            "DELETE FROM diagnosticos WHERE project_id = ?", (project_id,)
        ).rowcount,
        "videos": conn.execute(
            "DELETE FROM video_jobs WHERE project_id = ?", (project_id,)
        ).rowcount,
        "lanes": conn.execute(
            "DELETE FROM lane_configs WHERE project_id = ?", (project_id,)
        ).rowcount,
        "zones": conn.execute(
            "DELETE FROM zones WHERE project_id = ?", (project_id,)
        ).rowcount,
        # La bitácora también se va con el proyecto: si quedara, apuntaría
        # a una intersección que ya no existe y no se podría leer.
        "eventos": conn.execute(
            "DELETE FROM project_events WHERE project_id = ?", (project_id,)
        ).rowcount,
    }
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()
    borrados["archivos"] = archivos
    return borrados


# --- Carriles / líneas de conteo -------------------------------------------

def create_lane(
    camera_source: str,
    name: str,
    line_type: str,
    points: List[List[float]],
    project_id: Optional[int] = None,
    zone_id: Optional[int] = None,
    tramo: Optional[Dict] = None
) -> int:
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO lane_configs
               (camera_source, project_id, name, line_type, points_json, zone_id,
                tramo_json)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (camera_source, project_id, name, line_type, json.dumps(points), zone_id,
         json.dumps(tramo) if tramo else None)
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
        tramo = lane.pop("tramo_json", None)
        lane["tramo"] = json.loads(tramo) if tramo else None
        lanes.append(lane)
    return lanes


def update_lane(lane_id: int, name: Optional[str] = None,
                 line_type: Optional[str] = None,
                 points: Optional[List[List[float]]] = None,
                 zone_id: Optional[int] = None,
                 tramo: Optional[Dict] = None,
                 quitar_tramo: bool = False):
    conn = get_connection()
    fields, params = [], []
    # Corregir solo la distancia del tramo no toca la geometría: la base
    # guarda el tiempo de paso y la velocidad se recalcula al reportar, así
    # que los videos ya contados siguen vigentes. Mover la línea sí obliga a
    # volver a contar.
    solo_distancia = False
    if tramo is not None:
        previo = conn.execute("SELECT tramo_json FROM lane_configs WHERE id = ?",
                              (lane_id,)).fetchone()
        previo = json.loads(previo[0]) if previo and previo[0] else None
        solo_distancia = bool(previo) and previo.get("linea") == tramo.get("linea")
    if tramo is not None or quitar_tramo:
        fields.append("tramo_json = ?")
        params.append(json.dumps(tramo) if tramo else None)
    if name is not None:
        fields.append("name = ?")
        params.append(name)
    if line_type is not None:
        fields.append("line_type = ?")
        params.append(line_type)
    if points is not None:
        fields.append("points_json = ?")
        params.append(json.dumps(points))
    # 0 se interpreta como "desatar de la calzada": desde el formulario no
    # hay forma de mandar NULL, y sin esto una línea atada por error se
    # quedaba atada para siempre.
    if zone_id is not None:
        fields.append("zone_id = ?")
        params.append(zone_id or None)
    if not fields:
        return
    geometria = [f for f in fields if not f.startswith("name")]
    if not (solo_distancia and len(geometria) == 1):
        fields.append("updated_at = datetime('now')")
    params.append(lane_id)
    conn.execute(f"UPDATE lane_configs SET {', '.join(fields)} WHERE id = ?", params)
    conn.commit()


def delete_lane(lane_id: int):
    """Borrado lógico: se conserva el historial de cruces asociado."""
    conn = get_connection()
    conn.execute("UPDATE lane_configs SET active = 0 WHERE id = ?", (lane_id,))
    conn.commit()


# --- Zonas / calzadas dibujadas ----------------------------------------

def create_zone(project_id: int, name: str, points: List[List[float]],
                kind: str = 'calzada') -> int:
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO zones (project_id, name, kind, points_json)
           VALUES (?, ?, ?, ?)""",
        (project_id, name, kind, json.dumps(points))
    )
    conn.commit()
    return cur.lastrowid


def list_zones(project_id: int, active_only: bool = True) -> List[Dict]:
    conn = get_connection()
    query = "SELECT * FROM zones WHERE project_id = ?"
    if active_only:
        query += " AND active = 1"
    query += " ORDER BY id"
    rows = conn.execute(query, (project_id,)).fetchall()
    zones = []
    for row in rows:
        z = dict(row)
        z['points'] = json.loads(z.pop('points_json'))
        zones.append(z)
    return zones


def update_zone(zone_id: int, name: Optional[str] = None,
                kind: Optional[str] = None,
                points: Optional[List[List[float]]] = None):
    conn = get_connection()
    fields, params = [], []
    if name is not None:
        fields.append("name = ?")
        params.append(name)
    if kind is not None:
        fields.append("kind = ?")
        params.append(kind)
    if points is not None:
        fields.append("points_json = ?")
        params.append(json.dumps(points))
    if not fields:
        return
    fields.append("updated_at = datetime('now')")
    params.append(zone_id)
    conn.execute(f"UPDATE zones SET {', '.join(fields)} WHERE id = ?", params)
    conn.commit()


def delete_zone(zone_id: int):
    """Borrado lógico, igual que los carriles: los cruces ya atribuidos a
    esta zona conservan su zone_id y el histórico sigue teniendo sentido."""
    conn = get_connection()
    conn.execute("UPDATE zones SET active = 0 WHERE id = ?", (zone_id,))
    conn.commit()


# --- Cruces / conteos --------------------------------------------------

def record_movimientos(project_id: int, job_id: Optional[int],
                       movimientos: List[Dict]) -> int:
    """Guarda de una vez los movimientos de un video (ver tabla movimientos)."""
    if not movimientos:
        return 0
    conn = get_connection()
    conn.executemany(
        """INSERT INTO movimientos (project_id, job_id, origen_id, destino_id,
                                    vehicle_type, bbox_height, confidence,
                                    pedazos, timestamp, recorrido)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [(project_id, job_id, m['origen_id'], m['destino_id'], m['vehicle_type'],
          m.get('bbox_height'), m.get('confidence'), m.get('pedazos', 1),
          m['timestamp'],
          json.dumps(m['recorrido'], separators=(',', ':')) if m.get('recorrido') else None)
         for m in movimientos]
    )
    conn.commit()
    return len(movimientos)


def guardar_diagnostico(job_id: int, project_id: Optional[int], d: Dict) -> None:
    """Un diagnóstico por video; rehacerlo reemplaza al anterior."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO diagnosticos (job_id, project_id, puntaje, veredicto, color, etapa, datos)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(job_id) DO UPDATE SET
             puntaje=excluded.puntaje, veredicto=excluded.veredicto, color=excluded.color,
             etapa=excluded.etapa, datos=excluded.datos, created_at=datetime('now')""",
        (job_id, project_id, d['diagnostico']['puntaje'], d['diagnostico']['veredicto'],
         d['diagnostico']['color'], d['diagnostico'].get('etapa', 'solo imagen'),
         json.dumps(d, ensure_ascii=False))
    )
    conn.commit()


def get_diagnostico(job_id: int) -> Optional[Dict]:
    conn = get_connection()
    fila = conn.execute("SELECT * FROM diagnosticos WHERE job_id = ?", (job_id,)).fetchone()
    if fila is None:
        return None
    d = dict(fila)
    d['datos'] = json.loads(d['datos'])
    return d


def list_diagnosticos(project_id: int) -> List[Dict]:
    conn = get_connection()
    salida = []
    for fila in conn.execute(
        "SELECT * FROM diagnosticos WHERE project_id = ? ORDER BY job_id", (project_id,)
    ):
        d = dict(fila)
        d['datos'] = json.loads(d['datos'])
        salida.append(d)
    return salida


def delete_movimientos_for_job(job_id: int) -> int:
    """Igual que con los cruces: reprocesar un video no debe duplicar su aforo."""
    conn = get_connection()
    cur = conn.execute("DELETE FROM movimientos WHERE job_id = ?", (job_id,))
    conn.commit()
    return cur.rowcount


# Decidir por trayectoria cuesta unos segundos sobre un aforo de miles de
# vehículos y el informe lo pide cada vez que cambia el intervalo: se guarda
# el resultado mientras los movimientos del proyecto no cambien.
_cache_trayectoria: Dict = {}


def _decidir_por_trayectoria(project_id: int, filas) -> Dict:
    from src.engine import od_trayectoria

    firma = (len(filas), max((f['id'] for f in filas), default=0))
    guardado = _cache_trayectoria.get(project_id)
    if guardado and guardado[0] == firma:
        return guardado[1]

    registros = []
    for f in filas:
        ts = datetime.fromisoformat(f['timestamp'])
        rec = json.loads(f['recorrido']) if f['recorrido'] else None
        if rec:
            # La hora de inicio del video da la precisión de centésimas que
            # necesita el emparejamiento de pedazos; el timestamp del
            # movimiento viene truncado al segundo.
            if f['video_start_time']:
                inicio = datetime.fromisoformat(f['video_start_time']).timestamp()
            else:
                inicio = ts.timestamp() - rec['t'][0]
            reg = od_trayectoria.registro(f['origen_id'], f['destino_id'], rec, inicio,
                                          f['job_id'], f['vehicle_type'], clave=f['id'])
        else:
            reg = {'org': f['origen_id'], 'dst': f['destino_id'], 'video': f['job_id'],
                   'clave': f['id'], 't0': ts.timestamp(), 't1': ts.timestamp(),
                   'puntos': None, 'fin_en_destino': False, 'vehicle_type': f['vehicle_type']}
        registros.append(reg)
    decision = od_trayectoria.decidir(registros)
    resultado = {'vehiculos': decision['vehiculos'], 'sin_decidir': decision['sin_decidir'],
                 'motivos': decision['motivos'], 'rozadas': decision['rozadas']}
    _cache_trayectoria[project_id] = (firma, resultado)
    return resultado


def get_matriz_od(project_id: int, interval_minutes: int = 15,
                  metodo: str = 'trayectoria') -> Dict:
    """
    Aforo direccional agregado: por intervalo, origen, destino y clase.

    metodo:
      'trayectoria' — cada vehículo se decide por la forma de su recorrido
         (src/engine/od_trayectoria.py): recupera los que un obstáculo dejó a
         medias y corrige las zonas rozadas. En Entrada y salida Altozano,
         0.99x contra el conteo manual donde las zonas daban 0.74x.
      'zonas' — solo los que se vieron entrar y salir por un acceso.

    Los que no se pueden decidir se declaran aparte, con su motivo, y no se
    reparten entre los movimientos: repartirlos es suponer a dónde iban.
    """
    conn = get_connection()
    accesos = {z['id']: z['name'] for z in list_zones(project_id, active_only=False)
               if z.get('kind') == 'acceso'}
    filas = conn.execute(
        """SELECT m.id, m.job_id, m.origen_id, m.destino_id, m.vehicle_type, m.timestamp,
                  m.recorrido, v.video_start_time
           FROM movimientos m LEFT JOIN video_jobs v ON v.id = m.job_id
           WHERE m.project_id = ? ORDER BY m.timestamp""",
        (project_id,)
    ).fetchall()

    def intervalo(d):
        m = (d.hour * 60 + d.minute) // interval_minutes * interval_minutes
        return d.strftime('%Y-%m-%d') + f' {m // 60:02d}:{m % 60:02d}'

    completos, incompletos = defaultdict(int), defaultdict(int)
    # Volumen por acceso: cuántos ENTRARON y cuántos SALIERON por cada brazo.
    # Cuenta también los movimientos incompletos, y esa es la razón de ser de
    # este bloque: un vehículo del que no se vio el destino sigue diciendo por
    # dónde entró. La matriz origen-destino exige seguirlo por todo el cruce;
    # el volumen por acceso solo exige verlo entrar o salir, así que se puede
    # entregar en cámaras donde la matriz no alcanza. Medido contra el conteo
    # manual de Entrada y salida Altozano: 5 de 6 cifras con GEH < 5.
    entradas, salidas = defaultdict(int), defaultdict(int)
    rozadas = set()

    resumen = {}
    if metodo == 'trayectoria' and any(f['recorrido'] for f in filas):
        decision = _decidir_por_trayectoria(project_id, filas)
        for v in decision['vehiculos']:
            clave_t = intervalo(datetime.fromtimestamp(v['t0']))
            completos[(clave_t, v['origen_id'], v['destino_id'], v['vehicle_type'])] += 1
        for s in decision['sin_decidir']:
            incompletos[(intervalo(datetime.fromtimestamp(s['t0'])),
                         s['origen_id'], s['destino_id'])] += 1
        resumen = decision['motivos']
        rozadas = set(decision['rozadas'])
    else:
        metodo = 'zonas'
        for f in filas:
            clave_t = intervalo(datetime.fromisoformat(f['timestamp']))
            if f['origen_id'] is not None and f['destino_id'] is not None:
                completos[(clave_t, f['origen_id'], f['destino_id'], f['vehicle_type'])] += 1
            else:
                incompletos[(clave_t, f['origen_id'], f['destino_id'])] += 1

    # Entradas y salidas por lo que se VIO en cada acceso, y no por la
    # decisión por trayectoria. Medido a las 7:30 en Entrada y salida
    # Altozano contra el manual: por zonas 5 de 6 cifras con GEH < 5, por
    # trayectoria 4 de 6 (el arco daba 306 entradas contra 253: el pedazo sin
    # decidir y el completado de un mismo vehículo contaban cada uno su
    # entrada). La única corrección que sí se toma de la trayectoria: una
    # zona solo rozada no es una salida (Derecha tenía 121 "salidas").
    for f in filas:
        clave_t = intervalo(datetime.fromisoformat(f['timestamp']))
        if f['origen_id'] is not None:
            entradas[(clave_t, f['origen_id'])] += 1
        if f['destino_id'] is not None and f['id'] not in rozadas:
            salidas[(clave_t, f['destino_id'])] += 1
    return {
        'accesos': accesos,
        'intervalo_minutos': interval_minutes,
        'metodo': metodo,
        # Cuántos vehículos se decidieron de cada forma y por qué quedaron
        # los demás sin decidir: el informe lo declara.
        'resumen_metodo': resumen,
        'movimientos': [
            {'intervalo': t, 'origen_id': o, 'destino_id': d, 'vehicle_type': c, 'total': n}
            for (t, o, d, c), n in sorted(completos.items(), key=lambda kv: str(kv[0]))
        ],
        'incompletos': [
            {'intervalo': t, 'origen_id': o, 'destino_id': d, 'total': n}
            for (t, o, d), n in sorted(incompletos.items(), key=lambda kv: str(kv[0]))
        ],
        'por_acceso': [
            {'intervalo': t, 'acceso_id': a,
             'entradas': entradas[(t, a)], 'salidas': salidas[(t, a)]}
            for t, a in sorted(set(entradas) | set(salidas), key=lambda k: (k[0], k[1]))
        ],
    }


def record_crossing(lane_id: int, track_id: int, direction: str,
                     vehicle_type: str, confidence: float,
                     timestamp: Optional[str] = None,
                     job_id: Optional[int] = None,
                     zone_id: Optional[int] = None,
                     bbox_height: Optional[int] = None,
                     bbox_width: Optional[int] = None):
    """
    timestamp: hora REAL del cruce en formato ISO ('YYYY-MM-DD HH:MM:SS').
    En la cámara en vivo se omite (usa la hora del reloj del sistema).
    En videos subidos SIEMPRE se pasa explícito, calculado como
    video_start_time + (frame/fps) — si no, todos los cruces quedarían
    con la hora en que se PROCESÓ el archivo en vez de la hora en que
    ocurrieron de verdad, y los reportes por intervalo saldrían mal.

    job_id: video del que salió el cruce, para poder borrar los cruces
    anteriores si ese mismo video se vuelve a procesar.

    zone_id: calzada dibujada dentro de la que ocurrió el cruce. Es lo que
    permite separar los sentidos cuando en perspectiva las dos calzadas
    quedan una encima de la otra y la línea de conteo cruza ambas.
    """
    conn = get_connection()
    if timestamp:
        conn.execute(
            """INSERT INTO crossings (lane_id, track_id, direction, vehicle_type,
                                      confidence, timestamp, job_id, zone_id,
                                      bbox_height, bbox_width)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (lane_id, track_id, direction, vehicle_type, confidence, timestamp,
             job_id, zone_id, bbox_height, bbox_width)
        )
    else:
        conn.execute(
            """INSERT INTO crossings (lane_id, track_id, direction, vehicle_type,
                                      confidence, job_id, zone_id, bbox_height,
                                      bbox_width)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (lane_id, track_id, direction, vehicle_type, confidence, job_id,
             zone_id, bbox_height, bbox_width)
        )
    conn.commit()


def set_crossing_times(job_id: int, tiempos) -> int:
    """Pone el tiempo de paso por el tramo a los cruces de un video:
    [(lane_id, track_id, segundos)].

    Se guarda al cerrar el video y no en el momento del cruce porque la
    segunda línea del tramo puede estar DESPUÉS de la de conteo: cuando el
    vehículo cuenta todavía no se sabe su velocidad.
    """
    if not tiempos:
        return 0
    conn = get_connection()
    cur = conn.executemany(
        "UPDATE crossings SET tiempo_tramo_s = ? "
        "WHERE job_id = ? AND lane_id = ? AND track_id = ?",
        [(round(s, 4), job_id, lane_id, track_id)
         for lane_id, track_id, s in tiempos])
    conn.commit()
    return cur.rowcount


def delete_crossings_for_job(job_id: int) -> int:
    """
    Borra los cruces registrados por un video. Se llama antes de volver a
    procesarlo: sin esto, recalibrar y reprocesar SUMA los cruces nuevos a
    los viejos y el aforo queda inflado al doble.
    """
    conn = get_connection()
    cur = conn.execute("DELETE FROM crossings WHERE job_id = ?", (job_id,))
    conn.commit()
    return cur.rowcount


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


def get_calibration_time(project_id: int) -> Optional[str]:
    """
    Cuándo se tocó por última vez la geometría de este proyecto.

    Es el dato que permite saber si un conteo ya terminado corresponde a
    la calibración actual o a una anterior. Sin esto, editar las líneas
    después de procesar deja los números viejos en pantalla sin que nada
    lo indique, y no hay forma de distinguir un aforo vigente de uno que
    quedó obsoleto.
    """
    conn = get_connection()
    row = conn.execute(
        """SELECT MAX(t) FROM (
               SELECT MAX(updated_at) AS t FROM lane_configs
               WHERE project_id = ? AND active = 1
               UNION ALL
               SELECT MAX(updated_at) AS t FROM zones
               WHERE project_id = ? AND active = 1
           )""",
        (project_id, project_id)
    ).fetchone()
    return row[0] if row else None


def get_stale_jobs(project_id: int) -> List[Dict]:
    """Videos ya procesados cuyo conteo salió de una calibración anterior."""
    calibrado = get_calibration_time(project_id)
    if not calibrado:
        return []
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM video_jobs
           WHERE project_id = ? AND status = 'done'
             AND (finished_at IS NULL OR finished_at < ?)
           ORDER BY video_start_time, id""",
        (project_id, calibrado)
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
    # movimientos.job_id y diagnosticos.job_id son llaves foráneas: sin esto
    # el borrado falla.
    conn.execute("DELETE FROM diagnosticos WHERE job_id = ?", (job_id,))
    conn.execute("DELETE FROM movimientos WHERE job_id = ?", (job_id,))
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
    # Solo carriles activos: los eliminados conservan su historial en la base
    # (por eso el borrado es lógico), pero incluirlos aquí inflaría el aforo
    # vigente con mediciones de una calibración que el usuario ya descartó.
    lanes = list_lanes(project_id=project_id, active_only=True)
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
        f"""SELECT lane_id, direction, vehicle_type, bbox_height, bbox_width,
                   confidence, timestamp, tiempo_tramo_s FROM crossings
            WHERE lane_id IN ({placeholders})
            ORDER BY timestamp""",
        lane_ids
    ).fetchall()

    # Las clases de COCO no salen de aquí hacia el usuario. `truck` mezcla
    # la pickup con el tractocamión, y la interfaz lo traducía a "Camión":
    # el reporte declaraba 1 501 camiones donde el aforo manual contó 417.
    # Se traduce a la taxonomía de la empresa, y donde el vehículo se ve
    # demasiado pequeño para separarlos no se clasifica nada.
    #
    # El umbral se saca por CARRIL y no por proyecto: cada carril cuenta
    # sobre una línea fija, o sea a una distancia fija de la cámara, que es
    # justo la condición que hace comparable el alto en píxeles.
    from src.engine.clasificacion import (CONFIANZA_MINIMA, MEDIDO, ESTIMADO,
                                          NO_RESOLUBLE, clasificar,
                                          nivel_de_calzada, perfil_de_calzada)

    # Dos preguntas distintas, y mezclarlas fue un error que costo una
    # version:
    #
    #   1. ¿Se puede medir a esta HORA?  -> lo dice la confianza, sobre el
    #      proyecto entero. Separa dia de noche.
    #   2. ¿Se puede clasificar en esta CALZADA? -> lo dice el ALTO del
    #      vehiculo. Separa la calzada cercana de la del fondo.
    #
    # Usar la confianza para las dos no funciona porque se solapan: la
    # calzada del fondo DE DIA da 0.53-0.66 y la cercana DE NOCHE da
    # 0.54-0.69. Con un umbral unico, la calzada del fondo se callaba a
    # todas horas aunque de dia su proporcion sale a 1.8 puntos del aforo
    # manual. El sistema se volvia perezoso donde si podia.
    def _hora(fila):
        return fila["timestamp"][11:13]

    por_hora_todos = {}
    for fila in rows:
        por_hora_todos.setdefault(_hora(fila), []).append(fila)
    horas_medibles = {
        h for h, fs in por_hora_todos.items()
        if [f["confidence"] for f in fs if f["confidence"] is not None]
        and sum(f["confidence"] for f in fs if f["confidence"] is not None)
        / max(1, len([f for f in fs if f["confidence"] is not None])) >= CONFIANZA_MINIMA
    }

    # El nivel de cada calzada sale del alto, sin confianza: esa ya decidio
    # que horas cuentan.
    niveles = {}
    for lane in lanes:
        propios = [f for f in rows if f["lane_id"] == lane["id"]]
        for h in {_hora(f) for f in propios}:
            if h not in horas_medibles:
                niveles[(lane["id"], h)] = (NO_RESOLUBLE, None)
                continue
            niveles[(lane["id"], h)] = nivel_de_calzada(
                f["bbox_height"] for f in propios
                if _hora(f) == h and f["vehicle_type"] == "car"
            )

    # Lo que se reporta del carril es de lo que ES CAPAZ en sus mejores
    # horas: un carril que clasifica de dia no deja de poder porque de noche
    # no. Y como el umbral es fisico —pixeles de alto— una camara mejor
    # sube el nivel sola, sin tocar codigo.
    orden = {MEDIDO: 2, ESTIMADO: 1, NO_RESOLUBLE: 0}
    mejor = {
        lane["id"]: max(
            [v for (lid, _), v in niveles.items() if lid == lane["id"]],
            key=lambda x: orden.get(x[0], 0), default=(NO_RESOLUBLE, None))
        for lane in lanes
    }
    umbrales = {k: v[1] for k, v in mejor.items()}

    # Perfil del carril: tamaño y silueta de SU automovil. Es lo que decide
    # si ademas de liviano/pesado se pueden separar MOTO y AUTOBUS. Va por
    # carril y no por proyecto, igual que el umbral, porque cada carril
    # cuenta sobre una linea fija —a distancia fija de la camara— y esa es
    # justo la condicion que hace comparables el alto y la silueta.
    #
    # Se calcula solo con las horas medibles: de noche la etiqueta de COCO
    # no significa nada y el automovil sale deformado por el barrido.
    perfiles = {
        lane["id"]: perfil_de_calzada([
            {"vehicle_type": f["vehicle_type"], "bbox_height": f["bbox_height"],
             "bbox_width": f["bbox_width"]}
            for f in rows
            if f["lane_id"] == lane["id"] and _hora(f) in horas_medibles
        ])
        for lane in lanes
    }

    from src.engine.velocidad import control_distancia, kmh_de, resumen as resumen_velocidad

    result_lanes = []
    for lane in lanes:
        umbral = umbrales[lane["id"]]  # solo para informar; se clasifica por hora
        interval_map = {b: {"in": 0, "out": 0, "total": 0, "by_vehicle_type": {}} for b in buckets}
        velocidades = {b: [] for b in buckets}
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
            # Cada cruce se clasifica con el umbral de SU hora.
            u_hora = niveles.get((lane["id"], row["timestamp"][11:13]),
                                 (NO_RESOLUBLE, None))[1]
            clase = clasificar(row["vehicle_type"], row["bbox_height"], u_hora,
                               ancho=row["bbox_width"],
                               perfil=perfiles.get(lane["id"]))
            vt = bucket["by_vehicle_type"].setdefault(clase, {"in": 0, "out": 0})
            vt[row["direction"]] += 1
            # La velocidad solo en las horas medibles: de noche el vehículo
            # es una estela de luz y su rastro no dice a qué velocidad iba.
            if lane.get("tramo") and _hora(row) in horas_medibles:
                kmh = kmh_de(lane["tramo"]["distancia_m"], row["tiempo_tramo_s"])
                if kmh is not None:
                    velocidades[buckets[idx]].append(kmh)

        result_lanes.append({
            "lane_id": lane["id"],
            "lane_name": lane["name"],
            # Para que quien lea el reporte sepa si el desglose por tipo de
            # este carril es una medición o un "no se puede".
            "umbral_pesado_px": round(umbral, 1) if umbral else None,
            "nivel_clasificacion": mejor[lane["id"]][0],
            "tramo": lane.get("tramo"),
            # El automóvil como regla: con la distancia capturada, ¿cuánto
            # medirían de alto los automóviles? Delata una distancia mal
            # medida, que de otro modo escala todas las velocidades sin avisar.
            "control_tramo": control_distancia(
                [f["bbox_height"] for f in rows
                 if f["lane_id"] == lane["id"] and f["vehicle_type"] == "car"
                 and _hora(f) in horas_medibles],
                lane["points"], lane["tramo"]["linea"], lane["tramo"]["distancia_m"],
            ) if lane.get("tramo") else None,
            "velocidad": _resumen_redondeado(
                resumen_velocidad([v for b in buckets for v in velocidades[b]])
            ) if lane.get("tramo") else None,
            "intervals": [
                {
                    "start": b.strftime("%Y-%m-%d %H:%M:%S"),
                    "end": (b + delta).strftime("%Y-%m-%d %H:%M:%S"),
                    **interval_map[b],
                    **({"velocidad": _resumen_redondeado(resumen_velocidad(velocidades[b]))}
                       if lane.get("tramo") else {}),
                }
                for b in buckets
            ]
        })

    return {"lanes": result_lanes, "interval_minutes": interval_minutes}


def _resumen_redondeado(r: Dict) -> Dict:
    return {k: (round(v, 1) if isinstance(v, float) else v) for k, v in r.items()}


# --- Registro del proyecto ------------------------------------------------

def log_event(project_id: Optional[int], kind: str, summary: str,
              detail: Optional[str] = None) -> None:
    """
    Anota algo que le pasó a una intersección.

    Nunca lanza: el registro es para poder explicar el aforo después, no
    una parte del aforo. Si escribirlo falla, lo que estaba haciendo el
    usuario tiene que seguir adelante igual — perder una línea de
    historial es mucho menos grave que perder la subida de un video.
    """
    if project_id is None:
        return
    try:
        conn = get_connection()
        conn.execute(
            """INSERT INTO project_events (project_id, kind, summary, detail)
               VALUES (?, ?, ?, ?)""",
            (project_id, kind, summary, detail),
        )
        conn.commit()
    except Exception:
        logger.warning("No se pudo registrar el evento del proyecto", exc_info=True)


def list_events(project_id: int, limit: int = 200) -> List[Dict]:
    conn = get_connection()
    filas = conn.execute(
        """SELECT id, kind, summary, detail, created_at
           FROM project_events
           WHERE project_id = ?
           ORDER BY id DESC
           LIMIT ?""",
        (project_id, limit),
    ).fetchall()
    return [dict(f) for f in filas]


def vehicle_height_stats(project_id: int) -> Dict:
    """
    Distribución del alto de los vehículos, en píxeles, medido en el
    momento del cruce.

    Es la cifra que decide si el detector puede con el material. Solo
    existe para lo contado después de que se empezó a guardar, así que se
    devuelve también cuántos cruces la tienen: un percentil sacado de
    veinte muestras no significa lo mismo que uno sacado de cuarenta mil.
    """
    conn = get_connection()
    fila = conn.execute(
        """SELECT COUNT(*) AS con_medida
           FROM crossings c
           JOIN lane_configs l ON l.id = c.lane_id
           WHERE l.project_id = ? AND c.bbox_height IS NOT NULL""",
        (project_id,),
    ).fetchone()
    con_medida = fila["con_medida"] if fila else 0
    if not con_medida:
        return {"con_medida": 0, "mediana": None, "p10": None, "p90": None}

    alturas = [
        r["bbox_height"]
        for r in conn.execute(
            """SELECT c.bbox_height
               FROM crossings c
               JOIN lane_configs l ON l.id = c.lane_id
               WHERE l.project_id = ? AND c.bbox_height IS NOT NULL
               ORDER BY c.bbox_height""",
            (project_id,),
        ).fetchall()
    ]

    def pct(p: float) -> int:
        return alturas[min(len(alturas) - 1, int(len(alturas) * p))]

    return {
        "con_medida": con_medida,
        "mediana": pct(0.5),
        "p10": pct(0.10),
        "p90": pct(0.90),
    }
