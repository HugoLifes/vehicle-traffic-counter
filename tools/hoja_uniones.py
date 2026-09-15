"""
¿Las uniones de rastros partidos juntan al MISMO vehículo?

El motor direccional une el pedazo de rastro que se pierde (detrás de un
letrero, tapado por otro vehículo) con el que reaparece. Aflojar la
tolerancia une más pedazos y sube los movimientos completos, pero también
puede unir dos vehículos distintos, y eso no se ve en ningún total: el
movimiento sale "completo" y equivocado. La única prueba es mirar.

Para cada unión recorta del video la última caja del pedazo que muere y la
primera del que nace, lado a lado, con el hueco en cuadros. Se cuentan a ojo
los pares que no son el mismo vehículo.

    python tools/hoja_uniones.py data/od/tray/X__accesos.json --video V.mkv \\
        --salida data/od/uniones.png
"""

import argparse
import json
import math
import os

import cv2
import numpy as np

LADO = 110


def recorte(cap, cuadro, caja):
    cap.set(cv2.CAP_PROP_POS_FRAMES, cuadro)
    ok, f = cap.read()
    if not ok:
        return np.zeros((LADO, LADO, 3), np.uint8)
    _, x1, y1, x2, y2, _ = caja
    alto = max(y2 - y1, x2 - x1)
    # Margen de medio vehículo alrededor, para ver con qué se confunde.
    m = alto * 0.5
    X1, Y1 = int(max(0, x1 - m)), int(max(0, y1 - m))
    X2, Y2 = int(min(f.shape[1], x2 + m)), int(min(f.shape[0], y2 + m))
    r = f[Y1:Y2, X1:X2].copy()
    cv2.rectangle(r, (int(x1 - X1), int(y1 - Y1)), (int(x2 - X1), int(y2 - Y1)),
                  (0, 255, 255), 1)
    if r.size == 0:
        return np.zeros((LADO, LADO, 3), np.uint8)
    esc = LADO / max(r.shape[:2])
    r = cv2.resize(r, None, fx=esc, fy=esc, interpolation=cv2.INTER_CUBIC)
    lienzo = np.zeros((LADO, LADO, 3), np.uint8)
    lienzo[:r.shape[0], :r.shape[1]] = r
    return lienzo


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('accesos_json', help='el __accesos.json que escribe analizar_od --accesos')
    ap.add_argument('--video', required=True)
    ap.add_argument('--desde-min', type=float, default=0,
                    help='minuto del video donde empezó la extracción')
    ap.add_argument('--columnas', type=int, default=6)
    ap.add_argument('--max', type=int, default=60)
    ap.add_argument('--salida', default=None)
    args = ap.parse_args()

    with open(args.accesos_json, encoding='utf-8') as fh:
        uniones = json.load(fh).get('uniones', [])[:args.max]
    if not uniones:
        raise SystemExit('No hay uniones en ese archivo (¿corrió analizar_od con --accesos?)')

    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 15
    base = int(args.desde_min * 60 * fps)
    celdas = []
    for i, u in enumerate(uniones):
        a = recorte(cap, base + u['muere'][0], u['muere'])
        b = recorte(cap, base + u['nace'][0], u['nace'])
        par = np.hstack([a, np.full((LADO, 4, 3), 255, np.uint8), b])
        pie = np.zeros((18, par.shape[1], 3), np.uint8)
        hueco = u['nace'][0] - u['muere'][0]
        cv2.putText(pie, f"#{i + 1}  hueco {hueco} c", (3, 13), cv2.FONT_HERSHEY_SIMPLEX,
                    0.4, (255, 255, 255), 1, cv2.LINE_AA)
        celdas.append(np.vstack([par, pie]))
    cap.release()

    cols = args.columnas
    filas = math.ceil(len(celdas) / cols)
    h, w = celdas[0].shape[:2]
    hoja = np.zeros((filas * (h + 6), cols * (w + 6), 3), np.uint8)
    for i, c in enumerate(celdas):
        f, k = divmod(i, cols)
        hoja[f * (h + 6):f * (h + 6) + h, k * (w + 6):k * (w + 6) + w] = c
    salida = args.salida or args.accesos_json.replace('.json', '__uniones.png')
    cv2.imwrite(salida, hoja)
    print(f'{len(celdas)} uniones -> {salida}')


if __name__ == '__main__':
    main()
