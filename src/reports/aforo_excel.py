"""
Genera el Excel de aforo en el formato que usa la empresa.

Reproduce el formato de los estudios que ya entrega el cliente (las
estaciones 22 y 26 sirvieron de patrón), porque un informe que llega con
otra estructura obliga a rehacerlo a mano aunque los números estén bien.

Dos hojas, como los originales:

**TOTALES (est)** — resumen semanal. Tres bloques de diez columnas, uno
por sentido y el tercero con la suma: hora contra día de la semana, con
subtotal de lunes a viernes aparte del fin de semana, porque el tránsito
laboral y el de fin de semana no se promedian juntos.

**(EST) (15MIN)** — variación por cuartos de hora. Un bloque por sentido,
con los cuatro cuartos de cada hora y su total, que es donde se ve el pico
real y de donde sale el factor de hora pico.

Sobre los datos que faltan: la plataforma cuenta lo que hay grabado. Si un
aforo cubre tres horas de un martes, el resto de la semana sale vacío en
vez de a cero — un cero dice "no pasó nadie" y un hueco dice "no se
midió", y confundirlos en un informe de tránsito es grave.
"""

import logging
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from src.storage import traffic_db

DIAS = ["LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO", "DOMINGO"]
MESES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO",
         "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]

_TITULO = Font(bold=True, size=14)
_SUBTITULO = Font(bold=True, size=11)
_ETIQUETA = Font(bold=True, size=9)
_NORMAL = Font(size=9)
_CABECERA = Font(bold=True, size=9)
_GRIS = PatternFill("solid", fgColor="D9D9D9")
_AZUL = PatternFill("solid", fgColor="DCE6F1")
_CENTRO = Alignment(horizontal="center", vertical="center")
_IZQ = Alignment(horizontal="left", vertical="center")
_borde = Side(style="thin", color="808080")
_CAJA = Border(left=_borde, right=_borde, top=_borde, bottom=_borde)


def _fecha_larga(f: datetime) -> str:
    return f"{f.day} DE {MESES[f.month - 1]} DEL {f.year}"


def _celda(ws, fila, col, valor, fuente=_NORMAL, relleno=None,
           alineacion=_CENTRO, borde=True):
    c = ws.cell(fila, col, valor)
    c.font = fuente
    c.alignment = alineacion
    if relleno:
        c.fill = relleno
    if borde:
        c.border = _CAJA
    return c


# Confianza media por debajo de la cual una hora NO se puede medir y su
# celda va vacia en vez de con un numero.
#
# Medido sobre las 24 h del 19-ago-2026 contra el aforo contado a mano:
#
#   00:00-05:00  confianza 0.40-0.49   ->  0.03x del transito real
#   06:00        confianza 0.71        ->  0.59x
#   07:00-10:00  confianza 0.73-0.76   ->  0.94x-0.99x
#   21:00        confianza 0.50        ->  0.03x
#
# El corte cae limpio en el hueco entre 0.58 y 0.71. De noche la camara
# sobreexpone y barre el movimiento: el vehiculo sale como una estela y el
# detector, cuando acierta, lo hace con poca confianza.
#
# Se usa la confianza y NO el conteo: una hora de madrugada con poco
# transito real tendria pocos cruces pero ALTA confianza. Filtrar por
# conteo escondería las horas genuinamente tranquilas.
CONFIANZA_MINIMA = 0.65


def _horas_no_medibles(conn, project_id: int) -> set:
    """{(dia_semana, hora)} donde la camara no vio lo suficiente.

    Imprimir el numero de esas horas seria lo peor que puede hacer este
    informe: el sistema conto 8 vehiculos entre las 05:00 y las 06:00
    donde el aforo manual conto 2 038, y en la hoja se leia como una
    medicion.
    """
    fuera = set()
    for f in conn.execute("""
        SELECT c.timestamp AS ts, AVG(c.confidence) AS cf, COUNT(*) AS n
        FROM crossings c JOIN lane_configs l ON l.id = c.lane_id
        WHERE l.project_id = ?
        GROUP BY substr(c.timestamp, 1, 13)
    """, (project_id,)):
        try:
            t = datetime.strptime(f["ts"], "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            continue
        if f["cf"] is not None and f["cf"] < CONFIANZA_MINIMA:
            fuera.add((t.weekday(), t.hour))
    return fuera


def _datos(project_id: int) -> Dict:
    """
    Saca de la base todo lo que el informe necesita, en una sola pasada.

    Se agrupa por SENTIDO y no por línea: el informe de la empresa habla de
    direcciones ("NTE-SUR"), y en esta plataforma el sentido lo da la zona
    de calzada a la que se atribuyó el cruce.
    """
    conn = traffic_db.get_connection()
    proyecto = traffic_db.get_project(project_id)
    if proyecto is None:
        raise ValueError(f"No existe el proyecto {project_id}")

    filas = conn.execute("""
        SELECT c.timestamp AS ts,
               COALESCE(z.name, l.name) AS sentido
        FROM crossings c
        JOIN lane_configs l ON l.id = c.lane_id
        LEFT JOIN zones z ON z.id = c.zone_id
        WHERE l.project_id = ?
        ORDER BY c.timestamp
    """, (project_id,)).fetchall()

    # por_hora[sentido][dia_semana][hora] y por_cuarto[sentido][fecha][minuto]
    por_hora = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    por_cuarto = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    fechas = set()
    dias_vistos = defaultdict(set)   # sentido -> {(dia_semana)}
    primera = ultima = None

    for f in filas:
        try:
            t = datetime.strptime(f["ts"], "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            continue
        s = f["sentido"] or "SIN SENTIDO"
        por_hora[s][t.weekday()][t.hour] += 1
        por_cuarto[s][t.date()][t.hour * 60 + (t.minute // 15) * 15] += 1
        fechas.add(t.date())
        dias_vistos[s].add(t.weekday())
        primera = t if primera is None or t < primera else primera
        ultima = t if ultima is None or t > ultima else ultima

    return {
        "proyecto": proyecto,
        "no_medibles": _horas_no_medibles(conn, project_id),
        "sentidos": sorted(por_hora.keys()),
        "por_hora": por_hora,
        "por_cuarto": por_cuarto,
        "fechas": sorted(fechas),
        "dias_vistos": dias_vistos,
        "inicio": primera,
        "fin": ultima,
        "total": len(filas),
    }


def _bloque_totales(ws, col0: int, titulo_dir: str, d: Dict, horas: Dict,
                    dias_medidos: set):
    """Un bloque de diez columnas: hora contra día de la semana."""
    p = d["proyecto"]

    _celda(ws, 1, col0, "AFORO VEHICULAR CONTINUO", _TITULO, borde=False)
    ws.merge_cells(start_row=1, start_column=col0, end_row=1, end_column=col0 + 9)
    _celda(ws, 2, col0, "RESUMEN SEMANAL", _SUBTITULO, borde=False)
    ws.merge_cells(start_row=2, start_column=col0, end_row=2, end_column=col0 + 9)

    _celda(ws, 3, col0, "LUGAR:", _ETIQUETA, alineacion=_IZQ, borde=False)
    _celda(ws, 3, col0 + 1, p["name"], _NORMAL, alineacion=_IZQ, borde=False)
    _celda(ws, 3, col0 + 5, "UBICACION:", _ETIQUETA, alineacion=_IZQ, borde=False)
    _celda(ws, 3, col0 + 6, p.get("address") or "", _NORMAL, alineacion=_IZQ, borde=False)

    _celda(ws, 4, col0, "ESTACION:", _ETIQUETA, alineacion=_IZQ, borde=False)
    _celda(ws, 4, col0 + 1, p["id"], _NORMAL, alineacion=_IZQ, borde=False)
    _celda(ws, 4, col0 + 6, "CONDICIONES ATMOSFERICAS", _ETIQUETA,
           alineacion=_IZQ, borde=False)

    ini = _fecha_larga(d["inicio"]) if d["inicio"] else ""
    fin = _fecha_larga(d["fin"]) if d["fin"] else ""
    _celda(ws, 5, col0, "FECHA DE INICIO DE AFORO:", _ETIQUETA, alineacion=_IZQ, borde=False)
    _celda(ws, 5, col0 + 2, ini, _NORMAL, alineacion=_IZQ, borde=False)
    _celda(ws, 5, col0 + 6, "DESPEJADO:", _NORMAL, alineacion=_IZQ, borde=False)
    _celda(ws, 5, col0 + 8, "LLUVIA", _NORMAL, alineacion=_IZQ, borde=False)
    _celda(ws, 6, col0, "FECHA DE TERMINO DE AFORO:", _ETIQUETA, alineacion=_IZQ, borde=False)
    _celda(ws, 6, col0 + 2, fin, _NORMAL, alineacion=_IZQ, borde=False)
    _celda(ws, 6, col0 + 6, "NIEVE:", _NORMAL, alineacion=_IZQ, borde=False)
    _celda(ws, 6, col0 + 8, "HIELO", _NORMAL, alineacion=_IZQ, borde=False)

    _celda(ws, 8, col0 + 1, f"NUMERO DE VEHICULOS EN DIRECCION: {titulo_dir}",
           _SUBTITULO, _AZUL)
    ws.merge_cells(start_row=8, start_column=col0 + 1, end_row=8, end_column=col0 + 9)

    cabeceras = ["HORA"] + DIAS[:5] + ["SUBTOTAL", "SABADO", "DOMINGO", "TOTAL POR SEMANA"]
    for i, h in enumerate(cabeceras):
        _celda(ws, 9, col0 + i, h, _CABECERA, _GRIS)

    fila = 10
    _celda(ws, fila, col0, "A.M.", _CABECERA, _GRIS)
    ws.merge_cells(start_row=fila, start_column=col0, end_row=fila, end_column=col0 + 9)
    fila += 1

    total_dia = defaultdict(int)
    for hora in range(24):
        if hora == 12:
            _celda(ws, fila, col0, "P.M.", _CABECERA, _GRIS)
            ws.merge_cells(start_row=fila, start_column=col0,
                           end_row=fila, end_column=col0 + 9)
            fila += 1

        _celda(ws, fila, col0, f"{hora:02d}:00-{hora + 1:02d}:00", _NORMAL)
        entre_semana = 0
        for i in range(5):
            # Hueco, no cero: un cero afirma que no pasó nadie, y ahí lo que
            # ocurre es que no se midió.
            v = horas.get(i, {}).get(hora) if i in dias_medidos else None
            if (i, hora) in d["no_medibles"]:
                v = None
            _celda(ws, fila, col0 + 1 + i, v if v is not None else "")
            if v:
                entre_semana += v
                total_dia[i] += v
        _celda(ws, fila, col0 + 6, entre_semana or "", _CABECERA)

        finde = 0
        for j, i in enumerate((5, 6)):
            v = horas.get(i, {}).get(hora) if i in dias_medidos else None
            if (i, hora) in d["no_medibles"]:
                v = None
            _celda(ws, fila, col0 + 7 + j, v if v is not None else "")
            if v:
                finde += v
                total_dia[i] += v
        _celda(ws, fila, col0 + 9, (entre_semana + finde) or "", _CABECERA)
        fila += 1

    _celda(ws, fila, col0, "TOTAL", _CABECERA, _GRIS)
    for i in range(5):
        _celda(ws, fila, col0 + 1 + i, total_dia.get(i) or "", _CABECERA, _GRIS)
    sub = sum(total_dia.get(i, 0) for i in range(5))
    _celda(ws, fila, col0 + 6, sub or "", _CABECERA, _GRIS)
    for j, i in enumerate((5, 6)):
        _celda(ws, fila, col0 + 7 + j, total_dia.get(i) or "", _CABECERA, _GRIS)
    total = sum(total_dia.values())
    _celda(ws, fila, col0 + 9, total or "", _CABECERA, _GRIS)

    # Indicadores. Se dividen entre los días REALMENTE medidos, no entre 7:
    # con tres horas de un martes, dividir entre siete daría un tránsito
    # diario siete veces menor que el real.
    n_dias = len(dias_medidos) or 1
    fila += 2
    _celda(ws, fila, col0, f"Transito Diario Promedio ({n_dias} días medidos)",
           _ETIQUETA, alineacion=_IZQ, borde=False)
    _celda(ws, fila, col0 + 3, round(total / n_dias, 1) if total else "",
           _NORMAL, borde=False)

    pico = 0
    for i in dias_medidos:
        for hora in range(24):
            pico = max(pico, horas.get(i, {}).get(hora, 0))
    _celda(ws, fila + 1, col0, "Volumen Horario Máximo", _ETIQUETA,
           alineacion=_IZQ, borde=False)
    _celda(ws, fila + 1, col0 + 3, pico or "", _NORMAL, borde=False)

    for i in range(10):
        ws.column_dimensions[get_column_letter(col0 + i)].width = 13 if i == 0 else 10


def _hoja_totales(wb: Workbook, d: Dict):
    ws = wb.create_sheet("TOTALES (est)")
    ws.sheet_view.showGridLines = False

    col = 1
    for sentido in d["sentidos"]:
        _bloque_totales(ws, col, sentido.upper(), d,
                        d["por_hora"][sentido], d["dias_vistos"][sentido])
        col += 11

    # Bloque de ambos sentidos: solo tiene sentido si hay más de uno.
    if len(d["sentidos"]) > 1:
        juntos = defaultdict(lambda: defaultdict(int))
        dias = set()
        for s in d["sentidos"]:
            dias |= d["dias_vistos"][s]
            for dia, horas in d["por_hora"][s].items():
                for h, v in horas.items():
                    juntos[dia][h] += v
        _bloque_totales(ws, col, "EN AMBOS SENTIDOS", d, juntos, dias)


def _hoja_cuartos(wb: Workbook, d: Dict):
    ws = wb.create_sheet("(EST) (15MIN)")
    ws.sheet_view.showGridLines = False
    p = d["proyecto"]
    fechas = d["fechas"]

    col = 1
    for sentido in d["sentidos"]:
        ancho = 1 + len(fechas)
        _celda(ws, 1, col, "VARIACION POR CUARTOS DE HORA", _TITULO, borde=False)
        ws.merge_cells(start_row=1, start_column=col, end_row=1,
                       end_column=col + max(1, ancho - 1))
        _celda(ws, 2, col, "LUGAR:", _ETIQUETA, alineacion=_IZQ, borde=False)
        _celda(ws, 2, col + 1, p["name"], _NORMAL, alineacion=_IZQ, borde=False)
        _celda(ws, 3, col, "ESTACION No.", _ETIQUETA, alineacion=_IZQ, borde=False)
        _celda(ws, 3, col + 1, p["id"], _NORMAL, alineacion=_IZQ, borde=False)

        _celda(ws, 5, col + 1, f"NUMERO DE VEHICULOS — {sentido.upper()}",
               _SUBTITULO, _AZUL)
        if ancho > 1:
            ws.merge_cells(start_row=5, start_column=col + 1, end_row=5,
                           end_column=col + ancho - 1)

        _celda(ws, 6, col, "HORA", _CABECERA, _GRIS)
        for i, f in enumerate(fechas):
            _celda(ws, 6, col + 1 + i,
                   f"{DIAS[f.weekday()]} {f.day:02d}/{MESES[f.month - 1][:3]}",
                   _CABECERA, _GRIS)

        fila = 7
        for hora in range(24):
            for q in range(4):
                ini = hora * 60 + q * 15
                _celda(ws, fila, col,
                       f"{hora:02d}:{q * 15:02d}-"
                       f"{(hora + (q + 1) // 4):02d}:{((q + 1) * 15) % 60:02d}", _NORMAL)
                for i, f in enumerate(fechas):
                    v = d["por_cuarto"][sentido].get(f, {}).get(ini)
                    if (f.weekday(), hora) in d["no_medibles"]:
                        v = None
                    _celda(ws, fila, col + 1 + i, v if v is not None else "")
                fila += 1
            # Fila de total de la hora, como en los originales.
            _celda(ws, fila, col, f"{hora:02d}:00-{hora + 1:02d}:00", _CABECERA, _GRIS)
            for i, f in enumerate(fechas):
                v = d["por_hora"][sentido].get(f.weekday(), {}).get(hora)
                if (f.weekday(), hora) in d["no_medibles"]:
                    v = None
                _celda(ws, fila, col + 1 + i, v if v is not None else "",
                       _CABECERA, _GRIS)
            fila += 1

        ws.column_dimensions[get_column_letter(col)].width = 13
        for i in range(len(fechas)):
            ws.column_dimensions[get_column_letter(col + 1 + i)].width = 14
        col += ancho + 2


def _hoja_metodo(wb: Workbook, d: Dict):
    """
    De dónde salieron los números.

    Un aforo sustenta decisiones de obra: quien reciba el archivo tiene que
    poder saber qué se midió, cuánto y con qué. Sin esta hoja el informe se
    lee como si cubriera la semana completa aunque solo cubra tres horas.
    """
    ws = wb.create_sheet("METODO")
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 58

    _celda(ws, 1, 1, "ORIGEN DE LOS DATOS", _TITULO, borde=False)
    p = d["proyecto"]
    filas = [
        ("Intersección", p["name"]),
        ("Ubicación", p.get("address") or "—"),
        ("Estación", p["id"]),
        ("Inicio del aforo", d["inicio"].strftime("%Y-%m-%d %H:%M") if d["inicio"] else "—"),
        ("Fin del aforo", d["fin"].strftime("%Y-%m-%d %H:%M") if d["fin"] else "—"),
        ("Días con medición", len(d["fechas"])),
        ("Sentidos", ", ".join(d["sentidos"]) or "—"),
        ("Vehículos contados", d["total"]),
        ("", ""),
        ("Método", "Detección automática por visión computacional"),
        ("Modelo", "YOLOv8s, umbral de confianza 0.25 (PT-914 del IMT)"),
        ("Conteo", "Cruce de línea con atribución por calzada"),
        ("", ""),
        ("Celdas vacías", "Sin medición en ese periodo. NO significa cero "
                          "vehículos: significa que no se grabó, o que se "
                          "grabó en condiciones donde el sistema no puede "
                          "medir (ver abajo)."),
        ("Horas no medibles", f"{len(d['no_medibles'])} de las 24. Se dejan en "
                              "blanco a propósito, en vez de publicar el "
                              "conteo parcial que produjo el detector."),
    ]
    for i, (k, v) in enumerate(filas, start=3):
        _celda(ws, i, 1, k, _ETIQUETA, alineacion=_IZQ, borde=False)
        _celda(ws, i, 2, v, _NORMAL, alineacion=_IZQ, borde=False)

    # El aviso anterior decía "por falta de detalle en el video nocturno".
    # Está medido que es al revés: de noche la imagen es el DOBLE de
    # brillante que de día (177 contra 84 en la franja de la vía). La cámara
    # sobreexpone y barre el movimiento, y el vehículo sale como una estela.
    aviso = ws.cell(len(filas) + 5, 1,
                    "Las horas nocturnas no son medición fiable con el material "
                    "actual. Contrastado contra aforo manual del mismo día: de "
                    "día el sistema mide 0.96x del tránsito real; de noche, "
                    "0.03x. La causa no es falta de luz sino lo contrario — la "
                    "cámara sobreexpone y el obturador lento convierte cada "
                    "vehículo en una estela. Se corrige forzando obturador "
                    "rápido en el modo nocturno de la cámara.")
    aviso.font = Font(size=9, italic=True, color="9C2F26")
    aviso.alignment = _IZQ
    aviso.alignment = Alignment(wrap_text=True, vertical="top")
    ws.merge_cells(start_row=len(filas) + 5, start_column=1,
                   end_row=len(filas) + 6, end_column=2)


def generar(project_id: int, ruta: str) -> Dict:
    """Escribe el Excel y devuelve un resumen de lo que contiene."""
    d = _datos(project_id)
    wb = Workbook()
    wb.remove(wb.active)

    if not d["sentidos"]:
        raise ValueError(
            "Este proyecto todavía no tiene conteos. Procesa los videos antes "
            "de generar el informe."
        )

    _hoja_totales(wb, d)
    _hoja_cuartos(wb, d)
    _hoja_metodo(wb, d)
    wb.save(ruta)

    logging.info(f"Informe de aforo generado: {ruta} ({d['total']} cruces)")
    return {
        "archivo": ruta,
        "cruces": d["total"],
        "sentidos": d["sentidos"],
        "dias": len(d["fechas"]),
    }
