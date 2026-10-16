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

from fastapi import APIRouter, HTTPException, Request
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
    # Sin acentos: `isalnum` deja pasar la "í" de "terracería", y una
    # cabecera HTTP con caracteres fuera de ASCII sale mal formada igual.
    import unicodedata
    ascii_ = unicodedata.normalize("NFKD", proyecto).encode("ascii", "ignore").decode()
    limpio = "".join(c if c.isalnum() or c in "-_" else "-" for c in ascii_)
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
    ] + [f"total_{t}" for t in tipos] + ["cobertura_video"]

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
                # Al final para no mover las columnas de quien ya suma sobre
                # este CSV. Menos de 1 = periodo con video incompleto.
                + [iv.get("cobertura", "")]
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
    ] + [f"total_{t}" for t in tipos] + ["cobertura_video"]

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


@router.get("/movimientos.csv")
def exportar_movimientos(project_id: int):
    """Aforo direccional: cada cuarto de hora, cada movimiento numerado
    (1_2, 2_3...) con A, B y C, como la hoja MOVIMIENTOS (15 MIN) del Excel."""
    from src.reports.aforo_excel import formato_direccional

    proyecto = traffic_db.get_project(project_id)
    if proyecto is None:
        raise HTTPException(404, "Proyecto no encontrado")
    datos = formato_direccional(project_id)
    if datos is None:
        raise HTTPException(404, "Los accesos no tienen el número del croquis")
    filas = [[q["fecha"], q["etiqueta"], mv, *q["valores"][mv], sum(q["valores"][mv])]
             for q in datos["cuartos"] for mv in datos["movimientos"]]
    return _respuesta_csv(filas, ["fecha", "intervalo", "movimiento", "A", "B", "C", "total"],
                          _nombre_archivo(proyecto["name"], "movimientos"))


@router.get("/eventos.csv")
def exportar_eventos(project_id: int, request: Request):
    """
    Un renglón por vehículo: hora, dónde, clase, si cuenta y el enlace a su
    recorte. Es lo que hace auditable un aforo —Miovision lo vende así:
    quien audita ve el mismo cuadro que vio el sistema— y lo que deja
    rastrear cualquier cifra del Excel hasta los vehículos que la forman.

    En el direccional cada renglón dice además qué se hizo con él: si cuenta,
    en qué movimiento y cómo se decidió, o por qué no cuenta (pedazo de otro
    vehículo, la cámara no cubre el movimiento...).
    """
    from src.engine.revision import _clase_mostrada, opciones_de_clase

    proyecto = traffic_db.get_project(project_id)
    if proyecto is None:
        raise HTTPException(404, "Proyecto no encontrado")
    # El enlace tiene que servir desde donde se abrió la plataforma: por la
    # dirección pública llega por el relevo de Tailscale, que avisa el host
    # original en X-Forwarded-Host.
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    esquema = request.headers.get("x-forwarded-proto") or request.url.scheme
    base = f"{esquema}://{host}"
    cruces, ctx = traffic_db.cruces_para_revision(project_id)
    opciones = opciones_de_clase(project_id, ctx)
    nombres = {z["id"]: z["name"] for z in traffic_db.list_zones(project_id, active_only=False)}

    def numero(z):
        if z is None:
            return "?"
        n = traffic_db.numero_de_acceso(nombres.get(z, ""))
        return str(n) if n is not None else nombres.get(z, "?")

    def revisado(f):
        return "a mano" if f.get("clase_revisada_por") == "revision_manual" else (
            "modelo de visión" if f.get("clase_revisada") else "")

    filas = []
    for c in cruces:
        filas.append([c["timestamp"], "cruce de línea", c["linea"],
                      "entra" if c["direction"] == "in" else "sale",
                      _clase_mostrada(c["clase"], opciones), c["bbox_height"],
                      round(c["confidence"], 2) if c["confidence"] is not None else "",
                      "sí", "", revisado(c),
                      f"{base}/api/projects/{project_id}/revision/recorte/cruce/{c['id']}.jpg"])
    movs = traffic_db.movimientos_para_revision(project_id)
    if movs:
        decision = traffic_db.decisiones_od(project_id)
        for m in movs:
            d = decision.get(m["id"], {})
            filas.append([m["timestamp"], "movimiento",
                          f"{numero(d.get('origen_id'))}_{numero(d.get('destino_id'))}" if d.get("cuenta") else m["movimiento"],
                          "", _clase_mostrada(m["clase"], opciones), m["bbox_height"],
                          round(m["confidence"], 2) if m["confidence"] is not None else "",
                          "sí" if d.get("cuenta") else "no", d.get("como", ""),
                          "a mano" if m.get("clase_revisada") else "",
                          f"{base}/api/projects/{project_id}/revision/recorte/movimiento/{m['id']}.jpg"])
    filas.sort(key=lambda f: f[0])
    return _respuesta_csv(filas, ["hora", "tipo", "linea_o_movimiento", "sentido", "clase", "alto_px",
                                  "confianza", "cuenta", "como_se_decidio", "clase_revisada", "recorte"],
                          _nombre_archivo(proyecto["name"], "eventos"))


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
