"""
Importar videos de la carpeta de entrada (WinSCP o un disco conectado al
Jetson) a una intersección. Ver src/storage/entrada.py.
"""

import re
from datetime import datetime

from fastapi import APIRouter, HTTPException

from src.storage import disco_videos, entrada

router = APIRouter(prefix="/api/entrada")
_INICIO = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}(:\d{2})?$")


@router.get("")
def listar(project_id: int = None):
    return {**entrada.listar(project_id), "importacion": entrada.estado()}


@router.get("/estado")
def estado():
    return entrada.estado()


@router.post("/importar")
def importar(datos: dict):
    problema = disco_videos.problema_para_subir()
    if problema:
        raise HTTPException(507, detail={"mensaje": problema})
    proyecto_id = int(datos.get("project_id") or 0)
    pedidos = []
    for p in datos.get("archivos") or []:
        inicio = (p.get("inicio") or "").strip()
        # Sin hora el video no cae en ningún cuarto de hora del reporte.
        if not _INICIO.match(inicio):
            raise HTTPException(400, detail={"mensaje": f"Falta la fecha y la hora de inicio de {p.get('ruta')}."})
        if len(inicio) == 16:
            inicio += ":00"
        # Un año imposible no da error en ningún otro lado: el video cae en un
        # día que nadie consulta. Pasó con "0002-11-09" (19-nov-2026).
        try:
            fecha = datetime.strptime(inicio, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            raise HTTPException(400, detail={"mensaje": f"La fecha de {p.get('ruta')} no existe: {inicio}."})
        if not 2000 <= fecha.year <= 2100:
            raise HTTPException(400, detail={"mensaje": f"El año de {p.get('ruta')} es {fecha.year}; revisa la fecha."})
        pedidos.append({"ruta": str(p.get("ruta") or ""), "inicio": inicio})
    if not pedidos:
        raise HTTPException(400, detail={"mensaje": "No se eligió ningún video."})
    try:
        return entrada.importar(proyecto_id, pedidos, disco_videos.DIRECTORIO)
    except LookupError as e:
        raise HTTPException(404, detail={"mensaje": str(e)})
    except RuntimeError as e:
        raise HTTPException(409, detail={"mensaje": str(e)})
    except (ValueError, FileNotFoundError):
        raise HTTPException(400, detail={"mensaje": "Algún archivo ya no está en la carpeta de entrada; "
                                                     "vuelve a cargar la lista."})
