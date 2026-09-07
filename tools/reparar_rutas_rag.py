"""
Empareja los documentos del RAG indexados antes de que se guardara la ruta.

`rag_documents.stored_path` se agregó después de que ya hubiera documentos
indexados, así que esos tienen la ruta nula: su archivo existe y está en
uso, pero nada en la base lo reclama. Eso los hace parecer basura ante
tools/auditar_datos.py, y borrarlos destruiría el original de un documento
vivo.

Empareja por el nombre: los archivos se guardan como <8 hex>_<nombre
original>, así que el sufijo identifica a cuál pertenece cada uno.

    python tools/reparar_rutas_rag.py            # muestra qué haría
    python tools/reparar_rutas_rag.py --aplicar
"""

import argparse
import os
import sqlite3
import sys

DB = os.path.join("data", "traffic.db")
DOCS = "data/rag_docs"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true")
    args = ap.parse_args()

    # La columna stored_path la crea init_schema con _ensure_column, y esta
    # herramienta puede correr antes de que la aplicación haya tocado el
    # RAG. Sin esto falla con "no such column".
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from src.ai import rag
    rag.init_schema()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    faltan = conn.execute(
        "SELECT id, name FROM rag_documents WHERE stored_path IS NULL").fetchall()
    if not faltan:
        print("Todos los documentos tienen su ruta guardada.")
        return 0

    archivos = os.listdir(DOCS) if os.path.isdir(DOCS) else []
    tomados = {r[0] for r in conn.execute(
        "SELECT stored_path FROM rag_documents WHERE stored_path IS NOT NULL") if r[0]}

    emparejados, sin_pareja = [], []
    for doc in faltan:
        # El prefijo son 8 hex y un guion bajo; el resto es el nombre tal
        # como lo subió el usuario.
        cand = [a for a in archivos
                if a[9:] == doc["name"]
                and os.path.abspath(os.path.join(DOCS, a)) not in tomados]
        if len(cand) == 1:
            emparejados.append((doc["id"], doc["name"], os.path.join(DOCS, cand[0])))
        else:
            # Cero candidatos, o varios: en ninguno de los dos casos se
            # puede decidir sin riesgo de asignar el archivo equivocado.
            sin_pareja.append((doc["id"], doc["name"], len(cand)))

    for doc_id, nombre, ruta in emparejados:
        print(f"  documento {doc_id}  {nombre}  ->  {ruta}")
        if args.aplicar:
            conn.execute("UPDATE rag_documents SET stored_path = ? WHERE id = ?",
                         (ruta, doc_id))
    for doc_id, nombre, n in sin_pareja:
        print(f"  documento {doc_id}  {nombre}  ->  {n} candidatos, sin emparejar")

    if args.aplicar:
        conn.commit()
        print(f"\n{len(emparejados)} rutas guardadas.")
    elif emparejados:
        print(f"\n{len(emparejados)} se pueden emparejar. Corre con --aplicar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
