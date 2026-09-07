"""
Comprueba que cada dato esté donde debe y que nada haya quedado huérfano.

Existe porque los huérfanos de este proyecto nunca dieron un error: el
aforo desaparecía de la lista pero sus cruces seguían sumando en las
vistas que agregan por carril, y el buscador del RAG seguía citando
documentos de proyectos borrados. Se ven solo si se buscan a propósito.

Revisa cuatro cosas:

1. **Referencias rotas** — filas que apuntan a un padre que ya no existe.
2. **Los tres índices del RAG en sincronía** — texto, léxico y vectorial
   comparten el rowid del fragmento; si uno se desfasa, el buscador
   devuelve fragmentos que ya no existen o deja de encontrar otros.
3. **Archivos y base coherentes** — ni filas apuntando a archivos que se
   borraron, ni archivos ocupando disco sin fila que los reclame.
4. **Reglas del propio dominio** — una línea atada a la calzada de otro
   proyecto, un cruce cuya zona no es del proyecto de su carril.

    python tools/auditar_datos.py
    python tools/auditar_datos.py --arreglar     # limpia lo que sea seguro

En el Jetson va dentro del contenedor:

    docker compose -f docker-compose.jetson.yml exec -T aforo-vehicular \\
      python3 tools/auditar_datos.py
"""

import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB = os.path.join("data", "traffic.db")
CARPETAS = ["data/uploads", "data/rag_docs"]


def conectar():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except Exception as e:
        print(f"  aviso: sin extensión vectorial ({e}); no se revisa rag_vectors")
    return conn


# (etiqueta, consulta que cuenta las filas malas, sentencia de limpieza)
REFERENCIAS = [
    ("cruces sin carril",
     "SELECT COUNT(*) FROM crossings WHERE lane_id NOT IN (SELECT id FROM lane_configs)",
     "DELETE FROM crossings WHERE lane_id NOT IN (SELECT id FROM lane_configs)"),
    ("cruces cuyo video ya no existe",
     "SELECT COUNT(*) FROM crossings WHERE job_id IS NOT NULL AND job_id NOT IN (SELECT id FROM video_jobs)",
     "DELETE FROM crossings WHERE job_id IS NOT NULL AND job_id NOT IN (SELECT id FROM video_jobs)"),
    ("cruces con zona inexistente",
     "SELECT COUNT(*) FROM crossings WHERE zone_id IS NOT NULL AND zone_id NOT IN (SELECT id FROM zones)",
     "UPDATE crossings SET zone_id = NULL WHERE zone_id IS NOT NULL AND zone_id NOT IN (SELECT id FROM zones)"),
    ("carriles sin proyecto",
     "SELECT COUNT(*) FROM lane_configs WHERE project_id IS NULL OR project_id NOT IN (SELECT id FROM projects)",
     None),   # pueden tener cruces: se avisa, no se borra
    ("carriles atados a una zona inexistente",
     "SELECT COUNT(*) FROM lane_configs WHERE zone_id IS NOT NULL AND zone_id NOT IN (SELECT id FROM zones)",
     "UPDATE lane_configs SET zone_id = NULL WHERE zone_id IS NOT NULL AND zone_id NOT IN (SELECT id FROM zones)"),
    ("zonas sin proyecto",
     "SELECT COUNT(*) FROM zones WHERE project_id NOT IN (SELECT id FROM projects)",
     "DELETE FROM zones WHERE project_id NOT IN (SELECT id FROM projects)"),
    ("videos sin proyecto",
     "SELECT COUNT(*) FROM video_jobs WHERE project_id IS NULL OR project_id NOT IN (SELECT id FROM projects)",
     None),   # el archivo puede seguir ahí: lo decide una persona
    ("eventos sin proyecto",
     "SELECT COUNT(*) FROM project_events WHERE project_id NOT IN (SELECT id FROM projects)",
     "DELETE FROM project_events WHERE project_id NOT IN (SELECT id FROM projects)"),
    ("documentos del RAG con proyecto inexistente",
     "SELECT COUNT(*) FROM rag_documents WHERE project_id IS NOT NULL AND project_id NOT IN (SELECT id FROM projects)",
     None),   # borrarlos toca tres índices: lo hace rag.borrar_documento
    ("fragmentos sin documento",
     "SELECT COUNT(*) FROM rag_chunks WHERE doc_id NOT IN (SELECT id FROM rag_documents)",
     None),
    ("conversaciones con proyecto inexistente",
     "SELECT COUNT(*) FROM rag_conversaciones WHERE project_id IS NOT NULL AND project_id NOT IN (SELECT id FROM projects)",
     None),
    ("mensajes sin conversación",
     "SELECT COUNT(*) FROM rag_mensajes WHERE conversacion_id NOT IN (SELECT id FROM rag_conversaciones)",
     "DELETE FROM rag_mensajes WHERE conversacion_id NOT IN (SELECT id FROM rag_conversaciones)"),
]

DOMINIO = [
    ("líneas atadas a la calzada de OTRO proyecto",
     """SELECT COUNT(*) FROM lane_configs l JOIN zones z ON z.id = l.zone_id
        WHERE l.zone_id IS NOT NULL AND z.project_id != l.project_id"""),
    ("cruces cuya zona no es del proyecto de su carril",
     """SELECT COUNT(*) FROM crossings c
        JOIN lane_configs l ON l.id = c.lane_id
        JOIN zones z ON z.id = c.zone_id
        WHERE c.zone_id IS NOT NULL AND z.project_id != l.project_id"""),
    ("cruces cuyo video pertenece a otro proyecto",
     """SELECT COUNT(*) FROM crossings c
        JOIN lane_configs l ON l.id = c.lane_id
        JOIN video_jobs v ON v.id = c.job_id
        WHERE c.job_id IS NOT NULL AND v.project_id != l.project_id"""),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arreglar", action="store_true",
                    help="limpia lo que se puede limpiar sin perder información")
    args = ap.parse_args()

    if not os.path.exists(DB):
        sys.exit(f"No existe {DB}")

    conn = conectar()
    problemas = 0

    print("\n=== ESTADO GENERAL ===")
    print("  integridad:", conn.execute("PRAGMA integrity_check").fetchone()[0])
    print("  claves foráneas:",
          "aplicadas" if conn.execute("PRAGMA foreign_keys").fetchone()[0] else "NO APLICADAS")
    tam = os.path.getsize(DB) / 1e6
    print(f"  tamaño de la base: {tam:.1f} MB")

    print("\n=== INVENTARIO POR INTERSECCIÓN ===")
    filas = conn.execute("""
        SELECT p.id, p.name,
          (SELECT COUNT(*) FROM video_jobs v WHERE v.project_id = p.id) AS videos,
          (SELECT COUNT(*) FROM lane_configs l WHERE l.project_id = p.id AND l.active = 1) AS lineas,
          (SELECT COUNT(*) FROM zones z WHERE z.project_id = p.id AND z.active = 1) AS zonas,
          (SELECT COUNT(*) FROM crossings c JOIN lane_configs l2 ON l2.id = c.lane_id
             WHERE l2.project_id = p.id) AS cruces,
          (SELECT COUNT(*) FROM rag_documents d WHERE d.project_id = p.id) AS docs,
          (SELECT COUNT(*) FROM rag_conversaciones k WHERE k.project_id = p.id) AS chats
        FROM projects p ORDER BY p.id""").fetchall()
    if filas:
        print(f"  {'id':>3} {'intersección':<32} {'vid':>4} {'lín':>4} {'zon':>4} "
              f"{'cruces':>7} {'docs':>5} {'chats':>6}")
        for f in filas:
            print(f"  {f['id']:>3} {f['name'][:32]:<32} {f['videos']:>4} {f['lineas']:>4} "
                  f"{f['zonas']:>4} {f['cruces']:>7} {f['docs']:>5} {f['chats']:>6}")
    else:
        print("  (sin intersecciones)")

    generales = conn.execute(
        "SELECT COUNT(*) FROM rag_documents WHERE project_id IS NULL").fetchone()[0]
    print(f"\n  documentos de normativa general (sin intersección): {generales}")

    print("\n=== REFERENCIAS ROTAS ===")
    for etq, consulta, arreglo in REFERENCIAS:
        try:
            n = conn.execute(consulta).fetchone()[0]
        except sqlite3.OperationalError:
            continue          # la tabla todavía no existe en esta base
        if n:
            problemas += 1
            extra = ""
            if args.arreglar and arreglo:
                conn.execute(arreglo)
                conn.commit()
                extra = "  -> limpiado"
            elif not arreglo:
                extra = "  (hay que revisarlo a mano)"
            print(f"  {etq:<48} {n}{extra}")
    if not problemas:
        print("  ninguna")

    print("\n=== COHERENCIA DEL RAG ===")
    try:
        c = conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
        f = conn.execute("SELECT COUNT(*) FROM rag_fts").fetchone()[0]
        v = conn.execute("SELECT COUNT(*) FROM rag_vectors").fetchone()[0]
        print(f"  fragmentos {c} · léxico {f} · vectorial {v}")
        if not (c == f == v):
            problemas += 1
            print("  DESINCRONIZADOS: el buscador va a citar fragmentos que no existen,")
            print("  o a no encontrar otros. Reindexa los documentos afectados.")
    except sqlite3.OperationalError as e:
        print(f"  no se pudo comprobar: {e}")

    print("\n=== ARCHIVOS Y BASE ===")
    referidos = set()
    for consulta in ("SELECT stored_path FROM video_jobs",
                     "SELECT output_video_path FROM video_jobs",
                     "SELECT stored_path FROM rag_documents"):
        try:
            for r in conn.execute(consulta):
                if r[0]:
                    referidos.add(os.path.abspath(r[0]))
        except sqlite3.OperationalError:
            pass

    faltantes = [r for r in referidos if not os.path.exists(r)]
    if faltantes:
        problemas += 1
        print(f"  {len(faltantes)} filas apuntan a archivos que ya no están:")
        for r in faltantes[:5]:
            print(f"    {r}")
    else:
        print("  todas las filas apuntan a archivos existentes")

    # Un documento indexado ANTES de que rag_documents guardara la ruta
    # tiene stored_path nulo: su archivo existe y está en uso, pero no hay
    # fila que lo reclame. Borrarlo destruiría el original de un documento
    # vivo, así que mientras quede alguno sin ruta no se ofrece limpiar.
    sin_ruta = 0
    try:
        sin_ruta = conn.execute(
            "SELECT COUNT(*) FROM rag_documents WHERE stored_path IS NULL"
        ).fetchone()[0]
    except sqlite3.OperationalError:
        pass

    sueltos = []
    for carpeta in CARPETAS:
        if not os.path.isdir(carpeta):
            continue
        for nombre in os.listdir(carpeta):
            ruta = os.path.abspath(os.path.join(carpeta, nombre))
            if os.path.isfile(ruta) and ruta not in referidos:
                sueltos.append(ruta)
    if sueltos:
        peso = sum(os.path.getsize(r) for r in sueltos) / 1e6
        print(f"  {len(sueltos)} archivos sin fila que los reclame ({peso:.1f} MB):")
        for r in sueltos[:5]:
            print(f"    {os.path.relpath(r)}")
        if sin_ruta:
            problemas += 1
            print(f"  NO se van a borrar: hay {sin_ruta} documento(s) indexados sin ruta")
            print("  guardada, y alguno de esos archivos puede ser el suyo. Corre")
            print("  tools/reparar_rutas_rag.py para emparejarlos primero.")
        elif args.arreglar:
            for r in sueltos:
                try:
                    os.remove(r)
                except OSError as e:
                    print(f"    no se pudo borrar {r}: {e}")
            print(f"  -> {len(sueltos)} archivos eliminados")
        else:
            problemas += 1
            print("  (--arreglar los elimina)")
    else:
        print("  no hay archivos sueltos")

    print("\n=== REGLAS DEL DOMINIO ===")
    malas = 0
    for etq, consulta in DOMINIO:
        try:
            n = conn.execute(consulta).fetchone()[0]
        except sqlite3.OperationalError:
            continue
        if n:
            malas += 1
            problemas += 1
            print(f"  {etq:<48} {n}")
    if not malas:
        print("  todo coherente")

    print()
    if problemas:
        print(f"{problemas} cosas que revisar."
              + ("" if args.arreglar else "  Vuelve a correrlo con --arreglar."))
    else:
        print("Sin problemas: cada dato está donde debe.")
    return 1 if problemas and not args.arreglar else 0


if __name__ == "__main__":
    sys.exit(main())
