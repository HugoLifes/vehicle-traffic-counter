"""
Exportación del aforo.

Es lo que se entrega al cliente. Hasta ahora las cifras solo existían en
pantalla y había que copiarlas a mano a una hoja de cálculo, que es
justo donde se cuelan los errores de transcripción en un estudio que
luego sustenta una decisión de obra.

Dos formatos, cada uno para lo suyo:

  · CSV por intervalo — la tabla en bruto, una fila por carril y periodo.
    Es lo que se abre en Excel para hacer cuentas propias.
  · CSV de resumen — una sola fila por carril, con los totales, la
    composición y el factor de hora pico ya calculados.

El PDF no se genera aquí: la pantalla de reporte tiene hoja de estilos de
impresión, así que el propio navegador produce un PDF con las gráficas
vectoriales reales. Generarlo en el servidor obligaría a redibujarlas con
otra librería y a mantener dos versiones del mismo informe.
"""

import csv
import io
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from src.storage import traffic_db, traffic_metrics

router = APIRouter(prefix="/api/export")


def _nombre_archivo(proyecto: str, sufijo: str) -> str:
    """
    Nombre de archivo seguro y con fecha.

    Los nombres de intersección llevan acentos, espacios y el signo "×"
    ("Reforma × Insurgentes"). Sin limpiarlos, la cabecera Content-
    Disposition sale mal formada y el navegador guarda el archivo con un
    nombre roto o lo rechaza.
    """
    limpio = "".join(c if c.isalnum() or c in "-_" else "-" for c in proyecto)
    limpio = "-".join(filter(None, limpio.split("-")))[:60] or "aforo"
    return f"{limpio}-{sufijo}-{datetime.now():%Y%m%d}.csv"


def _respuesta_csv(filas: list, cabeceras: list, nombre: str) -> StreamingResponse:
    buffer = io.StringIO()
    # Marca de orden de bytes: sin ella Excel en Windows abre los acentos
    # como caracteres sueltos ("Automóvil"), que es como llegan estos
    # archivos al cliente.
    buffer.write("﻿")
    escritor = csv.writer(buffer, lineterminator="\n")
    escritor.writerow(cabeceras)
    escritor.writerows(filas)
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


@router.get("/intervalos.csv")
def exportar_intervalos(project_id: int, minutes: int = 15):
    """Una fila por carril y periodo, con el desglose por tipo."""
    proyecto = traffic_db.get_project(project_id)
    if proyecto is None:
        raise HTTPException(404, "Esa intersección no existe")

    m = traffic_metrics.get_project_metrics(project_id, minutes)

    # Se recogen todos los tipos presentes para que la tabla tenga las
    # mismas columnas en todas las filas: una hoja con columnas variables
    # no se puede sumar.
    tipos = sorted({t for c in m["lanes"] for t in c["composition"]})

    cabeceras = [
        "interseccion", "carril", "inicio", "fin",
        "entrada", "salida", "total",
    ] + [f"total_{t}" for t in tipos]

    filas = []
    for carril in m["lanes"]:
        for iv in carril["intervals"]:
            por_tipo = iv.get("by_vehicle_type", {})
            filas.append(
                [
                    proyecto["name"],
                    carril["lane_name"],
                    iv["start"],
                    iv["end"],
                    iv["in"],
                    iv["out"],
                    iv["total"],
                ]
                + [
                    (por_tipo.get(t, {}).get("in", 0) + por_tipo.get(t, {}).get("out", 0))
                    for t in tipos
                ]
            )

    return _respuesta_csv(filas, cabeceras, _nombre_archivo(proyecto["name"], "intervalos"))


@router.get("/resumen.csv")
def exportar_resumen(project_id: int, minutes: int = 15):
    """Una fila por carril con los totales y el factor de hora pico."""
    proyecto = traffic_db.get_project(project_id)
    if proyecto is None:
        raise HTTPException(404, "Esa intersección no existe")

    m = traffic_metrics.get_project_metrics(project_id, minutes)
    tipos = sorted({t for c in m["lanes"] for t in c["composition"]})

    cabeceras = [
        "interseccion", "direccion", "latitud", "longitud",
        "intervalo_min", "carril",
        "entrada", "salida", "total",
        "hora_pico_inicio", "hora_pico_fin", "volumen_hora_pico",
        "fhp", "flujo_irregular",
    ] + [f"total_{t}" for t in tipos]

    filas = []
    for carril in m["lanes"]:
        pico = carril.get("peak_hour")
        filas.append(
            [
                proyecto["name"],
                proyecto.get("address") or "",
                proyecto.get("latitude") if proyecto.get("latitude") is not None else "",
                proyecto.get("longitude") if proyecto.get("longitude") is not None else "",
                m["interval_minutes"],
                carril["lane_name"],
                carril["in"],
                carril["out"],
                carril["total"],
                pico["start"] if pico else "",
                pico["end"] if pico else "",
                pico["volume"] if pico else "",
                # El FHP se deja vacío, no en cero, cuando no hay una hora
                # completa que lo sustente: un cero se sumaría en un
                # promedio y falsearía el estudio.
                f"{pico['fhp']:.4f}" if pico and pico.get("fhp") is not None else "",
                ("si" if pico["flujo_irregular"] else "no") if pico and pico.get("fhp") is not None else "",
            ]
            + [carril["composition"].get(t, 0) for t in tipos]
        )

    return _respuesta_csv(filas, cabeceras, _nombre_archivo(proyecto["name"], "resumen"))


@router.get("/aforo.xlsx")
def exportar_excel(project_id: int):
    """
    El informe en el formato de la empresa, listo para entregar.

    Los CSV de arriba sirven para hacer cuentas propias; esto es el
    entregable: mismas hojas y misma disposición que los estudios que el
    cliente ya recibe, para que no haya que rehacerlo a mano.

    Se genera en memoria y no en disco: es un archivo por descarga, y
    dejarlos acumularse en data/ solo crea basura que después hay que
    limpiar.
    """
    from src.reports import aforo_excel

    proyecto = traffic_db.get_project(project_id)
    if proyecto is None:
        raise HTTPException(404, "Proyecto no encontrado")

    import tempfile
    import os
    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    tmp.close()
    try:
        aforo_excel.generar(project_id, tmp.name)
        with open(tmp.name, "rb") as fh:
            datos = fh.read()
    except ValueError as e:
        raise HTTPException(409, str(e))
    finally:
        os.unlink(tmp.name)

    nombre = _nombre_archivo(proyecto["name"], "aforo")
    return StreamingResponse(
        io.BytesIO(datos),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{nombre}.xlsx"'},
    )
