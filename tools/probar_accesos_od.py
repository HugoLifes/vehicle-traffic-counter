"""
Prueba un juego de accesos contra el conteo manual SIN volver a detectar.

Contar la ventana completa de un aforo direccional en la plataforma cuesta
1.5 h de GPU, así que probar un dibujo de accesos distinto costaba otra
1.5 h. Aquí se parte de los rastros ya extraídos de cada video
(extraer_trayectorias.py, uno por video) y se reproduce EXACTAMENTE lo que
hace producción al cerrar cada video (AforoDireccional.cerrar): se
descartan los pedazos que no se movieron, se unen los partidos, se decide
origen y destino y se descartan los incompletos quietos. Cada movimiento
lleva la hora real (inicio del video + cuadro / fps) y se contrasta con el
Excel de la empresa por cuarto de hora.

Dos formas de emparejar los accesos dibujados con los números del croquis:
  · --asignacion "Bajo puente=1,Derecha=3"  → la que dice la geometría;
  · sin ella, la de menos error, como comparar_od_real.py.
La primera es la honesta: el emparejamiento libre de Blvd Ind salió sin
sentido geométrico (ningún acceso en el 4) y aun así era "el mejor".

    python tools/probar_accesos_od.py \\
        --tray "data/od/tray/BLVD_IND_VENTANA__*.json" --fecha 2025-02-26 \\
        --accesos data/od/accesos_blvd_ind.json \\
        --manual "data/od/referencias/AFORO BLVD. INDEPENDENCIA.xlsx" \\
        --asignacion "Bajo puente=1,Abajo der=2,Abajo izq=2,Derecha=3,Izquierda=4"
"""

import argparse
import glob
import itertools
import json
import os
import re
import sys
from collections import Counter, defaultdict

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, 'tools'))

from comparar_od_real import geh, leer_manual                     # noqa: E402
from src.engine.origen_destino import (Rastro, acceso_de_punto,    # noqa: E402
                                       recorrido, se_movio, unir_pedazos)


def movimientos_de_video(ruta, accesos, fecha):
    """Lo mismo que AforoDireccional.cerrar, sobre un JSON de rastros."""
    with open(ruta, encoding='utf-8') as fh:
        datos = json.load(fh)
    m = re.search(r'(\d{2})-(\d{2})-(\d{2})', os.path.basename(datos['video']))
    if not m:
        raise SystemExit(f'Sin hora en el nombre del video: {datos["video"]}')
    inicio_s = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
    fps = datos['fps']
    rastros = []
    for tid, r in datos['rastros'].items():
        o = Rastro(tid)
        for p in r['p']:
            x, y = (p[1] + p[3]) / 2, p[4]
            o.puntos.append((p[0], x, y, p[4] - p[2], acceso_de_punto(accesos, x, y)))
            o.confianzas.append(p[5])
        o.clases = Counter(r['clases'])
        if o.puntos and se_movio(o.puntos):
            rastros.append(o)
    salida = []
    for cadena in unir_pedazos(rastros, fps):
        puntos = [p for c in cadena for p in c.puntos]
        org, dst = recorrido(puntos)
        if org is None and dst is None:
            continue
        if (org is None or dst is None) and not se_movio(puntos):
            continue
        segundo = inicio_s + puntos[0][0] / fps
        salida.append((org, dst, int(segundo // 60)))
    cubre = (inicio_s, inicio_s + datos['cuadros'] / fps)
    return salida, cubre


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tray', required=True, help='patrón de JSON de rastros, uno por video')
    ap.add_argument('--fecha', required=True)
    ap.add_argument('--accesos', required=True)
    ap.add_argument('--manual', required=True)
    ap.add_argument('--asignacion', default=None,
                    help='"Nombre=número,..." para fijar el emparejamiento por geometría')
    a = ap.parse_args()

    with open(a.accesos, encoding='utf-8') as fh:
        definidos = json.load(fh)
    accesos = [{'id': i + 1, 'name': d['nombre'], 'kind': 'acceso', 'points': d['puntos']}
               for i, d in enumerate(definidos)]
    nombre = {z['id']: z['name'] for z in accesos}

    completos = defaultdict(Counter)
    incompletos = Counter()
    tramos = []
    archivos = sorted(glob.glob(a.tray))
    if not archivos:
        sys.exit(f'Ningún archivo coincide con {a.tray}')
    for ruta in archivos:
        movs, cubre = movimientos_de_video(ruta, accesos, a.fecha)
        tramos.append(cubre)
        for org, dst, minuto in movs:
            q = minuto // 15 * 15
            if org is not None and dst is not None:
                completos[q][(org, dst)] += 1
            else:
                incompletos[q] += 1

    unidos = []
    for ini, fin in sorted(tramos):
        if unidos and ini <= unidos[-1][1] + 3:
            unidos[-1][1] = max(unidos[-1][1], fin)
        else:
            unidos.append([ini, fin])
    real = leer_manual(a.manual)
    cuartos = sorted(q for q in real
                     if any(i <= q * 60 and (q + 15) * 60 <= f for i, f in unidos))
    if not cuartos:
        sys.exit('Ningún cuarto de hora del manual está cubierto entero por los videos')
    numeros = sorted({n for q in real for mv in real[q] for n in mv.split('_')})
    movs_manual = sorted({mv for q in real for mv in real[q]})
    ids = sorted(nombre)

    def predicho(asig):
        p = defaultdict(Counter)
        for q in cuartos:
            for (o, d), n in completos[q].items():
                if o in asig and d in asig:
                    p[q][f'{asig[o]}_{asig[d]}'] += n
        return p

    def error(asig):
        p = predicho(asig)
        return sum(abs(p[q].get(mv, 0) - sum(real[q].get(mv, [0, 0, 0])))
                   for q in cuartos for mv in set(movs_manual) | set(p[q]))

    if a.asignacion:
        por_nombre = {n.strip(): v.strip() for n, v in
                      (par.split('=') for par in a.asignacion.split(','))}
        faltan = set(nombre.values()) - set(por_nombre)
        if faltan:
            sys.exit(f'La asignación no dice qué número es: {", ".join(sorted(faltan))}')
        asig = {i: por_nombre[nombre[i]] for i in ids}
        origen = 'fijada por geometría'
    else:
        asig = min((dict(zip(ids, c)) for c in itertools.product(numeros, repeat=len(ids))),
                   key=error)
        origen = 'la de menos error (sin geometría)'

    print(f"Cuartos comparables: {', '.join(f'{q // 60:02d}:{q % 60:02d}' for q in cuartos)}")
    print(f'Emparejamiento ({origen}):')
    for i in ids:
        print(f'  {nombre[i]:<16} -> {asig[i]}')

    p = predicho(asig)
    minutos = 15 * len(cuartos)
    print(f"\n{'movimiento':<11}{'plataforma':>11}{'manual':>8}{'%':>7}{'GEH':>7}")
    ok = n = tp = tr = 0
    for mv in movs_manual:
        pv = sum(p[q].get(mv, 0) for q in cuartos)
        rv = sum(sum(real[q].get(mv, [0, 0, 0])) for q in cuartos)
        tp += pv
        tr += rv
        g = geh(pv * 60 / minutos, rv * 60 / minutos)
        if pv or rv:
            n += 1
            ok += g < 5
        print(f"{mv:<11}{pv:>11}{rv:>8}{(f'{100 * pv / rv:.0f}' if rv else '-'):>7}{g:>7.1f}")
    for mv in sorted({mv for q in cuartos for mv in p[q]} - set(movs_manual)):
        pv = sum(p[q].get(mv, 0) for q in cuartos)
        tp += pv
        print(f'{mv:<11}{pv:>11}   (no está en el manual)')
    inc = sum(incompletos[q] for q in cuartos)
    print(f"\n{'TOTAL':<11}{tp:>11}{tr:>8}{100 * tp / tr if tr else 0:>6.0f}%")
    print(f'Incompletos en la ventana (no sumados): {inc}')
    print(f'Movimientos con GEH < 5: {ok} de {n} ({100 * ok / n if n else 0:.0f} %; criterio 85 %)')
    print(f'Error absoluto total del emparejamiento: {error(asig)}')


if __name__ == '__main__':
    main()
