"""
RAG sobre los documentos que sube el usuario.

Para qué sirve aquí: un aforo produce cifras, pero el informe que las
acompaña se apoya en normativa y metodología —la PT-914 del IMT, manuales
de ingeniería de tránsito, especificaciones del cliente—. Este módulo deja
preguntar sobre ESOS documentos y responde citando de dónde salió cada
cosa, en vez de que el modelo invente de memoria.

Decisiones de diseño y por qué:

**sqlite-vec y no un servidor de vectores.** El equipo de destino es un
Jetson Orin Nano con 8 GB compartidos entre CPU y GPU. Milvus o Qdrant
piden un proceso aparte permanente; sqlite-vec es una extensión del SQLite
que el proyecto ya usa, así que son cero servicios nuevos y un archivo
más. Medido en el Jetson con la dimensión real del modelo (2048): 3 000
vectores se insertan en 4.1 s, se buscan en 24 ms y ocupan 25 MB.

**Búsqueda híbrida (vectorial + léxica) fusionada con RRF.** La búsqueda
vectorial encuentra lo que significa lo mismo aunque esté dicho con otras
palabras; la léxica encuentra lo que se llama igual — y en este dominio
abundan los términos exactos que hay que acertar ("PT-914", "FHP",
"nivel de servicio D"). Cada una falla donde la otra acierta. No hay paso
de reranking porque el endpoint dedicado no está disponible en esta cuenta.

**Se responde solo con lo recuperado.** Si las fuentes no contienen la
respuesta, el modelo tiene instrucción de decirlo. Un informe de aforo
sustenta decisiones de obra: una cita inventada es peor que un "no lo sé".
"""

import json
import logging
import re
import struct
import threading
from typing import Dict, List, Optional, Tuple

from src.ai import nvidia_client
from src.storage import traffic_db

# Dimensión del modelo de embeddings (nvidia/nemotron-3-embed-1b).
# Se comprueba contra la primera respuesta real: si el modelo cambia y
# devuelve otra dimensión, la tabla vectorial ya no sirve y hay que
# reindexar, así que es mejor fallar con un mensaje claro.
DIMENSION = 2048

# Trozos de ~1200 caracteres con 200 de solape. El solape existe para que
# una definición partida justo en la frontera siga estando completa en uno
# de los dos trozos.
TAMANO_TROZO = 1200
SOLAPE = 200

# La extensión se carga una vez por hilo, igual que la conexión de
# traffic_db. No se puede marcar la propia conexión con un atributo:
# sqlite3.Connection es un tipo en C y no admite atributos arbitrarios.
_local = threading.local()


def _conn():
    """Conexión del hilo con la extensión vectorial ya cargada."""
    conn = traffic_db.get_connection()
    if not getattr(_local, "vec_ok", False):
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        _local.vec_ok = True
    return conn


def init_schema():
    """
    Crea las tablas del RAG. Idempotente, como el resto del proyecto.

    Son tres piezas que trabajan juntas: los trozos de texto, su índice
    léxico (FTS5) y su índice vectorial (vec0). Los tres comparten el
    rowid del trozo, que es lo que permite fusionar los resultados.
    """
    conn = _conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rag_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER REFERENCES projects(id),
            name TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'documento',
            size_bytes INTEGER NOT NULL DEFAULT 0,
            chunks INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rag_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id INTEGER NOT NULL REFERENCES rag_documents(id),
            ord INTEGER NOT NULL,
            pagina INTEGER,
            texto TEXT NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rag_chunks_doc ON rag_chunks(doc_id)"
    )
    # Índice léxico. content='' lo hace "externo": FTS5 guarda solo el
    # índice y no una segunda copia del texto.
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS rag_fts
        USING fts5(texto, content='rag_chunks', content_rowid='id', tokenize='unicode61')
    """)
    conn.execute(f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS rag_vectors
        USING vec0(embedding float[{DIMENSION}])
    """)
    # Conversaciones. Se guardan en el servidor y no en el navegador porque
    # una consulta sobre normativa es trabajo del proyecto: el que la hizo
    # tiene que poder volver a ella, y otro del equipo verla desde su
    # propia máquina.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rag_conversaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER REFERENCES projects(id),
            titulo TEXT NOT NULL DEFAULT 'Consulta',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rag_mensajes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversacion_id INTEGER NOT NULL REFERENCES rag_conversaciones(id),
            rol TEXT NOT NULL,
            texto TEXT NOT NULL,
            fuentes_json TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rag_msg_conv ON rag_mensajes(conversacion_id)"
    )
    conn.commit()


# --- Troceado ----------------------------------------------------------

def _limpiar(texto: str) -> str:
    # Los PDF traen saltos de línea a mitad de frase y espacios dobles;
    # dejarlos ensucia tanto el embedding como la cita que se le muestra
    # al usuario.
    texto = texto.replace("\r", "")
    texto = re.sub(r"-\n(\w)", r"\1", texto)      # palabras cortadas por guión
    texto = re.sub(r"(?<![\n.])\n(?![\n\s])", " ", texto)
    texto = re.sub(r"[ \t]+", " ", texto)
    return re.sub(r"\n{3,}", "\n\n", texto).strip()


def trocear(texto: str, tamano: int = TAMANO_TROZO, solape: int = SOLAPE) -> List[str]:
    """
    Corta el texto en trozos, prefiriendo cortar en final de párrafo o de
    frase. Un corte a mitad de oración produce un trozo que no se entiende
    solo, y el usuario lo va a leer como cita.
    """
    texto = _limpiar(texto)
    if len(texto) <= tamano:
        return [texto] if texto else []

    trozos, i = [], 0
    while i < len(texto):
        fin = min(i + tamano, len(texto))
        if fin < len(texto):
            ventana = texto[i:fin]
            corte = max(ventana.rfind("\n\n"), ventana.rfind(". "), ventana.rfind("\n"))
            # Solo se respeta el corte natural si no deja un trozo ridículo.
            if corte > tamano * 0.5:
                fin = i + corte + 1
        trozo = texto[i:fin].strip()
        if trozo:
            trozos.append(trozo)
        if fin >= len(texto):
            break
        i = max(i + 1, fin - solape)
    return trozos


def extraer_texto(ruta: str, nombre: str) -> List[Tuple[Optional[int], str]]:
    """Devuelve [(página, texto)]. La página es None en formatos sin páginas."""
    bajo = nombre.lower()
    if bajo.endswith(".pdf"):
        from pypdf import PdfReader
        lector = PdfReader(ruta)
        salida = []
        for n, pag in enumerate(lector.pages, 1):
            t = (pag.extract_text() or "").strip()
            if t:
                salida.append((n, t))
        if not salida:
            raise ValueError(
                "El PDF no tiene texto extraíble. Si es un escaneo, hace falta "
                "pasarlo antes por un OCR."
            )
        return salida
    for cod in ("utf-8", "latin-1"):
        try:
            with open(ruta, encoding=cod) as fh:
                return [(None, fh.read())]
        except UnicodeDecodeError:
            continue
    raise ValueError("No se pudo leer el archivo como texto.")


# --- Indexado ----------------------------------------------------------

def indexar(ruta: str, nombre: str, project_id: Optional[int] = None,
            size_bytes: int = 0, lote: int = 16) -> Dict:
    """
    Trocea, embebe e indexa un documento.

    Los embeddings van en lotes porque la diferencia es enorme: medido
    contra la API desde el Jetson, 0.71 s por fragmento de uno en uno
    contra 0.04 s en lotes de 16. Indexar 3 000 fragmentos pasa de media
    hora a dos minutos.
    """
    init_schema()
    paginas = extraer_texto(ruta, nombre)

    trozos: List[Tuple[Optional[int], str]] = []
    for pagina, texto in paginas:
        for t in trocear(texto):
            trozos.append((pagina, t))
    if not trozos:
        raise ValueError("El documento no tiene texto que indexar.")

    conn = _conn()
    cur = conn.execute(
        """INSERT INTO rag_documents (project_id, name, kind, size_bytes, chunks)
           VALUES (?, ?, ?, ?, ?)""",
        (project_id, nombre, "pdf" if nombre.lower().endswith(".pdf") else "texto",
         size_bytes, len(trozos))
    )
    doc_id = cur.lastrowid

    indexados = 0
    for inicio in range(0, len(trozos), lote):
        grupo = trozos[inicio:inicio + lote]
        vectores = nvidia_client.embed([t for _, t in grupo], input_type="passage")
        if vectores and len(vectores[0]) != DIMENSION:
            conn.rollback()
            raise ValueError(
                f"El modelo devolvió {len(vectores[0])} dimensiones y el índice "
                f"espera {DIMENSION}. Cambió el modelo de embeddings: hay que "
                "reindexar todo con el nuevo."
            )
        for (pagina, texto), vector in zip(grupo, vectores):
            c = conn.execute(
                "INSERT INTO rag_chunks (doc_id, ord, pagina, texto) VALUES (?,?,?,?)",
                (doc_id, indexados, pagina, texto)
            )
            chunk_id = c.lastrowid
            conn.execute("INSERT INTO rag_fts(rowid, texto) VALUES (?,?)",
                         (chunk_id, texto))
            conn.execute("INSERT INTO rag_vectors(rowid, embedding) VALUES (?,?)",
                         (chunk_id, struct.pack(f"{DIMENSION}f", *vector)))
            indexados += 1
        conn.commit()

    logging.info(f"RAG: '{nombre}' indexado en {indexados} fragmentos")
    return {"doc_id": doc_id, "nombre": nombre, "fragmentos": indexados}


def listar_documentos(project_id: Optional[int] = None) -> List[Dict]:
    init_schema()
    conn = _conn()
    if project_id is None:
        filas = conn.execute(
            "SELECT * FROM rag_documents ORDER BY id DESC").fetchall()
    else:
        filas = conn.execute(
            """SELECT * FROM rag_documents WHERE project_id = ? OR project_id IS NULL
               ORDER BY id DESC""", (project_id,)).fetchall()
    return [dict(f) for f in filas]


def borrar_documento(doc_id: int) -> int:
    """Borra el documento y sus tres representaciones a la vez.

    Si se olvidara alguna, el buscador seguiría devolviendo fragmentos de
    un documento que el usuario cree eliminado.
    """
    conn = _conn()
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM rag_chunks WHERE doc_id = ?", (doc_id,))]
    for chunk_id in ids:
        conn.execute("DELETE FROM rag_fts WHERE rowid = ?", (chunk_id,))
        conn.execute("DELETE FROM rag_vectors WHERE rowid = ?", (chunk_id,))
    conn.execute("DELETE FROM rag_chunks WHERE doc_id = ?", (doc_id,))
    conn.execute("DELETE FROM rag_documents WHERE id = ?", (doc_id,))
    conn.commit()
    return len(ids)


# --- Búsqueda ----------------------------------------------------------

def _rrf(listas: List[List[int]], k: int = 60) -> Dict[int, float]:
    """
    Reciprocal Rank Fusion: combina rankings usando la POSICIÓN, no la
    puntuación. Es lo que permite mezclar una distancia vectorial con un
    score BM25, que no comparten escala ni sentido (en uno menor es mejor,
    en el otro mayor).
    """
    puntos: Dict[int, float] = {}
    for lista in listas:
        for posicion, cid in enumerate(lista):
            puntos[cid] = puntos.get(cid, 0.0) + 1.0 / (k + posicion + 1)
    return puntos


def buscar(pregunta: str, n: int = 6, project_id: Optional[int] = None) -> List[Dict]:
    """Búsqueda híbrida: vectorial + léxica, fusionadas con RRF."""
    init_schema()
    conn = _conn()

    if not conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]:
        return []

    # Vectorial. input_type='query' importa: el modelo embebe preguntas y
    # pasajes en espacios distintos y mezclarlos degrada el resultado.
    vector = nvidia_client.embed([pregunta], input_type="query")[0]
    densos = [r["rowid"] for r in conn.execute(
        "SELECT rowid FROM rag_vectors WHERE embedding MATCH ? AND k = ?",
        (struct.pack(f"{DIMENSION}f", *vector), n * 3))]

    # Léxica. Las comillas evitan que un signo de interrogación o un guión
    # de la pregunta se interprete como sintaxis de FTS5 y reviente.
    consulta = " OR ".join(f'"{p}"' for p in re.findall(r"\w{3,}", pregunta.lower())[:12])
    lexicos = []
    if consulta:
        try:
            lexicos = [r["rowid"] for r in conn.execute(
                "SELECT rowid FROM rag_fts WHERE rag_fts MATCH ? ORDER BY rank LIMIT ?",
                (consulta, n * 3))]
        except Exception as e:
            logging.warning(f"RAG: la búsqueda léxica falló ({e}); se usa solo la vectorial")

    puntos = _rrf([densos, lexicos])
    if not puntos:
        return []

    mejores = sorted(puntos.items(), key=lambda kv: -kv[1])
    salida = []
    for chunk_id, punto in mejores:
        fila = conn.execute(
            """SELECT c.id, c.texto, c.pagina, d.name, d.id AS doc_id, d.project_id
               FROM rag_chunks c JOIN rag_documents d ON d.id = c.doc_id
               WHERE c.id = ?""", (chunk_id,)).fetchone()
        if fila is None:
            continue
        # Un documento atado a un proyecto solo aparece en ese proyecto;
        # los que no tienen proyecto son de consulta general.
        if (project_id is not None and fila["project_id"] is not None
                and fila["project_id"] != project_id):
            continue
        salida.append({
            "chunk_id": fila["id"], "doc_id": fila["doc_id"],
            "documento": fila["name"], "pagina": fila["pagina"],
            "texto": fila["texto"], "puntuacion": round(punto, 4),
            "en_vectorial": chunk_id in densos, "en_lexica": chunk_id in lexicos,
        })
        if len(salida) >= n:
            break
    return salida


# --- Conversaciones ----------------------------------------------------

def crear_conversacion(project_id: Optional[int], titulo: str) -> int:
    init_schema()
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO rag_conversaciones (project_id, titulo) VALUES (?,?)",
        (project_id, titulo[:80] or "Consulta"))
    conn.commit()
    return cur.lastrowid


def listar_conversaciones(project_id: Optional[int] = None) -> List[Dict]:
    init_schema()
    conn = _conn()
    # Una conversación pertenece a una intersección o a ninguna, y no se
    # mezclan: preguntar dentro de un proyecto no debe mostrar el hilo de
    # otro, aunque el documento de fondo sea el mismo.
    if project_id is None:
        filas = conn.execute(
            """SELECT c.*, (SELECT COUNT(*) FROM rag_mensajes m
                            WHERE m.conversacion_id = c.id) AS mensajes
               FROM rag_conversaciones c WHERE c.project_id IS NULL
               ORDER BY c.updated_at DESC""").fetchall()
    else:
        filas = conn.execute(
            """SELECT c.*, (SELECT COUNT(*) FROM rag_mensajes m
                            WHERE m.conversacion_id = c.id) AS mensajes
               FROM rag_conversaciones c WHERE c.project_id = ?
               ORDER BY c.updated_at DESC""", (project_id,)).fetchall()
    return [dict(f) for f in filas]


def obtener_conversacion(conversacion_id: int) -> Optional[Dict]:
    init_schema()
    fila = _conn().execute(
        "SELECT * FROM rag_conversaciones WHERE id = ?", (conversacion_id,)).fetchone()
    return dict(fila) if fila else None


def titular(conversacion_id: int, titulo: str):
    """El título sale de la primera pregunta: una lista de hilos llamados
    todos 'Consulta' no sirve para volver a ninguno."""
    conn = _conn()
    conn.execute("UPDATE rag_conversaciones SET titulo = ? WHERE id = ?",
                 (titulo[:80], conversacion_id))
    conn.commit()


def mensajes(conversacion_id: int) -> List[Dict]:
    init_schema()
    conn = _conn()
    salida = []
    for f in conn.execute(
            "SELECT * FROM rag_mensajes WHERE conversacion_id = ? ORDER BY id",
            (conversacion_id,)):
        m = dict(f)
        m["fuentes"] = json.loads(m.pop("fuentes_json") or "[]")
        salida.append(m)
    return salida


def borrar_conversacion(conversacion_id: int):
    conn = _conn()
    conn.execute("DELETE FROM rag_mensajes WHERE conversacion_id = ?", (conversacion_id,))
    conn.execute("DELETE FROM rag_conversaciones WHERE id = ?", (conversacion_id,))
    conn.commit()


def _guardar(conversacion_id: int, rol: str, texto: str, fuentes=None):
    conn = _conn()
    conn.execute(
        """INSERT INTO rag_mensajes (conversacion_id, rol, texto, fuentes_json)
           VALUES (?,?,?,?)""",
        (conversacion_id, rol, texto, json.dumps(fuentes or [], ensure_ascii=False)))
    conn.execute("UPDATE rag_conversaciones SET updated_at = datetime('now') WHERE id = ?",
                 (conversacion_id,))
    conn.commit()


# --- Respuesta ---------------------------------------------------------

INSTRUCCIONES = """Eres un asistente técnico de una empresa de estudios de tránsito en México.

Respondes ÚNICAMENTE con lo que digan las fuentes numeradas que se te dan.

Reglas:
- Cita la fuente entre corchetes después de cada afirmación: [1], [2].
- Si las fuentes no contienen la respuesta, dilo con claridad y no la completes
  con conocimiento propio. Un aforo sustenta decisiones de obra: un dato
  inventado es peor que un "no está en los documentos".
- Si las fuentes se contradicen, señálalo en vez de elegir una.
- Responde en español, directo y sin rodeos."""


def responder(pregunta: str, n: int = 6, project_id: Optional[int] = None,
              conversacion_id: Optional[int] = None) -> Dict:
    """
    Busca, arma el contexto y responde citando las fuentes.

    Con conversacion_id la respuesta tiene en cuenta el hilo previo, y eso
    cambia dos cosas:

    1. La BÚSQUEDA. "¿y el de NMS?" no recupera nada por sí sola: le falta
       el sujeto. Se le antepone la última pregunta del usuario para que el
       embedding tenga de qué agarrarse.
    2. La REDACCIÓN. El modelo ve los turnos anteriores, así que responde
       sobre lo ya dicho en vez de repetirlo.
    """
    historial = mensajes(conversacion_id) if conversacion_id else []

    # Solo se completa la consulta cuando la pregunta es corta: una
    # pregunta larga ya se sostiene sola, y arrastrarle la anterior la
    # desviaría hacia el tema viejo.
    consulta = pregunta
    if historial and len(pregunta.split()) <= 8:
        previas = [m["texto"] for m in historial if m["rol"] == "user"]
        if previas:
            consulta = f"{previas[-1]} {pregunta}"

    fuentes = buscar(consulta, n=n, project_id=project_id)
    if not fuentes:
        aviso = ("No hay documentos indexados todavía, o ninguno guarda relación "
                 "con la pregunta. Sube documentos y vuelve a intentarlo.")
        if conversacion_id:
            _guardar(conversacion_id, "user", pregunta)
            _guardar(conversacion_id, "assistant", aviso)
        return {"respuesta": aviso, "fuentes": [], "conversacion_id": conversacion_id}

    contexto = "\n\n".join(
        f"[{i}] {f['documento']}"
        + (f" (página {f['pagina']})" if f["pagina"] else "")
        + f"\n{f['texto']}"
        for i, f in enumerate(fuentes, 1)
    )

    # El contexto del proyecto entra en el prompt porque cambia la
    # respuesta: no es lo mismo preguntar por niveles de servicio en
    # abstracto que sobre la intersección que se está midiendo.
    encabezado = ""
    if project_id is not None:
        proyecto = traffic_db.get_project(project_id)
        if proyecto:
            encabezado = f"Intersección en estudio: {proyecto['name']}"
            if proyecto.get("address"):
                encabezado += f" ({proyecto['address']})"
            encabezado += "\n\n"

    conversacion = [{"role": "system", "content": INSTRUCCIONES}]
    # Solo los últimos turnos: el contexto de las fuentes ya es grande y
    # arrastrar un hilo largo desplaza justo lo que hay que citar.
    for m in historial[-6:]:
        conversacion.append({"role": m["rol"], "content": m["texto"]})
    conversacion.append({
        "role": "user",
        "content": f"{encabezado}FUENTES:\n\n{contexto}\n\nPREGUNTA: {pregunta}",
    })

    respuesta = nvidia_client.chat(
        conversacion,
        max_tokens=700, temperature=0.1,
        timeout_s=nvidia_client._load_config().get("rag_timeout_s", 120),
    )

    salida_fuentes = [
        {"n": i, "documento": f["documento"], "pagina": f["pagina"],
         "extracto": f["texto"][:300], "doc_id": f["doc_id"],
         "en_vectorial": f["en_vectorial"], "en_lexica": f["en_lexica"]}
        for i, f in enumerate(fuentes, 1)
    ]
    if conversacion_id:
        _guardar(conversacion_id, "user", pregunta)
        _guardar(conversacion_id, "assistant", respuesta, salida_fuentes)

    return {
        "respuesta": respuesta,
        "conversacion_id": conversacion_id,
        "fuentes": salida_fuentes,
    }
