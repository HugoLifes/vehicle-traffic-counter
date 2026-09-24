"""
¿La hora de los videos es la hora real? Se comprueba contra el sol.

En un video hay DOS relojes que pueden discrepar: el nombre del archivo, que
pone la grabadora, y la leyenda impresa en la imagen. En el aforo frontal de
Cd. Juarez (19-sep-2026) discrepan, y mucho:

    archivo 12:24 -> leyenda 2026-09-19 12:24:00    (iguales al segundo)
    archivo 12:26 -> leyenda 2026-08-28 17:21:00    (22 dias atras, +4 h 55 min)
    archivo 23:59 -> leyenda 2026-08-29 04:54:00    (el mismo desfase, constante)

A las 12:25 la leyenda salto, y los nombres de archivo siguieron corriendo
sin brincos. Con dos relojes en desacuerdo hace falta un tercero que no
dependa de la grabadora, y el unico que viene dentro del video es EL SOL.

La camara cambia a vision nocturna (infrarrojo, en blanco y negro) cuando
oscurece. Ese cambio se ve en el color: la saturacion cae casi a cero de un
minuto al siguiente. Se busca en que minuto, segun cada reloj, pasa eso, y
se compara con la puesta de sol y el fin del crepusculo civil calculados
para el lugar y el dia (formulas de la NOAA). El reloj correcto es el que
pone el cambio a nocturno justo despues de la puesta de sol.

Da una exactitud de minutos, no de segundos: la camara no cambia a nocturno
en un instante astronomico exacto sino con cierta luz, y esa luz depende de
las nubes. Alcanza para lo que importa: descubrir un reloj corrido horas, o
en otra zona horaria, que es justo lo que ningun otro chequeo del proyecto
puede ver (si el reloj de la grabadora esta mal, el nombre del archivo y
todo lo que se calcula con el estan mal juntos).

    python tools/revisar_reloj.py --proyecto 7 --desde 17 --hasta 21
    python tools/revisar_reloj.py --proyecto 7 --hoja-leyenda data/leyenda.png

Ciudad Juarez usa horario de montana con cambio de verano como EE. UU.:
en septiembre es UTC-6 (`--utc -6`, el valor por omision).
"""

import argparse
import datetime as dt
import math
import os
import sys

import cv2
import numpy as np

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from src.storage import traffic_db   # noqa: E402

# Centro de Ciudad Juarez. Un kilometro de error mueve la puesta de sol unos
# 2 s, asi que para esto sobra.
LAT, LON = 31.69, -106.42

# Saturacion media por debajo de la cual el cuadro esta en blanco y negro.
# De dia la escena da 60-110; en infrarrojo, un digito.
SATURACION_NOCHE = 15.0

# Leyenda de la hora, abajo a la derecha del cuadro de 2560x1440.
LEYENDA = (1960, 2520, 1345, 1425)     # x0, x1, y0, y1


def sol(fecha, lat, lon, utc, cenit):
    """Minuto del dia (hora local) en que el sol cruza el cenit dado al
    ponerse. 90.833 = puesta de sol; 96 = fin del crepusculo civil.

    Formulas del NOAA Global Monitoring Laboratory (ecuacion del tiempo y
    declinacion por serie de Fourier), buenas a un minuto.
    """
    n = fecha.timetuple().tm_yday
    g = 2 * math.pi / 365 * (n - 1)
    ecuacion = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                         - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g)
            - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
            - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    phi = math.radians(lat)
    ha = math.degrees(math.acos(math.cos(math.radians(cenit)) /
                                (math.cos(phi) * math.cos(decl))
                                - math.tan(phi) * math.tan(decl)))
    utc_min = 720 - 4 * (lon - ha) - ecuacion
    return (utc_min + 60 * utc) % 1440


def medir(ruta):
    """(saturacion media, brillo medio) del primer cuadro, o None."""
    cap = cv2.VideoCapture(ruta)
    ok, f = cap.read()
    cap.release()
    if not ok:
        return None
    hsv = cv2.cvtColor(cv2.resize(f, (640, 360)), cv2.COLOR_BGR2HSV)
    return float(hsv[..., 1].mean()), float(hsv[..., 2].mean())


def hhmm(minuto):
    minuto = round(minuto) % 1440
    return f"{minuto // 60:02d}:{minuto % 60:02d}"


def hoja_leyenda(videos, salida):
    """Recorte de la leyenda al principio y al final de cada video, junto a
    la hora del archivo, para leerla a ojo. No se usa OCR a proposito: son
    quince renglones y leerlos toma un minuto; un OCR que se equivoque en un
    digito cambiaria la conclusion."""
    x0, x1, y0, y1 = LEYENDA
    filas = []
    for hora, ruta in videos:
        cap = cv2.VideoCapture(ruta)
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        celdas = []
        for cuadro in (0, max(0, n - 1)):
            cap.set(cv2.CAP_PROP_POS_FRAMES, cuadro)
            ok, f = cap.read()
            celdas.append(f[y0:y1, x0:x1].copy() if ok
                          else np.zeros((y1 - y0, x1 - x0, 3), np.uint8))
        cap.release()
        rotulo = np.full((y1 - y0, 330, 3), 30, np.uint8)
        cv2.putText(rotulo, f"archivo {hora}", (10, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 255, 255), 2)
        filas.append(np.hstack([rotulo, celdas[0],
                                np.full((y1 - y0, 12, 3), 90, np.uint8), celdas[1]]))
    cv2.imwrite(salida, np.vstack(filas))
    print(f"hoja de la leyenda -> {salida}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--proyecto", type=int, required=True)
    ap.add_argument("--desde", type=int, default=17, help="hora del archivo desde la que medir")
    ap.add_argument("--hasta", type=int, default=21, help="hora del archivo hasta la que medir")
    ap.add_argument("--lat", type=float, default=LAT)
    ap.add_argument("--lon", type=float, default=LON)
    ap.add_argument("--utc", type=float, default=-6.0,
                    help="desfase de la hora local respecto a UTC (Juarez en sep: -6)")
    ap.add_argument("--hoja-leyenda", default=None,
                    help="ademas, guardar la hoja con la leyenda de un video por hora")
    a = ap.parse_args()

    conn = traffic_db.get_connection()
    jobs = [dict(r) for r in conn.execute(
        """SELECT video_start_time, stored_path FROM video_jobs
           WHERE project_id = ? AND video_start_time IS NOT NULL
           ORDER BY video_start_time""", (a.proyecto,))]
    if not jobs:
        sys.exit("El proyecto no tiene videos con hora de inicio")
    fecha = dt.date.fromisoformat(jobs[0]["video_start_time"][:10])

    if a.hoja_leyenda:
        por_hora = {}
        for j in jobs:
            por_hora.setdefault(j["video_start_time"][11:13], j)
        hoja_leyenda([(j["video_start_time"][11:16], j["stored_path"])
                      for j in por_hora.values()], a.hoja_leyenda)

    puesta = sol(fecha, a.lat, a.lon, a.utc, 90.833)
    civil = sol(fecha, a.lat, a.lon, a.utc, 96.0)
    print(f"{fecha}, lat {a.lat} lon {a.lon}, UTC{a.utc:+g}:")
    print(f"  puesta de sol                 {hhmm(puesta)}")
    print(f"  fin del crepusculo civil      {hhmm(civil)}")

    print(f"\n{'archivo':>8} {'saturacion':>11} {'brillo':>7}")
    serie = []
    for j in jobs:
        h = int(j["video_start_time"][11:13])
        if not a.desde <= h < a.hasta:
            continue
        m = medir(j["stored_path"])
        if m is None:
            continue
        minuto = h * 60 + int(j["video_start_time"][14:16])
        serie.append((minuto, *m))
        if minuto % 5 == 0:
            print(f"{hhmm(minuto):>8} {m[0]:>11.1f} {m[1]:>7.1f}")
    if not serie:
        sys.exit("No hay videos en esa franja")

    # Primer minuto a partir del cual el cuadro queda en blanco y negro y
    # ya no regresa al color: un nublado puede bajar la saturacion un rato.
    cambio = None
    for i, (minuto, s, _) in enumerate(serie):
        if s < SATURACION_NOCHE and all(x[1] < SATURACION_NOCHE for x in serie[i:]):
            cambio = minuto
            break
    print()
    if cambio is None:
        print("La camara no cambia a nocturno en la franja medida; ampliala.")
        return
    print(f"La camara cambia a nocturno a las {hhmm(cambio)} segun el ARCHIVO.")
    antes, despues = cambio - puesta, cambio - civil
    print(f"  {antes:+.0f} min respecto a la puesta de sol, "
          f"{despues:+.0f} min respecto al fin del crepusculo civil.")
    if -20 <= antes and despues <= 30:
        print("  => El reloj del ARCHIVO es la hora real: la camara pasa a "
              "nocturno entre la\n     puesta de sol y un rato despues del "
              "crepusculo, que es cuando le toca.")
    else:
        print("  => NO cuadra con el sol. El reloj de la grabadora esta "
              f"corrido del orden de\n     {antes / 60:+.1f} h, o en otra zona "
              "horaria. No usar las horas de este video sin\n     corregirlas.")


if __name__ == "__main__":
    main()
