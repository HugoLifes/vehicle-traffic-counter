"""
Firmas de color de cada rastro ya extraído, leyendo el video una vez.

extraer_trayectorias.py guarda cajas, no píxeles, y detectar otra vez para
sacar el color costaría GPU. Aquí solo se decodifica el video (CPU) y se
mide el color en los cuadros que hacen falta: los primeros y los últimos
puntos de cada rastro, que es lo que usa el motor para decidir si dos
pedazos son el mismo vehículo (src/engine/origen_destino.firma_color).

    python tools/firmas_color.py data/od/tray/X__bytetrack.json \\
        --video "data/od/videos/AFORO BLVD IND/17-04-54_2a.mkv"
"""

import argparse
import json
import os
import sys
from collections import defaultdict

import cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.engine.origen_destino import firma_color   # noqa: E402

# 5 muestras por extremo, una cada 3 cuadros: el motor usa la mediana de 5
# por extremo, y separarlas evita que las 5 caigan en el mismo instante en
# que la caja ya está medio tapada.
POR_EXTREMO = 5
PASO = 3


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('tray')
    ap.add_argument('--video', required=True)
    ap.add_argument('--desde-min', type=float, default=0)
    ap.add_argument('--salida', default=None)
    args = ap.parse_args()

    with open(args.tray, encoding='utf-8') as fh:
        datos = json.load(fh)

    # cuadro -> [(tid, 'ini'|'fin', bbox)]
    pedidos = defaultdict(list)
    for tid, r in datos['rastros'].items():
        p = r['p']
        ini = p[:POR_EXTREMO * PASO:PASO]
        fin = p[-POR_EXTREMO * PASO::PASO]
        for q in ini:
            pedidos[q[0]].append((tid, 'ini', q[1:5]))
        for q in fin:
            pedidos[q[0]].append((tid, 'fin', q[1:5]))

    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 15
    base = int(args.desde_min * 60 * fps)
    if base:
        cap.set(cv2.CAP_PROP_POS_FRAMES, base)
    firmas = defaultdict(lambda: {'ini': [], 'fin': []})
    ultimo = max(pedidos) if pedidos else -1
    n = 0
    while n <= ultimo:
        ok, f = cap.read()
        if not ok:
            break
        for tid, extremo, caja in pedidos.get(n, ()):
            c = firma_color(f, caja)
            if c is not None:
                firmas[tid][extremo].append([round(v, 1) for v in c])
        n += 1
    cap.release()

    salida = args.salida or args.tray.replace('.json', '__firmas.json')
    with open(salida, 'w', encoding='utf-8') as fh:
        json.dump(firmas, fh, separators=(',', ':'))
    print(f'{len(firmas)} rastros con firma, {n} cuadros leídos -> {salida}')


if __name__ == '__main__':
    main()
