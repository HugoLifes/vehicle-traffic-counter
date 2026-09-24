"""
Calibra la velocidad por tramo contra el contador de ejes, y de paso pone a
prueba AL CONTADOR.

    python tools/calibrar_velocidad.py --proyecto 7 --tray data/nuevos/vel/tray \\
        --tubo "Calzada alejandose=referencias/aforo_frontal/Miguel madrid clasificatorio Ote-Pte.xls" \\
        --tubo "Calzada hacia la camara=referencias/aforo_frontal/Miguel madrid clasificatorio Pte-Ote.xls" \\
        --filas 960 820 --calibrar 12 13 14

La velocidad por tramo necesita la distancia real entre las dos lineas, y del
aforo frontal nadie la midio en campo. Se hace lo que ya se hizo con la
camara lateral: se FIJA la distancia con unas horas contra el tubo y se MIDEN
las demas (perfil por hora, percentil 85, reparto por rangos).

Lo nuevo de esta camara es una prueba que la lateral no permitia. La camara
mira A LO LARGO de la via, asi que una misma FILA de la imagen esta a la misma
distancia real en las dos calzadas (piso plano, camara sin giro). Si las dos
lineas del tramo se ponen en las mismas filas para los dos sentidos, las dos
distancias calibradas tienen que salir casi iguales. Si no, al menos uno de
los dos tubos mide mal la velocidad: con la separacion de mangueras mal
capturada, todas las velocidades de un sentido salen escaladas por el mismo
factor y el aparato no avisa. En agosto el 19079 dio 93 km/h de media en una
avenida urbana por eso.

Las muestras son videos de un minuto (HH-MM.json, de extraer_trayectorias.py)
y se comparan contra el cuarto de hora del tubo que los contiene.
"""

import argparse
import glob
import json
import os
import statistics as st
import sys
from collections import defaultdict

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "tools"))

import contador_ejes as ce                                   # noqa: E402
from src.engine.velocidad import MedidorVelocidad, percentil  # noqa: E402


def cortes_en_fila(poligono, y):
    """x donde la fila y corta el borde del poligono (min, max)."""
    xs = []
    n = len(poligono)
    for i in range(n):
        (x1, y1), (x2, y2) = poligono[i], poligono[(i + 1) % n]
        if (y1 - y) * (y2 - y) <= 0 and y1 != y2:
            xs.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
    return (min(xs), max(xs)) if len(xs) >= 2 else None


def dentro(poligono, x, y):
    c = False
    n = len(poligono)
    for i in range(n):
        (x1, y1), (x2, y2) = poligono[i], poligono[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            c = not c
    return c


def tiempos_de_muestra(ruta, poligono, linea_a, linea_b):
    """Tiempos de paso (s) por el tramo de los rastros de UNA calzada.

    La calzada se decide por el punto de apoyo (centro del borde inferior),
    igual que el contador y las zonas de produccion."""
    with open(ruta, encoding="utf-8") as fh:
        d = json.load(fh)
    por_cuadro = defaultdict(list)
    for tid, r in d["rastros"].items():
        for c, x1, y1, x2, y2, _conf in r["p"]:
            if dentro(poligono, (x1 + x2) / 2, y2):
                por_cuadro[c].append({"id": int(tid), "track_id": int(tid),
                                      "bbox": (x1, y1, x2, y2)})
    # Distancia 1 m: el resultado es el tiempo; la distancia se aplica luego.
    med = MedidorVelocidad(linea_a, linea_b, 1.0, d["fps"])
    tiempos = []
    for c in sorted(por_cuadro):
        for m in med.observar(c, por_cuadro[c]):
            tiempos.append(m["segundos"])
    # Cuantos cruzaron la linea de conteo: sin esto, una hora donde solo se
    # alcanza a medir a unos pocos se lee igual que una donde se mide a casi
    # todos. De noche, hacia la camara, los faros parten el rastro entre las
    # dos lineas y se median 6-19 vehiculos por muestra contra 45-92 de dia.
    ya = linea_a[0][1]
    cruces = 0
    for r in d["rastros"].values():
        ys = [y2 for _, x1, _, x2, y2, _ in r["p"] if dentro(poligono, (x1 + x2) / 2, y2)]
        cruces += any((a - ya) * (b - ya) <= 0 and a != b for a, b in zip(ys, ys[1:]))
    return tiempos, cruces


def percentil_rangos(hist, q):
    n = sum(hist)
    obj, acc = q * n, 0.0
    for (lo, hi), c in zip(ce.RANGOS_KMH, hist):
        if c and acc + c >= obj:
            return lo + (hi - lo) * (obj - acc) / c
        acc += c
    return ce.RANGOS_KMH[-1][1]


def a_rangos(kmh):
    h = [0] * len(ce.RANGOS_KMH)
    for v in kmh:
        for i, (_, hi) in enumerate(ce.RANGOS_KMH):
            if v <= hi + 0.05:
                h[i] += 1
                break
    return h


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--proyecto", type=int, required=True)
    ap.add_argument("--tray", required=True, help="carpeta con HH-MM.json")
    ap.add_argument("--tubo", action="append", required=True,
                    help="'Nombre de calzada=reporte del tubo' (uno por sentido)")
    ap.add_argument("--filas", type=float, nargs=2, default=(960, 820),
                    help="filas de la imagen de las dos lineas del tramo")
    ap.add_argument("--calibrar", nargs="+", default=["12", "13", "14"],
                    help="horas con que se fija la distancia; el resto se mide")
    ap.add_argument("--salida", default=None)
    a = ap.parse_args()

    from src.storage import traffic_db
    from src.engine.zones import load_zones
    zonas = {z["name"]: z for z in load_zones(a.proyecto)}
    fecha = traffic_db.get_connection().execute(
        "select min(video_start_time) from video_jobs where project_id=?",
        (a.proyecto,)).fetchone()[0][:10]

    muestras = sorted(glob.glob(os.path.join(a.tray, "*.json")))
    if not muestras:
        sys.exit(f"No hay recorridos en {a.tray}")
    ya, yb = a.filas
    resultados = {}
    for par in a.tubo:
        nombre, ruta = par.split("=", 1)
        if nombre not in zonas:
            sys.exit(f"No existe la calzada '{nombre}' en el proyecto {a.proyecto}")
        pol = [tuple(p) for p in zonas[nombre]["points"]]
        ca, cb = cortes_en_fila(pol, ya), cortes_en_fila(pol, yb)
        if not ca or not cb:
            sys.exit(f"Las filas {ya} y {yb} no cortan la calzada '{nombre}'")
        la = [(ca[0], ya), (ca[1], ya)]
        lb = [(cb[0], yb), (cb[1], yb)]

        meta, sec, _ = ce.leer_todo(ruta)
        vel = sec.get(("velocidad", 1), {}).get(fecha)
        if not vel:
            sys.exit(f"{ruta} no trae velocidades del {fecha}")

        por_hora = defaultdict(list)
        cruces_hora = defaultdict(int)
        tubo_hora = defaultdict(lambda: [0] * len(ce.RANGOS_KMH))
        for m in muestras:
            base = os.path.splitext(os.path.basename(m))[0]
            hh, mm = base.split("-")[:2]
            t, n_cruces = tiempos_de_muestra(m, pol, la, lb)
            por_hora[hh] += t
            cruces_hora[hh] += n_cruces
            cuarto = int(hh) * 60 + (int(mm) // 15) * 15
            if cuarto in vel:
                for i in range(len(ce.RANGOS_KMH)):
                    tubo_hora[hh][i] += vel[cuarto][i]

        cal = [h for h in a.calibrar if por_hora.get(h) and sum(tubo_hora[h])]
        inv = sorted(1.0 / t for h in cal for t in por_hora[h] if t > 0)
        ref = [sum(tubo_hora[h][i] for h in cal) for i in range(len(ce.RANGOS_KMH))]
        distancia = percentil_rangos(ref, 0.5) / 3.6 / percentil(inv, 50)

        print(f"\n=== {nombre}  (tubo {meta.get('sentido')}, serie {meta.get('serie')}) ===")
        print(f"lineas del tramo: fila {ya:.0f} de x {ca[0]:.0f} a {ca[1]:.0f}; "
              f"fila {yb:.0f} de x {cb[0]:.0f} a {cb[1]:.0f}")
        print(f"distancia implicita del tramo: {distancia:.2f} m (calibrada con {', '.join(cal)} h)")
        print(f"{'hora':>5}   {'n':>4} {'medido':>6} {'p50':>6} {'p85':>6}   {'tubo n':>6} {'p50':>6} {'p85':>6}   {'dif p85':>7}")
        filas = []
        for h in sorted(por_hora):
            kmh = sorted(distancia / t * 3.6 for t in por_hora[h] if t > 0)
            kmh = [v for v in kmh if 3 <= v <= 160]
            if not kmh or not sum(tubo_hora[h]):
                continue
            n50, n85 = percentil(kmh, 50), percentil(kmh, 85)
            t50, t85 = percentil_rangos(tubo_hora[h], .5), percentil_rangos(tubo_hora[h], .85)
            marca = "c" if h in cal else " "
            medido = len(kmh) / max(1, cruces_hora[h])
            print(f"{h}:xx {marca} {len(kmh):>4} {100 * medido:>5.0f}% {n50:>6.1f} {n85:>6.1f}   {int(sum(tubo_hora[h])):>6} "
                  f"{t50:>6.1f} {t85:>6.1f}   {n85 - t85:>+7.1f}")
            filas.append({"hora": h, "cal": h in cal, "n": len(kmh), "medido": medido,
                          "p50": n50, "p85": n85,
                          "tubo_p50": t50, "tubo_p85": t85, "rangos": a_rangos(kmh),
                          "rangos_tubo": tubo_hora[h]})
        prueba = [f for f in filas if not f["cal"]]
        if len(prueba) >= 3:
            err = [f["p85"] - f["tubo_p85"] for f in prueba]
            r = st.correlation([f["p50"] for f in prueba], [f["tubo_p50"] for f in prueba]) \
                if len({f["tubo_p50"] for f in prueba}) > 1 else float("nan")
            print(f"horas de prueba {len(prueba)}: error del p85 medio {st.fmean(err):+.1f}, "
                  f"absoluto medio {st.fmean(abs(e) for e in err):.1f} km/h; perfil de la "
                  f"mediana r = {r:+.2f}")
            nt = [sum(f["rangos"][i] for f in prueba) for i in range(len(ce.RANGOS_KMH))]
            tt = [sum(f["rangos_tubo"][i] for f in prueba) for i in range(len(ce.RANGOS_KMH))]
            print("reparto en las horas de prueba (nuestro / tubo):")
            for i in range(1, 8):
                lo, hi = ce.RANGOS_KMH[i]
                print(f"  {lo:5.1f}-{hi:5.1f} km/h  {100 * nt[i] / sum(nt):5.1f} %  "
                      f"{100 * tt[i] / sum(tt):5.1f} %")
        resultados[nombre] = {"distancia_m": distancia, "sentido": meta.get("sentido"),
                              "serie": meta.get("serie"), "lineas": [la, lb], "horas": filas}

    if len(resultados) == 2:
        (n1, r1), (n2, r2) = resultados.items()
        razon = r1["distancia_m"] / r2["distancia_m"]
        print(f"\n=== La prueba del contador ===")
        print(f"Mismas filas en las dos calzadas -> la misma distancia real en el piso.")
        print(f"  {n1} (tubo {r1['sentido']}, serie {r1['serie']}): {r1['distancia_m']:.2f} m")
        print(f"  {n2} (tubo {r2['sentido']}, serie {r2['serie']}): {r2['distancia_m']:.2f} m")
        print(f"  razon: {razon:.2f}")
        if abs(razon - 1) > 0.10:
            print("  NO coinciden: al menos uno de los dos tubos mide la velocidad escalada.")
            print("  (Tambien puede ser un giro de la camara; mirar que el horizonte este")
            print("   horizontal antes de culpar al tubo.)")
        else:
            print("  Coinciden: los dos tubos miden velocidades compatibles entre si.")
    if a.salida:
        with open(a.salida, "w", encoding="utf-8") as fh:
            json.dump(resultados, fh, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
