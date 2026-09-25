"""
Conteo y clasificación por periodo contra el contador de ejes (mangueras).

    python tools/comparar_clases_tubo.py --proyecto 7 \\
        --tubo 9="referencias/aforo_frontal/Miguel madrid clasificatorio Ote-Pte.xls" \\
        --tubo 8="referencias/aforo_frontal/Miguel madrid clasificatorio Pte-Ote.xls" \\
        --salida data/comparacion_tubo.xlsx

Las clases del tubo son por EJES y las nuestras por lo que se ve; no se
corresponden una a una. Se comparan en los grupos donde sí equivalen:

    moto                 Cycle                       MOTO
    livianos             Cars + 2A-4T                A
    unitarios            Buses + 2A-SU + 3A-SU       B + C + TRACTOR
    tractocamión         5A-ST + 6A-ST               T-S
    doble remolque       5A-MT + 6A-MT               T-S-R
    sin equivalente      4A-SU + 4A-ST + Other       —

Por qué así, medido en el aforo frontal (19-sep-2026): el tubo no reconoce
autobuses (3 en doce horas; los manda a 2A-SU), registra el tractor sin
caja como 3A-SU, y sus clases de 4 ejes suben con el volumen de autos
(r = +0.83): son sobre todo dos autos pegados leídos como un vehículo. Por
eso esas van aparte y no se suman a ningún grupo nuestro.

Solo entran los cuartos de hora con el video completo (`cobertura` de
get_interval_counts); uno parcial compararía media medición contra una
entera.
"""

import argparse
import os
import statistics as st
import sys
from collections import defaultdict
from datetime import datetime

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "tools"))

import contador_ejes as ce                 # noqa: E402

GRUPOS = (
    ("moto", ("Cycle",), ("MOTO",)),
    ("livianos", ("Cars", "2A-4T"), ("A",)),
    ("unitarios", ("Buses", "2A-SU", "3A-SU"), ("B", "C", "TRACTOR", "PESADO")),
    ("tractocamión", ("5A-ST", "6A-ST"), ("T-S",)),
    # Aparte: el conteo manual de agosto casi no tuvo doble remolque (T-S-R
    # ~0) y el tubo marca 55 y 92 en doce horas; mezclarlos con el T-S
    # escondia que el tractocamion simple si cuadra (48 contra 54).
    ("doble remolque", ("5A-MT", "6A-MT"), ("T-S-R",)),
    ("sin equivalente", ("4A-SU", "4A-ST", "Other"), ()),
)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--proyecto", type=int, required=True)
    ap.add_argument("--tubo", action="append", required=True,
                    help="'id_de_linea=reporte clasificatorio del tubo', uno por sentido")
    ap.add_argument("--salida", default=None, help="Excel con las tablas por periodo")
    a = ap.parse_args()

    from src.storage import traffic_db
    r = traffic_db.get_interval_counts(a.proyecto, 15)
    lineas = {l["lane_id"]: l for l in r["lanes"]}

    filas_cuarto = []          # (sentido, inicio, grupo, nuestro, tubo)
    for par in a.tubo:
        lid, ruta = par.split("=", 1)
        linea = lineas[int(lid)]
        meta, sec, _ = ce.leer_todo(ruta)
        for iv in linea["intervals"]:
            if (iv.get("cobertura") or 0) < 0.995:
                continue
            t = datetime.strptime(iv["start"], "%Y-%m-%d %H:%M:%S")
            q = sec.get(("clasificatorio", 1), {}).get(t.date().isoformat(), {}) \
                .get(t.hour * 60 + t.minute)
            if q is None:
                continue
            nuestro = {k: v["in"] + v["out"] for k, v in iv["by_vehicle_type"].items()}
            for g, del_tubo, nuestras in GRUPOS:
                filas_cuarto.append((f"{linea['lane_name']} / {meta.get('sentido')}", t, g,
                                     sum(nuestro.get(k, 0) for k in nuestras),
                                     sum(q.get(k, 0) for k in del_tubo)))
            filas_cuarto.append((f"{linea['lane_name']} / {meta.get('sentido')}", t, "TOTAL",
                                 sum(nuestro.values()), sum(q.values())))

    sentidos = sorted({f[0] for f in filas_cuarto})
    grupos = [g for g, _, _ in GRUPOS] + ["TOTAL"]
    por_hora = defaultdict(lambda: [0, 0])
    for s, t, g, n, tb in filas_cuarto:
        por_hora[(s, t.hour, g)][0] += n
        por_hora[(s, t.hour, g)][1] += tb

    for s in sentidos:
        horas = sorted({h for (s2, h, _) in por_hora if s2 == s})
        print(f"\n=== {s}   (nuestro / tubo por hora)")
        print("hora " + "".join(f"{g:>20}" for g in grupos))
        for h in horas:
            print(f"{h:02d}   " + "".join(
                f"{por_hora[(s, h, g)][0]:>9}/{int(por_hora[(s, h, g)][1]):<10}" for g in grupos))
        tot = {g: [sum(por_hora[(s, h, g)][i] for h in horas) for i in (0, 1)] for g in grupos}
        print("suma " + "".join(f"{tot[g][0]:>9}/{int(tot[g][1]):<10}" for g in grupos))
        print("razón" + "".join(f"{(tot[g][0] / tot[g][1] if tot[g][1] else 0):>19.2f}x"
                                for g in grupos))
        cuartos = [(n, tb) for s2, _, g, n, tb in filas_cuarto if s2 == s and g == "TOTAL"]
        razones = sorted(n / tb for n, tb in cuartos if tb)
        r_ = st.correlation([c[0] for c in cuartos], [c[1] for c in cuartos])
        print(f"por cuarto de hora ({len(cuartos)}): perfil r = {r_:+.2f}; razón mediana "
              f"{st.median(razones):.2f}, de {razones[len(razones) // 10]:.2f} a "
              f"{razones[-1 - len(razones) // 10]:.2f} (percentiles 10–90)")

    if a.salida:
        from openpyxl import Workbook
        from openpyxl.styles import Font
        wb = Workbook()
        ws = wb.active
        ws.title = "POR HORA"
        ws.append(["sentido", "hora"] + [f"{g} {lado}" for g in grupos
                                         for lado in ("nuestro", "tubo", "razón")])
        for c in ws[1]:
            c.font = Font(bold=True)
        for s in sentidos:
            for h in sorted({h for (s2, h, _) in por_hora if s2 == s}):
                fila = [s, f"{h:02d}:00"]
                for g in grupos:
                    n, tb = por_hora[(s, h, g)]
                    fila += [n, int(tb), round(n / tb, 2) if tb else None]
                ws.append(fila)
        ws2 = wb.create_sheet("POR CUARTO")
        ws2.append(["sentido", "inicio", "grupo", "nuestro", "tubo", "razón"])
        for c in ws2[1]:
            c.font = Font(bold=True)
        for s, t, g, n, tb in filas_cuarto:
            ws2.append([s, t.strftime("%H:%M"), g, n, int(tb), round(n / tb, 2) if tb else None])
        ws3 = wb.create_sheet("GRUPOS")
        for linea in __doc__.strip().splitlines():
            ws3.append([linea])
        wb.save(a.salida)
        print(f"\nExcel: {a.salida}")


if __name__ == "__main__":
    main()
