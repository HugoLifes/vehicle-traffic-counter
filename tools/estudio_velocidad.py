"""
Estudio de velocidad por muestreo: velocidad de punto por hora y sentido,
en Excel, sin recontar el aforo.

    python tools/estudio_velocidad.py --proyecto 7 --tray data/nuevos/vel/tray \\
        --calibracion data/nuevos/vel/calibracion.json \\
        --salida data/nuevos/vel/estudio_velocidad_p7.xlsx

Existe porque la velocidad cruce por cruce se guarda al CONTAR (hace falta el
tramo puesto antes) y el aforo frontal se contó sin tramo: tenerla en el
Excel de la plataforma cuesta recontar el día entero (~23 h de Jetson). Un
estudio de velocidad de punto no necesita a todos los vehículos: por norma se
hace sobre una muestra por periodo. Aquí la muestra son recorridos de un
minuto de cada hora (`extraer_trayectorias.py`, uno por archivo HH-MM.json).
Con los tres por hora que se extrajeron para calibrar salían 16-92
vehículos medidos por hora y sentido, poco para las horas tranquilas (se
suele pedir al menos 50); con nueve por hora se triplica.

La distancia del tramo sale de `calibrar_velocidad.py --salida` (fijada contra
las mangueras con unas horas, comprobada en las demás y cruzada entre los dos
sentidos). Cuando alguien mida en el pavimento, `--distancia "Calzada=metros"`
la sustituye sin tocar nada más. Cada sentido lleva su propia distancia: la
calzada que viene se ve en la orilla del cuadro, donde el lente deforma, y
por eso las dos no tienen por qué ser idénticas (salieron 16.7 y 17.5 m).

Lo que NO se publica, por la misma regla que producción
(`velocidad.FRACCION_MINIMA`): una hora en que se alcanzó a medir a menos del
70 % de los que cruzaron la línea de conteo. De noche, hacia la cámara, los
faros parten el rastro entre las dos líneas y solo llega a la segunda el
21-50 %; la velocidad de esos pocos no representa al resto. Tampoco el
percentil 15: el reparto medido sale más ancho que el real y la cola lenta no
aguanta (ver CLAUDE.md, "Velocidad por tramo").
"""

import argparse
import glob
import json
import os
import statistics as st
import sys
from collections import Counter, defaultdict

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "tools"))

from calibrar_velocidad import dentro  # noqa: E402
from src.engine.velocidad import (FRACCION_MINIMA, MAX_KMH, MIN_KMH,  # noqa: E402
                                  MedidorVelocidad, percentil)

# Mismo corte que la regla de clase de produccion: pesado es el `bus` y el
# `truck` de al menos 1.58 veces el automovil mediano de su calzada, medido
# en la misma linea (a distancia fija de la camara).
MULTIPLO_PESADO = 1.58
RANGOS = [(lo, lo + 10) for lo in range(0, 120, 10)]


def medir_muestra(ruta, poligono, linea_a, linea_b, distancia):
    """Por cada rastro de UNA calzada: clase por votos, alto de la caja al
    cruzar la línea de conteo y velocidad si cruzó las dos líneas."""
    with open(ruta, encoding="utf-8") as fh:
        d = json.load(fh)
    ya = linea_a[0][1]
    rastros, por_cuadro = {}, defaultdict(list)
    for tid, r in d["rastros"].items():
        pts = [p for p in r["p"] if dentro(poligono, (p[1] + p[3]) / 2, p[4])]
        alto = None
        for (_, _, _, _, a2, _), (_, x1, y1, x2, b2, _) in zip(pts, pts[1:]):
            if (a2 - ya) * (b2 - ya) <= 0 and a2 != b2:
                alto = b2 - y1
                break
        if alto is None:
            continue        # no cruzó la línea de conteo en esta calzada
        votos = Counter(r.get("clases") or {})
        rastros[int(tid)] = {"clase": votos.most_common(1)[0][0] if votos else "car",
                             "alto": alto, "kmh": None}
        for c, x1, y1, x2, y2, _ in pts:
            por_cuadro[c].append({"id": int(tid), "track_id": int(tid),
                                  "bbox": (x1, y1, x2, y2)})
    med = MedidorVelocidad(linea_a, linea_b, distancia, d["fps"])
    for c in sorted(por_cuadro):
        for m in med.observar(c, por_cuadro[c]):
            r = rastros.get(int(m["track_id"]))
            if r is not None and MIN_KMH <= m["kmh"] <= MAX_KMH:
                r["kmh"] = m["kmh"]
    return list(rastros.values())


def resumen(kmh):
    v = sorted(kmh)
    if not v:
        return {"n": 0}
    return {"n": len(v), "media": st.fmean(v), "p50": percentil(v, 50),
            "p85": percentil(v, 85), "desv": st.pstdev(v) if len(v) > 1 else 0.0}


def estudio(proyecto, tray, calibracion, distancias):
    from src.engine.zones import load_zones
    zonas = {z["name"]: z for z in load_zones(proyecto)}
    muestras = sorted(glob.glob(os.path.join(tray, "*.json")))
    if not muestras:
        sys.exit(f"No hay recorridos en {tray}")
    salida = {}
    for nombre, cal in calibracion.items():
        if nombre not in zonas:
            sys.exit(f"La calibración trae '{nombre}' y el proyecto {proyecto} no tiene esa calzada")
        pol = [tuple(p) for p in zonas[nombre]["points"]]
        la, lb = [[tuple(p) for p in linea] for linea in cal["lineas"]]
        dist = distancias.get(nombre, cal["distancia_m"])
        por_hora = defaultdict(list)
        muestras_hora = defaultdict(list)
        for m in muestras:
            hh, mm = os.path.splitext(os.path.basename(m))[0].split("-")[:2]
            por_hora[hh] += medir_muestra(m, pol, la, lb, dist)
            muestras_hora[hh].append(f"{hh}:{mm}")
        autos = sorted(r["alto"] for rs in por_hora.values() for r in rs if r["clase"] == "car")
        umbral = MULTIPLO_PESADO * percentil(autos, 50)
        tubo = {h["hora"]: h for h in cal.get("horas", [])}
        horas = []
        for hh in sorted(por_hora):
            rs = por_hora[hh]
            medidos = [r for r in rs if r["kmh"] is not None]
            pesado = [r for r in medidos if r["clase"] == "bus"
                      or (r["clase"] == "truck" and r["alto"] >= umbral)]
            ids_pesado = {id(r) for r in pesado}
            liviano = [r for r in medidos
                       if id(r) not in ids_pesado and r["clase"] != "motorcycle"]
            fraccion = len(medidos) / len(rs) if rs else 0.0
            horas.append({
                "hora": hh, "muestras": muestras_hora[hh], "cruzaron": len(rs),
                "fraccion": fraccion, "publica": fraccion >= FRACCION_MINIMA,
                "calibracion": bool(tubo.get(hh, {}).get("cal")),
                "todos": resumen([r["kmh"] for r in medidos]),
                "livianos": resumen([r["kmh"] for r in liviano]),
                "pesados": resumen([r["kmh"] for r in pesado]),
                "tubo_p50": tubo.get(hh, {}).get("tubo_p50"),
                "tubo_p85": tubo.get(hh, {}).get("tubo_p85"),
                "kmh": sorted(r["kmh"] for r in medidos),
            })
        publicadas = [k for h in horas if h["publica"] for k in h["kmh"]]
        salida[nombre] = {"distancia_m": dist, "sentido": cal.get("sentido"),
                          "serie_tubo": cal.get("serie"),
                          "distancia_de": "pavimento" if nombre in distancias else "mangueras",
                          "umbral_pesado_px": umbral, "horas": horas,
                          "dia": resumen(publicadas),
                          "reparto": [sum(lo <= k < hi for k in publicadas) for lo, hi in RANGOS]}
    return salida


# ------------------------------------------------------------------ Excel
def escribir_excel(res, ruta, lugar, fecha):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    TINTA, GRIS, FONDO, NO = "1C2430", "5B6675", "E6EEF8", "F2F2F2"
    neg = Font(bold=True, color=TINTA)
    cab = Font(bold=True, color="FFFFFF")
    relleno_cab = PatternFill("solid", fgColor=TINTA)
    linea = Side(style="thin", color="D5DBE3")
    borde = Border(bottom=linea)
    centro = Alignment(horizontal="center", vertical="center", wrap_text=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "VELOCIDAD POR HORA"
    ws["A1"] = "ESTUDIO DE VELOCIDAD DE PUNTO POR MUESTREO"
    ws["A1"].font = Font(bold=True, size=14, color=TINTA)
    ws["A2"], ws["B2"] = "LUGAR:", lugar
    ws["A3"], ws["B3"] = "FECHA:", fecha
    ws["A4"] = ("Velocidad en km/h. Muestra: 3 minutos por hora. Las horas marcadas con (c) se usaron "
                "para fijar la distancia del tramo contra las mangueras; las demás se miden.")
    ws["A4"].font = Font(italic=True, color=GRIS)
    for c in ("A2", "A3"):
        ws[c].font = neg

    columnas = ["Hora", "Vehículos medidos", "% de los que cruzaron", "Media", "Mediana",
                "Percentil 85", "Desv. estándar", "Livianos · mediana", "Pesados medidos",
                "Pesados · mediana", "Mangueras · mediana", "Mangueras · p85"]
    fila = 6
    for nombre, r in res.items():
        ws.cell(fila, 1, f"{nombre.upper()}  ·  sentido {r['sentido'] or '?'}  ·  "
                         f"tramo de {r['distancia_m']:.2f} m (fijado con {r['distancia_de']})").font = neg
        fila += 1
        for j, t in enumerate(columnas, 1):
            c = ws.cell(fila, j, t)
            c.font, c.fill, c.alignment = cab, relleno_cab, centro
        ws.row_dimensions[fila].height = 32
        fila += 1
        for h in r["horas"]:
            etiqueta = f"{h['hora']}:00-{int(h['hora']) + 1:02d}:00" + (" (c)" if h["calibracion"] else "")
            t, lv, ps = h["todos"], h["livianos"], h["pesados"]
            if h["publica"]:
                valores = [etiqueta, t["n"], h["fraccion"], t["media"], t["p50"], t["p85"], t["desv"],
                           lv.get("p50"), ps["n"], ps.get("p50") if ps["n"] >= 5 else None,
                           h["tubo_p50"], h["tubo_p85"]]
            else:
                valores = [etiqueta, t["n"], h["fraccion"], "no se publica", None, None, None,
                           None, None, None, h["tubo_p50"], h["tubo_p85"]]
            for j, v in enumerate(valores, 1):
                c = ws.cell(fila, j, v)
                c.border = borde
                c.alignment = Alignment(horizontal="center")
                if j == 3:
                    c.number_format = "0%"
                elif isinstance(v, float):
                    c.number_format = "0.0"
                if not h["publica"]:
                    c.fill = PatternFill("solid", fgColor=NO)
                    c.font = Font(color=GRIS)
            fila += 1
        d = r["dia"]
        for j, v in enumerate(["Horas publicadas", d["n"], None, d.get("media"), d.get("p50"),
                               d.get("p85"), d.get("desv")], 1):
            c = ws.cell(fila, j, v)
            c.font, c.fill = neg, PatternFill("solid", fgColor=FONDO)
            c.alignment = Alignment(horizontal="center")
            if isinstance(v, float):
                c.number_format = "0.0"
        fila += 3
    ws.column_dimensions["A"].width = 17
    for j in range(2, len(columnas) + 1):
        ws.column_dimensions[get_column_letter(j)].width = 13
    ws.freeze_panes = "B6"

    wr = wb.create_sheet("REPARTO")
    wr["A1"] = "REPARTO POR RANGO DE VELOCIDAD (horas publicadas)"
    wr["A1"].font = Font(bold=True, size=13, color=TINTA)
    fila = 3
    for j, t in enumerate(["km/h"] + [f"{n} · vehículos" for n in res] + [f"{n} · %" for n in res], 1):
        c = wr.cell(fila, j, t)
        c.font, c.fill, c.alignment = cab, relleno_cab, centro
    wr.row_dimensions[fila].height = 32
    for i, (lo, hi) in enumerate(RANGOS):
        fila += 1
        wr.cell(fila, 1, f"{lo}-{hi}").alignment = Alignment(horizontal="center")
        for j, r in enumerate(res.values()):
            tot = sum(r["reparto"]) or 1
            wr.cell(fila, 2 + j, r["reparto"][i]).alignment = Alignment(horizontal="center")
            c = wr.cell(fila, 2 + len(res) + j, r["reparto"][i] / tot)
            c.number_format, c.alignment = "0.0%", Alignment(horizontal="center")
    for j in range(1, 2 + 2 * len(res)):
        wr.column_dimensions[get_column_letter(j)].width = 24 if j > 1 else 10

    wm = wb.create_sheet("METODO")
    textos = [
        "CÓMO SE MIDIÓ",
        "Como un contador de mangueras: dos líneas a una distancia conocida sobre cada calzada y el tiempo "
        "que tarda cada vehículo de una a otra, con el punto donde la llanta toca el piso.",
        "La muestra son tres minutos de video por hora (xx:10, xx:30 y xx:50); un estudio de velocidad de "
        "punto se hace por muestreo, no sobre todos los vehículos.",
        "",
        "LA DISTANCIA DEL TRAMO",
    ]
    for nombre, r in res.items():
        textos.append(f"{nombre}: {r['distancia_m']:.2f} m, fijada con {r['distancia_de']}"
                      + (f" (aparato serie {r['serie_tubo']})" if r["distancia_de"] == "mangueras" else ""))
    textos += [
        "Con mangueras se fija la distancia con las horas marcadas (c) y se comprueba en todas las demás. "
        "Las dos calzadas se miden en las mismas filas de la imagen, así que sus distancias tienen que "
        "salir parecidas: si un aparato tuviera mal capturada la separación de sus mangueras, no "
        "coincidirían.",
        "Si se mide en el pavimento la distancia entre dos marcas, sustituye a la de las mangueras sin "
        "volver a procesar nada.",
        "",
        "LO QUE NO SE PUBLICA",
        f"Una hora en que se midió a menos del {int(FRACCION_MINIMA * 100)} % de los vehículos que cruzaron "
        "la línea de conteo: de noche, hacia la cámara, los faros parten el recorrido entre las dos líneas y "
        "la velocidad de los pocos medidos no representa al resto. Esas horas salen en gris.",
        "El percentil 15: la cola lenta del reparto medido no es confiable.",
        "La mediana de pesados con menos de 5 medidos en la hora.",
        "",
        "CLASES",
        f"Pesado: autobús, o camión de al menos {MULTIPLO_PESADO} veces el alto del automóvil mediano de su "
        "calzada en la línea de conteo, la misma regla que el conteo. Las motos van en el total, no en "
        "livianos ni pesados.",
    ]
    for i, t in enumerate(textos, 1):
        c = wm.cell(i, 1, t)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        if t.isupper():
            c.font = neg
    wm.column_dimensions["A"].width = 110
    wb.save(ruta)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--proyecto", type=int, required=True)
    ap.add_argument("--tray", required=True, help="carpeta con HH-MM.json")
    ap.add_argument("--calibracion", required=True,
                    help="JSON de calibrar_velocidad.py --salida (líneas y distancia por calzada)")
    ap.add_argument("--distancia", action="append", default=[],
                    help="'Nombre de calzada=metros' medidos en el pavimento; sustituye la calibración")
    ap.add_argument("--salida", required=True, help="Excel del estudio")
    ap.add_argument("--json", default=None, help="también las cifras en JSON")
    a = ap.parse_args()

    with open(a.calibracion, encoding="utf-8") as fh:
        calibracion = json.load(fh)
    distancias = {}
    for par in a.distancia:
        nombre, metros = par.split("=", 1)
        distancias[nombre] = float(metros)

    res = estudio(a.proyecto, a.tray, calibracion, distancias)

    from src.storage import traffic_db
    p = traffic_db.get_project(a.proyecto) or {}
    fecha = traffic_db.get_connection().execute(
        "select min(video_start_time) from video_jobs where project_id=?",
        (a.proyecto,)).fetchone()[0][:10]
    escribir_excel(res, a.salida, p.get("name", f"proyecto {a.proyecto}"), fecha)

    for nombre, r in res.items():
        print(f"\n=== {nombre}  (tramo {r['distancia_m']:.2f} m, {r['distancia_de']}) ===")
        print(f"{'hora':>6} {'n':>4} {'medido':>6} {'media':>6} {'p50':>6} {'p85':>6} "
              f"{'liv p50':>7} {'pes n':>5} {'pes p50':>7} {'tubo p85':>8}")
        for h in r["horas"]:
            t = h["todos"]
            if not h["publica"]:
                print(f"{h['hora']}:00 {t['n']:>4} {100 * h['fraccion']:>5.0f}%   no se publica")
                continue
            ps = h["pesados"]
            print(f"{h['hora']}:00 {t['n']:>4} {100 * h['fraccion']:>5.0f}% {t['media']:>6.1f} "
                  f"{t['p50']:>6.1f} {t['p85']:>6.1f} {h['livianos'].get('p50', 0):>7.1f} "
                  f"{ps['n']:>5} {ps.get('p50', 0) if ps['n'] >= 5 else 0:>7.1f} "
                  f"{h['tubo_p85'] or 0:>8.1f}")
        d = r["dia"]
        if d["n"]:
            print(f"horas publicadas: {d['n']} vehículos, media {d['media']:.1f}, "
                  f"mediana {d['p50']:.1f}, p85 {d['p85']:.1f} km/h")
    if a.json:
        for r in res.values():
            for h in r["horas"]:
                h.pop("kmh", None)
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=1, ensure_ascii=False)
    print(f"\nExcel -> {a.salida}")


if __name__ == "__main__":
    main()
