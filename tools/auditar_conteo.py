"""
Auditoría del conteo SIN conteo manual de campo.

De un aforo nuevo casi nunca hay conteo de referencia, y sin referencia no
hay razón que reportar. Lo que sí se puede hacer es **acotar el error** con
dos comprobaciones que no dependen del detector ni una de la otra:

1. `--barrido` (no usa GPU). Sobre la franja de píxeles de la línea de
   conteo, cuadro a cuadro, un lazo virtual cuenta las manchas que dejan los
   vehículos. Es una segunda opinión hecha del video crudo. Tiene sus
   propios defectos conocidos —pierde motos y junta vehículos que cruzan
   pegados— así que sirve para tamizar qué minutos mirar, no para dar una
   razón.

2. `--consistencia` (usa GPU, no correr con la cola contando). Conservación
   de flujo: se cuenta con la línea puesta también unos píxeles antes y
   después. En un tramo sin salidas intermedias, el vehículo que cruza la
   primera tiene que cruzar las tres. Lo que se pierde entre ellas es error
   del rastreo, y se mide sin que nadie cuente a mano.

    python tools/auditar_conteo.py --proyecto 7 --barrido
    python tools/auditar_conteo.py --proyecto 7 --consistencia --muestra 12

Lo que NINGUNA de las dos ve es el vehículo que el detector nunca vio: para
eso hace falta el conteo manual, o mirar el barrido a ojo.
"""

import argparse
import json
import os
import sys
from collections import defaultdict

import cv2
import numpy as np

# La raíz del repo es el directorio de trabajo cuando ahí está src/ (en el
# Jetson las herramientas se copian a data/ y se corren desde /app); si no,
# la carpeta padre de tools/.
from pathlib import Path                                           # noqa: E402
RAIZ = str(Path.cwd()) if (Path.cwd() / 'src').is_dir() else os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, 'tools'))

from barrido_linea import contar_rayas, muestrear                  # noqa: E402
from src.storage import traffic_db                                 # noqa: E402

# Cuánto se mueve la línea para la prueba de conservación de flujo, en
# píxeles. Lo bastante para que sean posiciones distintas del rastro y lo
# bastante poco para que no haya salidas de la vía entre ellas.
DESPLAZAMIENTO = 60


def videos_contados(proyecto):
    conn = traffic_db.get_connection()
    return conn.execute(
        """SELECT id, original_name, stored_path, video_start_time, fps
           FROM video_jobs WHERE project_id = ? AND status = 'done'
           ORDER BY video_start_time""", (proyecto,)).fetchall()


def auditar_barrido(proyecto, limite=None):
    conn = traffic_db.get_connection()
    carriles = traffic_db.list_lanes(project_id=proyecto)
    filas = []
    for job in videos_contados(proyecto)[:limite]:
        cap = cv2.VideoCapture(job['stored_path'])
        if not cap.isOpened():
            continue
        tiras = {c['id']: [] for c in carriles}
        while True:
            ok, f = cap.read()
            if not ok:
                break
            for c in carriles:
                p = c['points']
                tiras[c['id']].append(muestrear(f, tuple(p[0]), tuple(p[1]), 260, 6))
        cap.release()
        fila = {'video': job['original_name'], 'hora': (job['video_start_time'] or '')[11:13]}
        for c in carriles:
            if not tiras[c['id']]:
                continue
            manchas, _ = contar_rayas(np.stack(tiras[c['id']], axis=1))
            sistema = conn.execute(
                "SELECT COUNT(*) FROM crossings WHERE job_id=? AND lane_id=?",
                (job['id'], c['id'])).fetchone()[0]
            fila[c['name']] = {'sistema': sistema, 'lazo': len(manchas)}
        filas.append(fila)
        print(json.dumps(fila, ensure_ascii=False), flush=True)
    return filas


def auditar_consistencia(proyecto, muestra):
    import yaml
    from src.detector import VehicleDetector
    from src.counter import BidirectionalCounter
    from src.engine.zones import (band_from_zones, filter_detections, load_zones,
                                  zone_for_bbox)
    from src.tracker import VehicleTracker

    cfg = yaml.safe_load(open(os.path.join(RAIZ, 'configs', 'platform.yaml'))) or {}
    zonas = load_zones(proyecto)
    datos = traffic_db.get_project(proyecto) or {}
    carriles = traffic_db.list_lanes(project_id=proyecto)
    jobs = videos_contados(proyecto)
    # Repartidos a lo largo del día, no los primeros: la exactitud cambia con
    # la hora y con el tránsito.
    paso = max(1, len(jobs) // max(1, muestra))
    jobs = jobs[::paso][:muestra]

    filas = []
    for job in jobs:
        cap = cv2.VideoCapture(job['stored_path'])
        if not cap.isOpened():
            continue
        alto, ancho = int(cap.get(4)), int(cap.get(3))
        det = VehicleDetector(cfg.get('model_path'), cfg.get('confidence_threshold', 0.25),
                              cfg.get('iou_threshold', 0.5), cfg.get('input_size', 1280),
                              'auto')
        det.nms_agnostico = bool(datos.get('nms_agnostico'))
        det.set_detection_band(band_from_zones(zonas, alto) if zonas else None)
        t = dict(cfg.get('tracker', {}))
        trk = VehicleTracker(max_age=t.get('max_age', 30), min_hits=t.get('min_hits', 3),
                             iou_threshold=t.get('iou_threshold', 0.3), config=t)
        contadores = {}
        for c in carriles:
            for nombre, dy in (('antes', -DESPLAZAMIENTO), ('linea', 0),
                               ('despues', DESPLAZAMIENTO)):
                cont = BidirectionalCounter(line_type='diagonal')
                cont.set_counting_line(
                    line_type='diagonal',
                    points=[(p[0], p[1] + dy) for p in c['points']],
                    frame_shape=(alto, ancho))
                contadores[(c['id'], nombre)] = cont
        vistos = defaultdict(set)
        while True:
            ok, f = cap.read()
            if not ok:
                break
            tracks = trk.update(filter_detections(zonas, det.detect(f)[0]))
            for c in carriles:
                zona = c.get('zone_id')
                propios = [tr for tr in tracks
                           if not zona or zone_for_bbox(zonas, tr['bbox']) == zona]
                for nombre in ('antes', 'linea', 'despues'):
                    r = contadores[(c['id'], nombre)].update(propios)
                    for cr in r['in'] + r['out']:
                        vistos[(c['id'], nombre)].add(cr['track_id'])
        cap.release()

        fila = {'video': job['original_name'], 'hora': (job['video_start_time'] or '')[11:13]}
        for c in carriles:
            a = vistos[(c['id'], 'antes')]
            m = vistos[(c['id'], 'linea')]
            d = vistos[(c['id'], 'despues')]
            union = a | m | d
            las_tres = a & m & d
            fila[c['name']] = {
                'antes': len(a), 'linea': len(m), 'despues': len(d),
                'en_las_tres': len(las_tres),
                'consistencia': round(len(las_tres) / len(union), 3) if union else None,
            }
        filas.append(fila)
        print(json.dumps(fila, ensure_ascii=False), flush=True)
    return filas


def resumir(filas, claves):
    por_hora = defaultdict(lambda: defaultdict(int))
    for f in filas:
        for nombre, v in f.items():
            if not isinstance(v, dict):
                continue
            for k in claves:
                if v.get(k) is not None:
                    por_hora[(f['hora'], nombre)][k] += v[k]
    return por_hora


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--proyecto', type=int, required=True)
    ap.add_argument('--barrido', action='store_true')
    ap.add_argument('--consistencia', action='store_true')
    ap.add_argument('--muestra', type=int, default=12, help='videos de la muestra')
    ap.add_argument('--limite', type=int, default=None, help='tope de videos (--barrido)')
    ap.add_argument('--salida', default=None)
    a = ap.parse_args()

    if not a.barrido and not a.consistencia:
        sys.exit('Elige --barrido (sin GPU) o --consistencia (con GPU)')

    filas = []
    if a.barrido:
        filas = auditar_barrido(a.proyecto, a.limite)
        por_hora = resumir(filas, ('sistema', 'lazo'))
        print(f"\n{'hora':>5} {'carril':26} {'sistema':>8} {'lazo':>6} {'razon':>7}")
        for (hora, carril), v in sorted(por_hora.items()):
            r = v['sistema'] / v['lazo'] if v['lazo'] else 0
            print(f"{hora:>5} {carril[:26]:26} {v['sistema']:>8} {v['lazo']:>6} {r:>7.2f}")
    if a.consistencia:
        filas += auditar_consistencia(a.proyecto, a.muestra)
        por_hora = resumir(filas, ('linea', 'en_las_tres'))
        print(f"\n{'hora':>5} {'carril':26} {'en la linea':>12} {'en las tres':>12} {'consistencia':>13}")
        for (hora, carril), v in sorted(por_hora.items()):
            if not v.get('linea'):
                continue
            c = v['en_las_tres'] / v['linea']
            print(f"{hora:>5} {carril[:26]:26} {v['linea']:>12} {v['en_las_tres']:>12} {c:>13.3f}")

    if a.salida:
        with open(a.salida, 'w', encoding='utf-8') as fh:
            json.dump(filas, fh, indent=1, ensure_ascii=False)
        print(f'\n{a.salida}')


if __name__ == '__main__':
    main()
