"""
Volumen por brazo de un aforo direccional YA CONTADO, con un cordón de líneas
probado sobre los recorridos guardados: sin volver a detectar.

Para qué: en una cámara donde el vehículo se parte en pedazos (lejos, a
640x360, tapado por un poste o un camellón) la matriz origen-destino deja la
mayoría sin decidir, pero cada pedazo que cruza una línea sí dice que por ahí
pasó un vehículo y en qué sentido. Con una línea en cada brazo, orientada para
que "entrada" sea entrar al cruce, la suma de entradas por cuarto de hora es
el volumen del cruce, y de ahí sale la hora de máxima demanda.

El criterio de cruce es el de counter.py (producto cruzado del movimiento
contra la línea; positivo = entrada). Solo ve los recorridos que la
plataforma guardó (`movimientos.recorrido`): los que tocaron algún acceso.
Por eso cada línea va DENTRO de su acceso.

    python tools/cordon_od.py --proyecto 26 \\
        --linea "Oeste=290,165,290,200" --linea "Este=420,200,420,165" \\
        --linea "Camara=400,300,640,285"

Comprobación que imprime: entradas contra salidas por cuarto. En un cordón
cerrado tienen que parecerse; si una línea da muchas más salidas que
entradas (o al revés), sus recorridos mueren antes de llegar a ella y su
cifra no vale. En Gómez Morín (11-oct-2026) la línea Este salió así: el
volumen se apoya en la Oeste, que lleva el flujo dominante.
"""

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.storage import traffic_db  # noqa: E402


def _lado(o, u, v):
    return (u[0] - o[0]) * (v[1] - o[1]) - (u[1] - o[1]) * (v[0] - o[0])


def cruza(a, b, p, q) -> bool:
    return _lado(a, b, p) * _lado(a, b, q) < 0 and _lado(p, q, a) * _lado(p, q, b) < 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--proyecto', type=int, required=True)
    ap.add_argument('--linea', action='append', required=True,
                    help='Nombre=x1,y1,x2,y2 en pixeles del video; entrar al cruce = producto cruzado positivo')
    ap.add_argument('--minutos', type=int, default=15)
    args = ap.parse_args()

    lineas = {}
    for texto in args.linea:
        nombre, coords = texto.split('=', 1)
        x1, y1, x2, y2 = (float(v) for v in coords.split(','))
        lineas[nombre] = ((x1, y1), (x2, y2))

    db = sqlite3.connect(str(traffic_db.DB_PATH))
    filas = db.execute(
        """SELECT v.video_start_time, m.recorrido FROM movimientos m
             JOIN video_jobs v ON v.id = m.job_id
            WHERE m.project_id = ? AND m.recorrido IS NOT NULL AND v.video_start_time IS NOT NULL""",
        (args.proyecto,)).fetchall()
    if not filas:
        sys.exit("Ese proyecto no tiene recorridos guardados (¿es direccional y ya se contó?).")

    entradas = defaultdict(lambda: defaultdict(int))
    salidas = defaultdict(lambda: defaultdict(int))
    for inicio, texto in filas:
        r = json.loads(texto)
        t0 = datetime.fromisoformat(inicio)
        puntos = list(zip(r['x'], r['y'], r['t']))
        for nombre, (a, b) in lineas.items():
            for (x1, y1, s1), (x2, y2, s2) in zip(puntos, puntos[1:]):
                if not cruza(a, b, (x1, y1), (x2, y2)):
                    continue
                signo = (x2 - x1) * (b[1] - a[1]) - (y2 - y1) * (b[0] - a[0])
                hora = t0 + timedelta(seconds=(s1 + s2) / 2)
                cuarto = hora.replace(minute=hora.minute // args.minutos * args.minutos,
                                      second=0, microsecond=0)
                (entradas if signo > 0 else salidas)[cuarto][nombre] += 1
                break   # un recorrido cruza cada línea una vez

    cuartos = sorted(set(entradas) | set(salidas))
    print(f"{len(filas)} recorridos. Entradas por línea, total de entradas y de salidas:")
    print("intervalo        " + "  ".join(f"{n:>8}" for n in lineas) + "   entradas  salidas")
    total = {}
    for c in cuartos:
        total[c] = sum(entradas[c].values())
        print(c.strftime('%Y-%m-%d %H:%M') + "  " + "  ".join(f"{entradas[c][n]:>8}" for n in lineas)
              + f"   {total[c]:>8}  {sum(salidas[c].values()):>7}")

    paso = timedelta(minutes=args.minutos)
    n = 60 // args.minutos
    for dia in sorted({c.date() for c in cuartos}):
        cs = [c for c in cuartos if c.date() == dia]
        ventanas = []
        for i in range(len(cs) - n + 1):
            w = cs[i:i + n]
            if w[-1] - w[0] != paso * (n - 1):
                continue   # falta un intervalo: no es una hora seguida
            vol = sum(total[c] for c in w)
            pico = max(total[c] for c in w)
            ventanas.append((vol, w[0], vol / (n * pico) if pico else 0))
        if ventanas:
            vol, ini, fhp = max(ventanas)
            print(f"{dia}: hora de máxima demanda {ini:%H:%M}-{ini + paso * n:%H:%M}, "
                  f"{vol} entradas, FHP {fhp:.2f}")


if __name__ == '__main__':
    main()
