"""
Mide la velocidad por tramo sobre recorridos ya extraídos y la contrasta
contra el contador de ejes (RoadRunner) del mismo día.

    python tools/velocidad_contra_tubo.py --tray data/velocidad/tray \
        --tubo referencias/aforo_real/miguel_de_la_madrid_pte_ote.xls --zona 3

Los recorridos salen de `extraer_trayectorias.py` (uno por hora, nombrados
hHH.json). Cada vehículo se mide con el mismo `MedidorVelocidad` que usa
producción, viendo solo lo que está sobre su calzada, como el procesador.

El problema de validar aquí: no se sabe la distancia real entre las dos
líneas, porque nadie la midió en campo y no se conoce el punto exacto de la
cámara para medirla en el mapa. Así que la herramienta separa dos preguntas:

1. ¿La medición sigue a la velocidad real? Se fija la distancia con UNAS
   horas (las de calibración) y se miden LAS DEMÁS: perfil por hora,
   percentil 85 y reparto por rangos contra el tubo. Es la misma validación
   con holdout que se usó para la clasificación.
2. ¿Qué distancia implica? La que resulta de la calibración, para compararla
   contra lo que se mida en campo cuando se pueda.

Lo que NO valida: la distancia que el usuario capture. Un error ahí escala
todas las velocidades por el mismo factor (el tubo ote-pte de este mismo
aforo lo demuestra: 93 km/h de media en una avenida urbana).
"""

import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.engine.velocidad import MedidorVelocidad, percentil, resumen  # noqa: E402
from src.engine.zones import zone_for_bbox  # noqa: E402

# Las calzadas del proyecto 2 del Jetson (Cd. Juárez), tal como están en la base.
ZONAS_JUAREZ = [
    {'id': 3, 'name': 'Calzada poniente', 'kind': 'calzada',
     'points': [[0, 165], [640, 184], [640, 199], [0, 180]]},
    {'id': 4, 'name': 'Calzada oriente', 'kind': 'calzada',
     'points': [[0, 180], [640, 199], [640, 270], [0, 196]]},
]

# Rangos del contador de ejes (km/h). El último, "Other", queda fuera.
BORDES_TUBO = [0, 32.15, 40.15, 48.15, 56.25, 64.25, 72.35, 80.35, 88.45, 96.45,
               104.55, 112.55, 120.65, 128.65, 136.75, 144.75]


def leer_tubo(ruta):
    """Rangos de velocidad por cuarto de hora: {'HH:MM': [16 conteos]}."""
    import warnings
    warnings.filterwarnings('ignore')
    import pandas as pd
    df = pd.read_excel(ruta, header=None)
    hora = re.compile(r'^\d{2}:\d{2}:\d{2}$')
    tabla = {}
    for fila in df.itertuples(index=False):
        vals = [v for v in fila if str(v) != 'nan']
        for i, v in enumerate(vals):
            if isinstance(v, str) and hora.match(v) or (hasattr(v, 'hour') and not hasattr(v, 'year')):
                resto = vals[i + 1:]
                # La tabla de velocidad trae 16 rangos + total; la de clases, 13 + total.
                if len(resto) == 17 and all(isinstance(x, (int, float)) for x in resto):
                    clave = str(v)[:5]
                    tabla[clave] = [int(x) for x in resto[:16]]
                break
    return tabla


def stats_rangos(conteos):
    """Media y percentiles desde los rangos, interpolando dentro de cada uno."""
    total = sum(conteos[:15])
    if total == 0:
        return None
    medios = [(BORDES_TUBO[i] + BORDES_TUBO[i + 1]) / 2 for i in range(15)]
    medios[0] = 28.0  # el primer rango arranca en 0; casi nadie circula a menos de 25
    media = sum(c * m for c, m in zip(conteos, medios)) / total

    def pct(q):
        meta = total * q / 100.0
        acum = 0
        for i in range(15):
            if acum + conteos[i] >= meta and conteos[i] > 0:
                f = (meta - acum) / conteos[i]
                return BORDES_TUBO[i] + f * (BORDES_TUBO[i + 1] - BORDES_TUBO[i])
            acum += conteos[i]
        return BORDES_TUBO[15]
    return {'n': total, 'media': media, 'p15': pct(15), 'p50': pct(50), 'p85': pct(85)}


def a_rangos(kmh):
    c = [0] * 16
    for v in kmh:
        for i in range(15):
            if v < BORDES_TUBO[i + 1]:
                c[i] += 1
                break
        else:
            c[15] += 1
    return c


def medir_hora(ruta, zona, linea_a, linea_b):
    """Tiempos de paso (s) por el tramo de los rastros de una calzada."""
    with open(ruta, encoding='utf-8') as fh:
        d = json.load(fh)
    por_cuadro = defaultdict(list)
    for tid, r in d['rastros'].items():
        for c, x1, y1, x2, y2, _conf in r['p']:
            por_cuadro[c].append({'id': int(tid), 'bbox': (x1, y1, x2, y2)})
    # Distancia 1: el resultado queda en "tramos por segundo" y la distancia
    # real se aplica después.
    med = MedidorVelocidad(linea_a, linea_b, 1.0, d['fps'])
    tiempos = []
    for c in sorted(por_cuadro):
        vistos = [t for t in por_cuadro[c] if zone_for_bbox(ZONAS_JUAREZ, t['bbox']) == zona]
        for m in med.observar(c, vistos):
            tiempos.append(m['segundos'])
    # Descartados por "imposibles" con distancia 1 m no significan nada; se
    # filtra al final, ya con la distancia real.
    return tiempos


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tray', default='data/velocidad/tray')
    ap.add_argument('--tubo', required=True)
    ap.add_argument('--zona', type=int, required=True, help='id de la calzada')
    ap.add_argument('--a', type=float, nargs=4, required=True, metavar=('X1', 'Y1', 'X2', 'Y2'))
    ap.add_argument('--b', type=float, nargs=4, required=True, metavar=('X1', 'Y1', 'X2', 'Y2'))
    ap.add_argument('--calibrar', nargs='+', default=['07', '08', '09'],
                    help='horas con que se fija la distancia; el resto se mide')
    ap.add_argument('--salida', default=None, help='JSON con los resultados')
    args = ap.parse_args()

    tubo = leer_tubo(args.tubo)
    la = [(args.a[0], args.a[1]), (args.a[2], args.a[3])]
    lb = [(args.b[0], args.b[1]), (args.b[2], args.b[3])]

    tiempos = {}
    for ruta in sorted(glob.glob(os.path.join(args.tray, 'h*.json'))):
        h = os.path.basename(ruta)[1:3]
        tiempos[h] = medir_hora(ruta, args.zona, la, lb)
    if not tiempos:
        sys.exit('No hay recorridos en ' + args.tray)

    # El video de cada hora empieza en HH:00 y dura 10 minutos: se compara
    # con el cuarto de hora HH:00 del tubo.
    ref = {h: stats_rangos(tubo[f'{h}:00']) for h in tiempos if f'{h}:00' in tubo}

    # Distancia que hace coincidir la MEDIANA en las horas de calibración.
    # Mediana y no media: la media la mueven los pocos rastros mal armados.
    cal = [h for h in args.calibrar if h in tiempos and ref.get(h)]
    inv = sorted(1.0 / t for h in cal for t in tiempos[h])
    ref_cal = stats_rangos([sum(tubo[f'{h}:00'][i] for h in cal) for i in range(16)])
    distancia = ref_cal['p50'] / 3.6 / percentil(inv, 50)

    print(f'Calzada {args.zona}. Distancia implícita del tramo: {distancia:.1f} m '
          f'(calibrada con {", ".join(cal)})\n')
    print(f'{"hora":>5} {"":1} {"n":>4} {"media":>6} {"p50":>6} {"p85":>6}   '
          f'{"tubo n":>6} {"media":>6} {"p50":>6} {"p85":>6}   {"dif p85":>7}')
    filas = []
    for h in sorted(tiempos):
        kmh = [distancia / t * 3.6 for t in tiempos[h]]
        kmh = [v for v in kmh if 3 <= v <= 160]
        nuestro = resumen(kmh)
        r = ref.get(h)
        marca = 'c' if h in cal else ' '
        if nuestro['n'] and r:
            print(f'{h}:00 {marca} {nuestro["n"]:>4} {nuestro["media"]:>6.1f} {nuestro["p50"]:>6.1f} '
                  f'{nuestro["p85"]:>6.1f}   {r["n"]:>6} {r["media"]:>6.1f} {r["p50"]:>6.1f} '
                  f'{r["p85"]:>6.1f}   {nuestro["p85"] - r["p85"]:>+7.1f}')
        filas.append({'hora': h, 'calibracion': h in cal, 'nuestro': nuestro, 'tubo': r,
                      'rangos': a_rangos(kmh), 'rangos_tubo': tubo.get(f'{h}:00')})

    prueba = [f for f in filas if not f['calibracion'] and f['nuestro']['n'] and f['tubo']]
    if len(prueba) >= 3:
        import numpy as np
        a = np.array([f['nuestro']['p50'] for f in prueba])
        b = np.array([f['tubo']['p50'] for f in prueba])
        r = np.corrcoef(a, b)[0, 1]
        err = np.array([f['nuestro']['p85'] - f['tubo']['p85'] for f in prueba])
        print(f'\nHoras de prueba: {len(prueba)}. Correlación del perfil (mediana): r = {r:+.2f}. '
              f'Error del p85: medio {err.mean():+.1f}, absoluto medio {np.abs(err).mean():.1f} km/h')
        todos = [sum(f['rangos'][i] for f in prueba) for i in range(16)]
        todos_t = [sum(f['rangos_tubo'][i] for f in prueba) for i in range(16)]
        nt, ntt = sum(todos), sum(todos_t)
        print('\nReparto por rangos en las horas de prueba (nuestro / tubo):')
        for i in range(6):
            etiqueta = f'{BORDES_TUBO[i]:.0f}-{BORDES_TUBO[i + 1]:.0f}'
            print(f'  {etiqueta:>7} km/h  {100 * todos[i] / nt:5.1f} %  {100 * todos_t[i] / ntt:5.1f} %')
        resto = sum(todos[6:]) / nt * 100
        resto_t = sum(todos_t[6:]) / ntt * 100
        print(f'  {">72":>7} km/h  {resto:5.1f} %  {resto_t:5.1f} %')

    if args.salida:
        with open(args.salida, 'w', encoding='utf-8') as fh:
            json.dump({'zona': args.zona, 'distancia_m': distancia, 'calibracion': cal,
                       'a': la, 'b': lb, 'horas': filas}, fh, indent=1)


if __name__ == '__main__':
    main()
