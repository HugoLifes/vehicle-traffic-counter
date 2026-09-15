"""
Origen-destino a partir de las trayectorias que guarda extraer_trayectorias.py.

No detecta nada: trabaja sobre el JSON, así que cada prueba tarda segundos.
Responde, en este orden, las tres preguntas que deciden si un video sirve
para aforo direccional:

1. **¿Cuántos rastros se parten?** Un vehículo que entra por un acceso y
   sale por otro tiene que empezar y terminar en la ORILLA de la escena. Un
   rastro que empieza o termina en el centro es un pedazo: lo tapó otro
   vehículo, o el detector lo perdió. Es el error dominante del conteo por
   movimiento según toda la literatura revisada.
2. **¿Se pueden unir los pedazos?** Un pedazo que termina y otro que empieza
   poco después, donde el primero habría llegado a su velocidad y con un
   tamaño parecido, son el mismo vehículo.
3. **¿Por dónde se entra y se sale?** Agrupa los puntos iniciales y finales
   de los rastros completos. El método sigue a "Unsupervised Detection of
   Entry and Exit Regions from Vehicle Trajectories" (arXiv 2607.10949):
   7 puntos por extremo, se descarta el centro de la escena (1/6 por lado)
   y K-Means con k elegido por el codo. Ahí midieron 3.4 % de error mediano
   contra conteo manual en 25 cámaras.

    python tools/analizar_od.py data/od/tray/X__07-49-57_2ta__bytetrack.json
"""

import argparse
import json
import math
import os
import sys
from collections import Counter, defaultdict

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PUNTOS_POR_EXTREMO = 7
COLORES = [(80, 80, 255), (80, 200, 255), (80, 255, 160), (255, 200, 80),
           (255, 110, 200), (200, 120, 255), (60, 255, 255), (255, 255, 90),
           (160, 160, 160)]


def _apoyo(p):
    """Punto de contacto con el pavimento: el mismo criterio del contador."""
    _, x1, y1, x2, y2, _ = p
    return ((x1 + x2) / 2, y2)


def cargar(ruta, min_cuadros, min_recorrido):
    with open(ruta, encoding='utf-8') as fh:
        datos = json.load(fh)
    diag = math.hypot(datos['ancho'], datos['alto'])
    rastros = []
    for tid, r in datos['rastros'].items():
        pts = r['p']
        if len(pts) < min_cuadros:
            continue
        a, b = _apoyo(pts[0]), _apoyo(pts[-1])
        # Un vehículo detenido todo el clip no aporta movimiento; se descarta
        # antes de que ensucie los grupos de entrada y salida.
        if math.hypot(b[0] - a[0], b[1] - a[1]) < min_recorrido * diag:
            continue
        rastros.append({
            'id': tid, 'p': pts,
            'clase': max(r['clases'].items(), key=lambda kv: kv[1])[0],
        })
    return datos, rastros


def region_de_interes(rastros):
    xs = [_apoyo(p)[0] for r in rastros for p in r['p']]
    ys = [_apoyo(p)[1] for r in rastros for p in r['p']]
    return min(xs), min(ys), max(xs), max(ys)


def en_centro(pt, roi, razon):
    x0, y0, x1, y1 = roi
    mx, my = (x1 - x0) * razon, (y1 - y0) * razon
    return x0 + mx < pt[0] < x1 - mx and y0 + my < pt[1] < y1 - my


def unir_pedazos(rastros, roi, razon, fps, max_hueco_s, tolerancia):
    """
    Une un rastro que muere en el centro con uno que nace en el centro poco
    después, si el segundo aparece donde el primero habría llegado.

    Emparejamiento voraz por costo creciente: primero las uniones más
    obvias, y cada pedazo se usa una sola vez.
    """
    muertos = [r for r in rastros if en_centro(_apoyo(r['p'][-1]), roi, razon)]
    nacidos = [r for r in rastros if en_centro(_apoyo(r['p'][0]), roi, razon)]
    hueco = int(max_hueco_s * fps)
    candidatos = []
    for a in muertos:
        fa = a['p'][-1][0]
        pa = _apoyo(a['p'][-1])
        k = min(len(a['p']) - 1, 5)
        pk = _apoyo(a['p'][-1 - k])
        df = max(1, a['p'][-1][0] - a['p'][-1 - k][0])
        vx, vy = (pa[0] - pk[0]) / df, (pa[1] - pk[1]) / df
        ha = a['p'][-1][4] - a['p'][-1][2]
        for b in nacidos:
            if b is a:
                continue
            fb = b['p'][0][0]
            if not 0 < fb - fa <= hueco:
                continue
            hb = b['p'][0][4] - b['p'][0][2]
            if not 0.6 <= hb / max(ha, 1) <= 1.6:
                continue
            esperado = (pa[0] + vx * (fb - fa), pa[1] + vy * (fb - fa))
            pb = _apoyo(b['p'][0])
            dist = math.hypot(pb[0] - esperado[0], pb[1] - esperado[1])
            # La tolerancia crece con el tamaño del vehículo: 1 alto de caja.
            if dist <= tolerancia * max(ha, hb):
                candidatos.append((dist / max(ha, hb) + (fb - fa) / hueco, a, b))
    candidatos.sort(key=lambda c: c[0])
    usados_a, usados_b = set(), set()
    siguiente = {}
    for _, a, b in candidatos:
        if a['id'] in usados_a or b['id'] in usados_b:
            continue
        usados_a.add(a['id'])
        usados_b.add(b['id'])
        siguiente[a['id']] = b

    por_id = {r['id']: r for r in rastros}
    tiene_previo = set(usados_b)
    unidos = []
    for r in rastros:
        if r['id'] in tiene_previo:
            continue
        cadena = [r]
        while cadena[-1]['id'] in siguiente:
            cadena.append(siguiente[cadena[-1]['id']])
        clases = Counter(c['clase'] for c in cadena)
        unidos.append({
            'id': '+'.join(c['id'] for c in cadena),
            'p': [p for c in cadena for p in c['p']],
            'clase': clases.most_common(1)[0][0],
            'pedazos': len(cadena),
        })
    assert sum(u['pedazos'] for u in unidos) == len(por_id)
    return unidos, len(siguiente)


def _k_por_codo(puntos, k_min=2, k_max=9):
    from sklearn.cluster import KMeans
    k_max = min(k_max, max(k_min, len(puntos) // 5))
    ks = list(range(k_min, k_max + 1))
    modelos = [KMeans(n_clusters=k, n_init=10, random_state=0).fit(puntos) for k in ks]
    if len(ks) <= 2:
        return modelos[0]
    inercias = np.array([m.inertia_ for m in modelos])
    # Codo: el k más alejado de la recta entre el primero y el último.
    x = np.array(ks, dtype=float)
    x = (x - x[0]) / (x[-1] - x[0])
    y = (inercias - inercias[-1]) / max(inercias[0] - inercias[-1], 1e-9)
    distancia = np.abs(x + y - 1) / math.sqrt(2)
    return modelos[int(np.argmax(distancia))]


def agrupar_extremos(rastros, roi, razon):
    inicio = [_apoyo(p) for r in rastros for p in r['p'][:PUNTOS_POR_EXTREMO]
              if not en_centro(_apoyo(p), roi, razon)]
    fin = [_apoyo(p) for r in rastros for p in r['p'][-PUNTOS_POR_EXTREMO:]
           if not en_centro(_apoyo(p), roi, razon)]
    return (_k_por_codo(np.array(inicio)) if len(inicio) >= 10 else None,
            _k_por_codo(np.array(fin)) if len(fin) >= 10 else None)


def _voto(modelo, pts, roi, razon):
    pts = [p for p in pts if not en_centro(p, roi, razon)]
    if modelo is None or not pts:
        return None
    etiquetas = modelo.predict(np.array(pts))
    return Counter(etiquetas.tolist()).most_common(1)[0][0]


def modo_accesos(datos, rastros, ruta_accesos, ruta_json, salida, hueco=2.0,
                 tolerancia=1.2, tamano=(0.6, 1.6), firmas=None, color=None):
    """
    Origen-destino con accesos DIBUJADOS, usando el mismo motor que la
    plataforma (src/engine/origen_destino.py) en vez de la agrupación
    automática.

    La agrupación falla en cuanto un acceso no está en la orilla del cuadro:
    en la entrada de Altozano los vehículos entran y salen por un arco al
    fondo de la imagen, y los grupos se partieron en seis. Con los accesos
    dibujados se mide lo que va a medir producción.

    Marca en la imagen dónde mueren los rastros sin destino (X roja) y dónde
    nacen los que no tienen origen (+ verde): donde se amontonan hay algo que
    tapa la vía — un letrero, un poste, un vehículo estacionado.
    """
    from src.engine.origen_destino import Rastro, acceso_de_punto, recorrido, unir_pedazos

    with open(ruta_accesos, encoding='utf-8') as fh:
        definidos = json.load(fh)
    accesos = [{'id': i + 1, 'name': a['nombre'], 'kind': 'acceso', 'points': a['puntos']}
               for i, a in enumerate(definidos)]
    nombre = {a['id']: a['name'] for a in accesos}

    objetos = []
    for r in rastros:
        o = Rastro(r['id'])
        for p in r['p']:
            x, y = _apoyo(p)
            o.puntos.append((p[0], x, y, p[4] - p[2], acceso_de_punto(accesos, x, y)))
            o.confianzas.append(p[5])
        o.clases = Counter({r['clase']: len(r['p'])})
        if firmas and r['id'] in firmas:
            # El motor toma la mediana de las primeras y de las últimas 5.
            o.colores = [tuple(c) for c in firmas[r['id']]['ini']] + \
                        [tuple(c) for c in firmas[r['id']]['fin']]
        objetos.append(o)

    antes = Counter()
    for o in objetos:
        org, dst = recorrido(o.puntos)
        antes['completo' if org and dst else 'incompleto' if org or dst else 'sin acceso'] += 1

    lista_uniones = []
    cadenas = unir_pedazos(objetos, datos['fps'], max_hueco_s=hueco, tolerancia=tolerancia,
                           rango_tamano=tamano, uniones=lista_uniones,
                           max_delta_color=color)
    print(f"Unión de pedazos: hueco <= {hueco} s, tolerancia {tolerancia} altos, "
          f"tamaño {tamano[0]}-{tamano[1]}, color {color if color else 'sin usar'}")
    matriz = defaultdict(Counter)
    por_clase = defaultdict(Counter)
    estado = Counter()
    muertes, nacimientos, color_rastro = [], [], {}
    for cadena in cadenas:
        puntos = [p for c in cadena for p in c.puntos]
        org, dst = recorrido(puntos)
        clase = Counter()
        for c in cadena:
            clase.update(c.clases)
        clase = clase.most_common(1)[0][0]
        if org is None and dst is None:
            estado['nunca pisó un acceso'] += 1
            continue
        if org is not None and dst is not None:
            estado['completo'] += 1
            matriz[org][dst] += 1
            por_clase[(org, dst)][clase] += 1
        elif dst is None:
            estado['sin destino'] += 1
            muertes.append(puntos[-1][1:3])
        else:
            estado['sin origen'] += 1
            nacimientos.append(puntos[0][1:3])
        for c in cadena:
            color_rastro[c.id] = (org, dst)

    unidos = sum(1 for c in cadenas if len(c) > 1)
    vistos = estado['completo'] + estado['sin destino'] + estado['sin origen']
    print(f"\nAccesos dibujados: {', '.join(nombre.values())}")
    print(f"Antes de unir: {dict(antes)}")
    print(f"Cadenas unidas: {unidos}")
    print(f"Vehículos que pisaron algún acceso: {vistos}")
    for k in ('completo', 'sin destino', 'sin origen', 'nunca pisó un acceso'):
        v = estado[k]
        pct = f" ({100 * v / vistos:.0f} %)" if vistos and k != 'nunca pisó un acceso' else ''
        print(f"  {k:<22} {v}{pct}")
    print('\nMatriz origen (fila) -> destino (columna):')
    ids = [a['id'] for a in accesos]
    ancho = max(len(n) for n in nombre.values()) + 2
    print(' ' * ancho + ''.join(f'{nombre[j][:10]:>11}' for j in ids))
    for i in ids:
        print(f'{nombre[i]:<{ancho}}' + ''.join(f'{matriz[i][j]:>11}' for j in ids))

    base = cv2.imread(ruta_json.replace('.json', '.jpg'))
    if base is None:
        base = np.zeros((datos['alto'], datos['ancho'], 3), np.uint8)
    img = base.copy()
    capa = img.copy()
    for k, a in enumerate(accesos):
        pts = np.array(a['points'], np.int32)
        cv2.fillPoly(capa, [pts], COLORES[k % len(COLORES)])
    cv2.addWeighted(capa, 0.25, img, 0.75, 0, img)
    movs = sorted({v for v in color_rastro.values() if v[0] and v[1]})
    col_mov = {m: COLORES[i % len(COLORES)] for i, m in enumerate(movs)}
    lineas = np.zeros_like(img)
    for r in rastros:
        m = color_rastro.get(r['id'])
        if m is None:
            continue
        col = col_mov.get(m, (120, 120, 120))
        pts = [tuple(map(int, _apoyo(p))) for p in r['p']]
        for a, b in zip(pts, pts[1:]):
            cv2.line(lineas, a, b, col, 1, cv2.LINE_AA)
    cv2.addWeighted(lineas, 0.9, img, 1.0, 0, img)
    for x, y in muertes:
        cv2.drawMarker(img, (int(x), int(y)), (0, 0, 255), cv2.MARKER_TILTED_CROSS, 9, 2)
    for x, y in nacimientos:
        cv2.drawMarker(img, (int(x), int(y)), (0, 255, 0), cv2.MARKER_CROSS, 9, 2)
    for k, a in enumerate(accesos):
        pts = np.array(a['points'], np.int32)
        cv2.polylines(img, [pts], True, COLORES[k % len(COLORES)], 2, cv2.LINE_AA)
        cx, cy = pts.mean(axis=0).astype(int)
        cv2.putText(img, a['name'], (int(cx) - 30, int(cy)), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (255, 255, 255), 2, cv2.LINE_AA)
    cv2.imwrite(salida, img)

    with open(salida.replace('.png', '.json'), 'w', encoding='utf-8') as fh:
        por_id = {r['id']: r for r in rastros}
        json.dump({
            'estado': dict(estado), 'unidos': unidos,
            # Cada unión: último punto del pedazo que murió y primer punto
            # del que nació, [cuadro, x1, y1, x2, y2, conf], para recortarlos
            # del video y comprobar que son el mismo vehículo.
            'uniones': [{'muere': por_id[a]['p'][-1], 'nace': por_id[b]['p'][0]}
                        for a, b in lista_uniones if a in por_id and b in por_id],
            'matriz': {nombre[o]: {nombre[d]: n for d, n in f.items()} for o, f in matriz.items()},
            'por_clase': {f'{nombre[o]} -> {nombre[d]}': dict(c) for (o, d), c in por_clase.items()},
        }, fh, ensure_ascii=False, indent=1)
    print(f'\n{salida}')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('json')
    ap.add_argument('--accesos', default=None,
                    help='JSON con [{"nombre": ..., "puntos": [[x, y], ...]}]: usa el motor '
                         'de producción con accesos dibujados en vez de agruparlos solo')
    ap.add_argument('--min-cuadros', type=int, default=5)
    ap.add_argument('--min-recorrido', type=float, default=0.04,
                    help='desplazamiento mínimo como fracción de la diagonal')
    ap.add_argument('--centro', type=float, default=1 / 6,
                    help='margen de orilla por lado, como fracción de la escena')
    # Los predeterminados son los del motor de producción
    # (src/engine/origen_destino.py), donde está la medición que los eligió.
    ap.add_argument('--hueco', type=float, default=1.0,
                    help='segundos máximos entre pedazos para unirlos')
    ap.add_argument('--tolerancia', type=float, default=2.0,
                    help='distancia máxima al punto esperado, en altos de caja')
    ap.add_argument('--tamano', type=float, nargs=2, default=(0.5, 2.0),
                    metavar=('MIN', 'MAX'),
                    help='razón de alto aceptable entre el pedazo que nace y el que muere')
    ap.add_argument('--firmas', default=None,
                    help='JSON de tools/firmas_color.py con el color de cada rastro')
    ap.add_argument('--color', type=float, default=None,
                    help='diferencia de color máxima (Lab) para unir dos pedazos')
    ap.add_argument('--sin-unir', action='store_true')
    ap.add_argument('--salida', default=None)
    args = ap.parse_args()

    datos, rastros = cargar(args.json, args.min_cuadros, args.min_recorrido)
    if not rastros:
        sys.exit('Sin rastros con recorrido real')
    if args.accesos:
        modo_accesos(datos, rastros, args.accesos, args.json,
                     args.salida or args.json.replace('.json', '__accesos.png'),
                     hueco=args.hueco, tolerancia=args.tolerancia,
                     tamano=tuple(args.tamano), color=args.color,
                     firmas=json.load(open(args.firmas, encoding='utf-8')) if args.firmas else None)
        return

    roi = region_de_interes(rastros)
    fps = datos['fps']

    def partidos(rs):
        return sum(1 for r in rs if en_centro(_apoyo(r['p'][0]), roi, args.centro)
                   or en_centro(_apoyo(r['p'][-1]), roi, args.centro))

    print(f"{datos['cuadros']} cuadros ({datos['cuadros'] / fps / 60:.1f} min), "
          f"rastreador {datos['rastreador']}, {len(datos['rastros'])} rastros crudos, "
          f"{len(rastros)} con recorrido real")
    p0 = partidos(rastros)
    print(f"Partidos (empiezan o terminan en el centro): {p0} de {len(rastros)} "
          f"({100 * p0 / len(rastros):.0f} %)")

    if not args.sin_unir:
        rastros, uniones = unir_pedazos(rastros, roi, args.centro, fps,
                                        args.hueco, args.tolerancia)
        p1 = partidos(rastros)
        print(f"Tras unir {uniones} pedazos: {len(rastros)} vehículos, partidos {p1} "
              f"({100 * p1 / len(rastros):.0f} %)")

    completos = [r for r in rastros
                 if not en_centro(_apoyo(r['p'][0]), roi, args.centro)
                 and not en_centro(_apoyo(r['p'][-1]), roi, args.centro)]
    m_ent, m_sal = agrupar_extremos(completos, roi, args.centro)

    matriz = defaultdict(Counter)
    sin_mov = 0
    asignado = {}
    for r in rastros:
        o = _voto(m_ent, [_apoyo(p) for p in r['p'][:PUNTOS_POR_EXTREMO]], roi, args.centro)
        d = _voto(m_sal, [_apoyo(p) for p in r['p'][-PUNTOS_POR_EXTREMO:]], roi, args.centro)
        if o is None or d is None:
            sin_mov += 1
            continue
        matriz[o][d] += 1
        asignado[r['id']] = (o, d)

    n_ent = m_ent.n_clusters if m_ent is not None else 0
    n_sal = m_sal.n_clusters if m_sal is not None else 0
    print(f"\nEntradas halladas: {n_ent}   Salidas halladas: {n_sal}")
    print(f"Con movimiento asignado: {len(asignado)} de {len(rastros)} "
          f"({100 * len(asignado) / len(rastros):.0f} %)  sin asignar: {sin_mov}")
    print('\nMatriz origen (fila) -> destino (columna):')
    print('      ' + ''.join(f'S{j:<5}' for j in range(n_sal)))
    for i in range(n_ent):
        print(f'E{i:<4} ' + ''.join(f'{matriz[i][j]:<6}' for j in range(n_sal)))

    base = cv2.imread(args.json.replace('.json', '.jpg'))
    if base is None:
        base = np.zeros((datos['alto'], datos['ancho'], 3), np.uint8)
    img = base.copy()
    capa = np.zeros_like(img)
    movimientos = sorted({v for v in asignado.values()},
                         key=lambda m: -sum(1 for x in asignado.values() if x == m))
    color_de = {m: COLORES[i % len(COLORES)] for i, m in enumerate(movimientos)}
    for r in rastros:
        col = color_de.get(asignado.get(r['id']), (90, 90, 90))
        pts = [tuple(map(int, _apoyo(p))) for p in r['p']]
        for a, b in zip(pts, pts[1:]):
            cv2.line(capa, a, b, col, 1, cv2.LINE_AA)
    cv2.addWeighted(capa, 0.9, img, 1.0, 0, img)
    # Dónde nace (verde) y dónde muere (rojo) cada rastro: es lo que hay que
    # mirar para dibujar los accesos a mano.
    for r in rastros:
        a, b = _apoyo(r['p'][0]), _apoyo(r['p'][-1])
        cv2.circle(img, (int(a[0]), int(a[1])), 2, (0, 255, 0), -1)
        cv2.circle(img, (int(b[0]), int(b[1])), 2, (0, 0, 255), -1)
    for nombre, modelo, col in (('E', m_ent, (0, 255, 0)), ('S', m_sal, (0, 0, 255))):
        if modelo is None:
            continue
        for i, (cx, cy) in enumerate(modelo.cluster_centers_):
            cv2.circle(img, (int(cx), int(cy)), 6, col, 2)
            cv2.putText(img, f'{nombre}{i}', (int(cx) + 7, int(cy)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 2, cv2.LINE_AA)
    x0, y0, x1, y1 = roi
    mx, my = (x1 - x0) * args.centro, (y1 - y0) * args.centro
    cv2.rectangle(img, (int(x0 + mx), int(y0 + my)), (int(x1 - mx), int(y1 - my)),
                  (200, 200, 200), 1)
    salida = args.salida or args.json.replace('.json', '__od.png')
    cv2.imwrite(salida, img)

    resumen = {
        'rastros': len(rastros), 'asignados': len(asignado),
        'entradas': m_ent.cluster_centers_.round(1).tolist() if m_ent is not None else [],
        'salidas': m_sal.cluster_centers_.round(1).tolist() if m_sal is not None else [],
        'matriz': {f'E{o}': {f'S{d}': n for d, n in fila.items()} for o, fila in matriz.items()},
        'por_clase': {f'E{o}-S{d}': dict(Counter(r['clase'] for r in rastros
                                                  if asignado.get(r['id']) == (o, d)))
                      for (o, d) in movimientos},
    }
    with open(salida.replace('.png', '.json'), 'w', encoding='utf-8') as fh:
        json.dump(resumen, fh, ensure_ascii=False, indent=1)
    print(f'\n{salida}')


if __name__ == '__main__':
    main()
