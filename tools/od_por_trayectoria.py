"""
Contrastar la decisión por TRAYECTORIA (src/engine/od_trayectoria.py)
contra el conteo manual, sobre rastros ya extraídos y SIN volver a detectar.

Reproduce lo que hace producción: cierra cada video como
AforoDireccional.cerrar (descartar quietos, unir pedazos, origen y destino
por zonas), guarda de cada vehículo el mismo recorrido compacto que se
guarda en la base, y decide con el mismo motor que usa el informe. Así lo
que se mide aquí es lo que entrega la plataforma, no una versión aparte.

Las plantillas pueden venir de OTROS videos del mismo aforo
(--plantillas-de), para no medir sobre lo mismo con lo que se aprendió.

La asignación de accesos dibujados a números del croquis se da a mano y
por geometría (--asignacion), no por la que menos error deja: con pocos
cuartos de hora, "la de menos error" rescata dibujos equivocados. En
Entrada y salida Altozano mandaba "Derecha" al acceso 3 para salvar 92
vehículos que solo rozaban esa zona.

    python tools/od_por_trayectoria.py \\
        --tray "data/od/tray/ALTOZANO_VENTANA__07-[123]*.json" \\
        --plantillas-de "data/od/tray/ALTOZANO_VENTANA__07-[45]*.json" \\
        --accesos data/od/accesos_entrada_altozano.json \\
        --manual "data/od/referencias/AFORO ENTRADA Y SALIDA ALTOZANO.xlsx" \\
        --asignacion "Arco=2,Fondo izq=1,Izquierda=3,Abajo=3,Derecha=x" \\
        --imagen data/od/od_trayectoria.png
"""

import argparse
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict

import numpy as np

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, 'tools'))

from comparar_od_real import geh, leer_manual                     # noqa: E402
from src.engine import od_trayectoria as odt                       # noqa: E402
from src.engine.origen_destino import (Rastro, acceso_de_punto,    # noqa: E402
                                       recorrido, se_movio, unir_pedazos)


def _inicio_s(video):
    m = re.search(r'(\d{2})-(\d{2})-(\d{2})', os.path.basename(video))
    if not m:
        raise SystemExit(f'Sin hora en el nombre del video: {video}')
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))


def registros_de_video(ruta, accesos):
    """Los vehículos que producción guarda al cerrar el video, con su recorrido."""
    with open(ruta, encoding='utf-8') as fh:
        datos = json.load(fh)
    inicio = _inicio_s(datos['video'])
    fps = datos['fps']
    rastros = []
    for tid, r in datos['rastros'].items():
        o = Rastro(tid)
        for p in r['p']:
            x, y = (p[1] + p[3]) / 2, p[4]
            o.puntos.append((p[0], x, y, p[4] - p[2], acceso_de_punto(accesos, x, y)))
        o.clases = Counter(r['clases'])
        if o.puntos and se_movio(o.puntos):
            rastros.append(o)
    salida = []
    for n, cadena in enumerate(unir_pedazos(rastros, fps)):
        puntos = [p for c in cadena for p in c.puntos]
        org, dst = recorrido(puntos)
        if org is None and dst is None:
            continue
        if (org is None or dst is None) and not se_movio(puntos):
            continue
        clases = Counter()
        for c in cadena:
            clases.update(c.clases)
        salida.append(odt.registro(org, dst, odt.compactar(puntos, fps, dst), inicio,
                                   os.path.basename(ruta), clases.most_common(1)[0][0],
                                   clave=(os.path.basename(ruta), n)))
    return salida, (inicio, inicio + datos['cuadros'] / fps)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tray', required=True, help='rastros a contar, un JSON por video')
    ap.add_argument('--plantillas-de', default=None,
                    help='rastros de los que salen las plantillas (por omisión, los mismos)')
    ap.add_argument('--accesos', required=True)
    ap.add_argument('--manual', default=None)
    ap.add_argument('--asignacion', default=None,
                    help='"Nombre=número,..."; x para un acceso que el manual no cuenta')
    ap.add_argument('--cobertura-minima', type=float, default=0.85,
                    help='fracción de un cuarto de hora que tienen que cubrir los videos')
    ap.add_argument('--imagen', default=None)
    a = ap.parse_args()

    with open(a.accesos, encoding='utf-8') as fh:
        accesos = [{'id': i + 1, 'name': d['nombre'], 'kind': 'acceso', 'points': d['puntos']}
                   for i, d in enumerate(json.load(fh))]
    nombre = {z['id']: z['name'] for z in accesos}

    def cargar(patron):
        archivos = sorted(glob.glob(patron))
        if not archivos:
            sys.exit(f'Ningún archivo coincide con {patron}')
        regs, tramos = [], []
        for ruta in archivos:
            r, t = registros_de_video(ruta, accesos)
            regs += r
            tramos.append(t)
        return regs, tramos, archivos

    def par(mov):
        return f'{nombre[mov[0]]} -> {nombre[mov[1]]}'

    regs, tramos, archivos = cargar(a.tray)
    tpl = odt.plantillas(cargar(a.plantillas_de)[0]) if a.plantillas_de else None
    d = odt.decidir(regs, tpl)

    print(f"{len(archivos)} videos a contar; plantillas de "
          f"{'otros videos' if a.plantillas_de else 'los mismos videos'}")
    print('\nPlantillas:')
    for mov, p in sorted(d['plantillas'].items(), key=lambda kv: -kv[1]['ejemplos']):
        print(f"  {par(mov):<26} {p['ejemplos']:>4} completos, tarda {p['duracion']:.1f} s, "
              f"{100 * p['sale']:.0f} % muere en su destino")
    for mov, dst in d['absorbida'].items():
        print(f"  {par(mov):<26} es {par(dst)} visto a medias: se absorbe")
    print('\nDecisiones: ' + '  ·  '.join(
        f'{k} {v}' for k, v in sorted(d['motivos'].items(), key=lambda kv: -kv[1])))

    def cuarto(t):
        return int(t // 60) // 15 * 15

    produccion = defaultdict(Counter)
    for r in regs:
        if r['org'] is not None and r['dst'] is not None:
            produccion[cuarto(r['t0'])][(r['org'], r['dst'])] += 1
    trayectoria = defaultdict(Counter)
    for v in d['vehiculos']:
        trayectoria[cuarto(v['t0'])][(v['origen_id'], v['destino_id'])] += 1

    if a.imagen:
        _dibujar(a.imagen, archivos[0], d, regs, nombre)

    if not (a.manual and a.asignacion):
        print('\nSin --manual y --asignacion no hay comparación. Por par de zonas:')
        tot_p, tot_t = Counter(), Counter()
        for q in produccion:
            tot_p.update(produccion[q])
        for q in trayectoria:
            tot_t.update(trayectoria[q])
        for mov in sorted(set(tot_p) | set(tot_t), key=lambda m: -tot_t[m]):
            print(f'  {par(mov):<26} zonas {tot_p[mov]:>4}   trayectoria {tot_t[mov]:>4}')
        return

    por_nombre = {n.strip(): v.strip() for n, v in
                  (p.split('=') for p in a.asignacion.split(','))}
    faltan = set(nombre.values()) - set(por_nombre)
    if faltan:
        sys.exit(f'La asignación no dice qué número es: {", ".join(sorted(faltan))}')
    asig = {i: por_nombre[nombre[i]] for i in nombre}

    unidos = []
    for ini, fin in sorted(tramos):
        if unidos and ini <= unidos[-1][1] + 3:
            unidos[-1][1] = max(unidos[-1][1], fin)
        else:
            unidos.append([ini, fin])
    real = leer_manual(a.manual)
    cobertura = {}
    for q in real:
        s0, s1 = q * 60, (q + 15) * 60
        dentro = sum(max(0, min(s1, f) - max(s0, i)) for i, f in unidos)
        if dentro / 900 >= a.cobertura_minima:
            cobertura[q] = dentro / 900
    if not cobertura:
        sys.exit('Ningún cuarto de hora del manual queda cubierto')

    def mapear(conteo):
        m = defaultdict(Counter)
        for q in cobertura:
            for (o, dd), n in conteo[q].items():
                if asig[o] != 'x' and asig[dd] != 'x':
                    m[q][f'{asig[o]}_{asig[dd]}'] += n
        return m

    pp, pt = mapear(produccion), mapear(trayectoria)
    movs = sorted({mv for q in cobertura for mv in real[q]} |
                  {mv for q in cobertura for mv in pt[q]} |
                  {mv for q in cobertura for mv in pp[q]})
    minutos = 15 * sum(cobertura.values())

    print('\nCuartos comparados: ' + ', '.join(
        f'{q // 60:02d}:{q % 60:02d} ({100 * c:.0f} % cubierto)'
        for q, c in sorted(cobertura.items())))
    print('Un cuarto cubierto a medias se compara contra el manual escalado a su cobertura.\n')
    print(f"{'movimiento':<11}{'manual':>8}{'zonas':>8}{'GEH':>6}{'trayectoria':>13}{'GEH':>6}")
    tot = [0.0, 0, 0]
    ok = [0, 0]
    n = 0
    for mv in movs:
        rv = sum(sum(real[q].get(mv, [0, 0, 0])) * cobertura[q] for q in cobertura)
        bv = sum(pp[q].get(mv, 0) for q in cobertura)
        cv = sum(pt[q].get(mv, 0) for q in cobertura)
        gb = geh(bv * 60 / minutos, rv * 60 / minutos)
        gc = geh(cv * 60 / minutos, rv * 60 / minutos)
        tot[0] += rv
        tot[1] += bv
        tot[2] += cv
        if rv >= 0.5 or bv or cv:
            n += 1
            ok[0] += gb < 5
            ok[1] += gc < 5
        print(f'{mv:<11}{rv:>8.0f}{bv:>8}{gb:>6.1f}{cv:>13}{gc:>6.1f}')
    print(f"\n{'TOTAL':<11}{tot[0]:>8.0f}{tot[1]:>8}{'':>6}{tot[2]:>13}")
    print(f"{'razón':<11}{'':>8}{tot[1] / tot[0]:>7.2f}x{'':>6}{tot[2] / tot[0]:>12.2f}x")
    print(f'GEH < 5: zonas {ok[0]} de {n}, trayectoria {ok[1]} de {n} (criterio 85 %)')

    print('\nPor cuarto de hora: manual / zonas / trayectoria')
    for q in sorted(cobertura):
        rv = sum(sum(v) for v in real[q].values()) * cobertura[q]
        print(f'  {q // 60:02d}:{q % 60:02d}  {rv:6.0f} / {sum(pp[q].values()):5} '
              f'/ {sum(pt[q].values()):5}')


def _dibujar(salida, primer_json, d, regs, nombre):
    """Para mirar a ojo: la franja de cada movimiento gruesa, los vehículos
    completados por trayectoria finos con su color, y en gris los que
    quedaron sin decidir."""
    import cv2
    fondo = cv2.imread(primer_json.replace('.json', '.jpg'))
    if fondo is None:
        fondo = np.full((720, 1280, 3), 40, np.uint8)
    img = (fondo * 0.55).astype(np.uint8)
    colores = [(0, 200, 255), (255, 120, 0), (80, 255, 80), (255, 0, 255), (0, 80, 255),
               (255, 255, 0), (160, 160, 255), (0, 255, 180), (200, 120, 255)]
    tpl = d['plantillas']
    color = {mov: colores[i % len(colores)] for i, mov in enumerate(sorted(tpl))}
    por_clave = {r['clave']: r for r in regs}

    def trazo(reg, col, grosor):
        pts = np.array([(p[1], p[2]) for p in reg['puntos']], np.int32).reshape(-1, 1, 2)
        cv2.polylines(img, [pts], False, col, grosor, cv2.LINE_AA)

    for s in d['sin_decidir']:
        trazo(por_clave[s['clave']], (110, 110, 110), 1)
    for v in d['vehiculos']:
        if v['decision'] == 'trayectoria':
            trazo(por_clave[v['clave']],
                  color.get((v['origen_id'], v['destino_id']), (255, 255, 255)), 1)
    for mov, p in tpl.items():
        for e in p['ejemplares']:
            pts = e['xy'].astype(np.int32).reshape(-1, 1, 2)
            cv2.polylines(img, [pts], False, color[mov], 3, cv2.LINE_AA)
        x, y = p['xy'][len(p['xy']) // 2]
        cv2.putText(img, f"{nombre[mov[0]]}>{nombre[mov[1]]} ({p['ejemplos']})",
                    (int(x) + 6, int(y) - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color[mov], 2)
    cv2.imwrite(salida, img)
    print(f'\n{salida}')


if __name__ == '__main__':
    main()
