"""
¿Dónde entra y sale de verdad el tránsito de la vista? Sobre una ventana
completa (varios videos), con el mismo proceso de producción.

Dibujar los accesos por dónde "se ve pasar" tránsito falló en Blvd Ind:
2 107 movimientos incompletos en 80 minutos y movimientos enteros en cero,
porque ningún vehículo registraba origen en los accesos de abajo. Antes de
volver a dibujar hay que ver dónde nacen y dónde mueren los rastros, ya
unidos como los une producción:

  · verde   — inicio de un incompleto SIN ORIGEN (nació fuera de todo acceso);
  · rojo    — fin de un incompleto SIN DESTINO (murió fuera de todo acceso);
  · azul    — inicio de un movimiento completo;
  · naranja — fin de un movimiento completo.

Donde se amontonan los verdes y rojos falta un acceso, o el que hay está
mal puesto. También escribe, por celda de una rejilla, cuántos inicios y
fines sin acceso cayeron ahí, para dibujar el polígono con números.

    python tools/mapa_extremos_od.py --tray "data/od/tray/BLVD_IND_VENTANA__*.json" \\
        --accesos data/od/accesos_blvd_ind.json --salida data/od/mapa_blvd.png
"""

import argparse
import glob
import json
import os
import sys
from collections import Counter

import cv2
import numpy as np

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from src.engine.origen_destino import (Rastro, acceso_de_punto,    # noqa: E402
                                       recorrido, se_movio, unir_pedazos)

CELDA = 80


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tray', required=True)
    ap.add_argument('--accesos', required=True)
    ap.add_argument('--salida', required=True)
    a = ap.parse_args()

    with open(a.accesos, encoding='utf-8') as fh:
        definidos = json.load(fh)
    accesos = [{'id': i + 1, 'name': d['nombre'], 'kind': 'acceso', 'points': d['puntos']}
               for i, d in enumerate(definidos)]

    archivos = sorted(glob.glob(a.tray))
    if not archivos:
        sys.exit(f'Ningún archivo coincide con {a.tray}')
    extremos = {'sin_origen': [], 'sin_destino': [], 'ini': [], 'fin': []}
    ancho = alto = None
    base = None
    for ruta in archivos:
        with open(ruta, encoding='utf-8') as fh:
            datos = json.load(fh)
        ancho, alto = datos['ancho'], datos['alto']
        if base is None:
            base = cv2.imread(ruta.replace('.json', '.jpg'))
        rastros = []
        for tid, r in datos['rastros'].items():
            o = Rastro(tid)
            for p in r['p']:
                x, y = (p[1] + p[3]) / 2, p[4]
                o.puntos.append((p[0], x, y, p[4] - p[2], acceso_de_punto(accesos, x, y)))
            if o.puntos and se_movio(o.puntos):
                rastros.append(o)
        for cadena in unir_pedazos(rastros, datos['fps']):
            puntos = [p for c in cadena for p in c.puntos]
            org, dst = recorrido(puntos)
            if org is None and dst is None:
                continue
            if (org is None or dst is None) and not se_movio(puntos):
                continue
            ini, fin = puntos[0][1:3], puntos[-1][1:3]
            if org is None:
                extremos['sin_origen'].append(ini)
            if dst is None:
                extremos['sin_destino'].append(fin)
            if org is not None and dst is not None:
                extremos['ini'].append(ini)
                extremos['fin'].append(fin)

    if base is None:
        base = np.zeros((alto, ancho, 3), np.uint8)
    img = base.copy()
    capa = img.copy()
    for k, z in enumerate(accesos):
        cv2.fillPoly(capa, [np.array(z['points'], np.int32)], (255, 255, 255))
    cv2.addWeighted(capa, 0.15, img, 0.85, 0, img)
    colores = {'ini': (255, 120, 0), 'fin': (0, 160, 255),
               'sin_origen': (0, 255, 0), 'sin_destino': (0, 0, 255)}
    for clave in ('ini', 'fin', 'sin_origen', 'sin_destino'):
        for x, y in extremos[clave]:
            cv2.circle(img, (int(x), int(y)), 2, colores[clave], -1)
    for z in accesos:
        pts = np.array(z['points'], np.int32)
        cv2.polylines(img, [pts], True, (255, 255, 255), 2, cv2.LINE_AA)
        cx, cy = pts.mean(axis=0).astype(int)
        cv2.putText(img, z['name'], (int(cx) - 40, int(cy)), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (255, 255, 255), 2, cv2.LINE_AA)

    # Rejilla: cuántos incompletos empiezan o terminan en cada celda.
    rejilla = Counter()
    for x, y in extremos['sin_origen'] + extremos['sin_destino']:
        rejilla[(int(x) // CELDA, int(y) // CELDA)] += 1
    for (cx, cy), n in rejilla.items():
        if n >= 20:
            x0, y0 = cx * CELDA, cy * CELDA
            cv2.rectangle(img, (x0, y0), (x0 + CELDA, y0 + CELDA), (0, 255, 255), 1)
            cv2.putText(img, str(n), (x0 + 4, y0 + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                        (0, 255, 255), 1, cv2.LINE_AA)
    cv2.imwrite(a.salida, img)

    print(f"{len(archivos)} videos: completos {len(extremos['ini'])}, "
          f"sin origen {len(extremos['sin_origen'])}, sin destino {len(extremos['sin_destino'])}")
    print(f'Celdas de {CELDA} px con más incompletos (x0-x1, y0-y1: cuántos):')
    for (cx, cy), n in rejilla.most_common(15):
        print(f'  x {cx * CELDA}-{(cx + 1) * CELDA}, y {cy * CELDA}-{(cy + 1) * CELDA}: {n}')
    print(a.salida)


if __name__ == '__main__':
    main()
