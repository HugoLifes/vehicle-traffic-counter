"""
API del RAG: subir documentos, consultarlos y preguntar sobre ellos.

Los documentos pueden atarse a una intersección o quedar sueltos. Los
sueltos son la normativa que aplica a todos los estudios (la PT-914, los
manuales); los atados son lo específico de un cliente o un tramo. Al
preguntar dentro de un proyecto se ven los suyos y los generales, nunca
los de otra intersección.
"""

import logging
import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from src.ai import nvidia_client, rag

router = APIRouter(prefix="/api/rag", tags=["rag"])

DOCS_DIR = Path("data/rag_docs")
EXTENSIONES = {".pdf", ".txt", ".md", ".csv"}
MAX_BYTES = 40 * 1024 * 1024


class Pregunta(BaseModel):
    pregunta: str
    project_id: Optional[int] = None
    n: int = 6


def _exigir_key():
    if not nvidia_client.is_configured():
        raise HTTPException(
            503,
            "El RAG necesita la API key de NVIDIA. Genera una gratis en "
            "https://build.nvidia.com y ponla en el archivo .env como "
            "NVIDIA_API_KEY."
        )


@router.get("/documentos")
def listar(project_id: Optional[int] = None):
    return rag.listar_documentos(project_id=project_id)


@router.post("/documentos")
async def subir(file: UploadFile = File(...), project_id: Optional[int] = Form(None)):
    """
    Sube un documento y lo indexa en el momento.

    Se indexa aquí y no en segundo plano a propósito: el usuario acaba de
    subir el archivo y necesita saber si sirvió. Un PDF escaneado sin texto
    extraíble, por ejemplo, tiene que fallar con un mensaje que explique
    que hace falta OCR — no quedarse en una cola y aparecer vacío después.
    """
    _exigir_key()

    nombre = Path(file.filename or "documento").name
    if Path(nombre).suffix.lower() not in EXTENSIONES:
        raise HTTPException(
            400,
            f"Formato no soportado. Se aceptan: {', '.join(sorted(EXTENSIONES))}."
        )

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    destino = DOCS_DIR / f"{uuid.uuid4().hex[:8]}_{nombre}"
    try:
        with open(destino, "wb") as out:
            shutil.copyfileobj(file.file, out)
        tam = destino.stat().st_size
        if tam > MAX_BYTES:
            destino.unlink(missing_ok=True)
            raise HTTPException(413, f"El archivo pasa de {MAX_BYTES // 1024 // 1024} MB.")

        return rag.indexar(str(destino), nombre, project_id=project_id, size_bytes=tam)

    except HTTPException:
        raise
    except ValueError as e:
        # Errores esperables del propio documento (PDF escaneado, vacío):
        # el archivo no sirve, así que no se conserva.
        destino.unlink(missing_ok=True)
        raise HTTPException(400, str(e))
    except Exception as e:
        destino.unlink(missing_ok=True)
        logging.exception("RAG: falló el indexado")
        raise HTTPException(500, f"No se pudo indexar el documento: {e}")


@router.delete("/documentos/{doc_id}")
def borrar(doc_id: int):
    borrados = rag.borrar_documento(doc_id)
    return {"deleted": doc_id, "fragmentos": borrados}


@router.post("/buscar")
def buscar(p: Pregunta):
    """Solo recuperación, sin generar respuesta. Sirve para ver qué
    fragmentos alimentan una respuesta, sin gastar una llamada al modelo."""
    _exigir_key()
    return {"fuentes": rag.buscar(p.pregunta, n=p.n, project_id=p.project_id)}


@router.post("/preguntar")
def preguntar(p: Pregunta):
    _exigir_key()
    if not p.pregunta.strip():
        raise HTTPException(400, "La pregunta viene vacía.")
    try:
        return rag.responder(p.pregunta.strip(), n=p.n, project_id=p.project_id)
    except nvidia_client.NvidiaClientError as e:
        raise HTTPException(503, str(e))


# --- Conversaciones ----------------------------------------------------

class NuevaConversacion(BaseModel):
    project_id: Optional[int] = None
    titulo: Optional[str] = None


class MensajeChat(BaseModel):
    conversacion_id: int
    pregunta: str
    n: int = 6


@router.get("/conversaciones")
def listar_conversaciones(project_id: Optional[int] = None):
    """Las de una intersección, o las generales si no se pasa project_id.

    No se mezclan a propósito: preguntar dentro de un proyecto no debe
    mostrar el hilo de otro, aunque el documento de fondo sea el mismo."""
    return rag.listar_conversaciones(project_id=project_id)


@router.post("/conversaciones")
def crear_conversacion(c: NuevaConversacion):
    cid = rag.crear_conversacion(c.project_id, c.titulo or "Consulta")
    return {"id": cid}


@router.get("/conversaciones/{conversacion_id}")
def leer_conversacion(conversacion_id: int):
    return {"mensajes": rag.mensajes(conversacion_id)}


@router.delete("/conversaciones/{conversacion_id}")
def borrar_conversacion(conversacion_id: int):
    rag.borrar_conversacion(conversacion_id)
    return {"deleted": conversacion_id}


@router.post("/chat")
def chat(m: MensajeChat):
    """
    Un turno de conversación: guarda la pregunta, responde con el hilo
    previo en cuenta, y guarda la respuesta con sus fuentes.

    El título de la conversación se toma de la primera pregunta, porque
    una lista de hilos llamados todos "Consulta" no sirve para volver a
    ninguno.
    """
    _exigir_key()
    pregunta = m.pregunta.strip()
    if not pregunta:
        raise HTTPException(400, "La pregunta viene vacía.")

    conv = rag.obtener_conversacion(m.conversacion_id)
    if conv is None:
        raise HTTPException(404, "Esa conversación no existe.")
    previos = rag.mensajes(m.conversacion_id)

    try:
        salida = rag.responder(pregunta, n=m.n, project_id=conv["project_id"],
                               conversacion_id=m.conversacion_id)
    except nvidia_client.NvidiaClientError as e:
        raise HTTPException(503, str(e))

    if not previos:
        rag.titular(m.conversacion_id, pregunta)
    return salida
