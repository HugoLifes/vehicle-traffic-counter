"""
Contar por INSTANTE contra contar por TRAYECTORIA, sobre la misma detección.

Los dos métodos comparten detector, franja, filtro de zonas y rastreador; lo
único que cambia es cómo se decide el cruce, así que la diferencia es del
método y no del ruido del detector — la misma idea de
`recontar_sin_guardar.py` para el cambio de rastreador.

    python tools/comparar_metodo_conteo.py --proyecto 7 --jobs 166 167 168

Imprime, por video y por carril, lo que cuenta cada método y lo que hay
guardado en la base. No escribe nada.
"""

import argparse
import os
import sys
from collections import Counter

import cv2
import yaml

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from src.detector import VehicleDetector                            # noqa: E402
from src.engine import conteo_trayectoria                           # noqa: E402
from src.engine.lanes import build_lane_counters                    # noqa: E402
from src.engine.zones import (band_from_zones, filter_detections,   # noqa: E402
                              load_zones, zone_for_bbox, zone_for_point)
from src.storage import traffic_db                                  # noqa: E402
from src.tracker import VehicleTracker                              # noqa: E402


def procesar(job, cfg):
    zonas = load_zones(job['project_id'])
    proyecto = traffic_db.get_project(job['project_id']) or {}
    cap = cv2.VideoCapture(job['stored_path'])
    if not cap.isOpened():
        return None
    alto, ancho = int(cap.get(4)), int(cap.get(3))
    fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
    det = VehicleDetector(cfg.get('model_path'), cfg.get('confidence_threshold', 0.25),
                          cfg.get('iou_threshold', 0.5), cfg.get('input_size', 1280), 'auto')
    det.nms_agnostico = bool(proyecto.get('nms_agnostico'))
    det.set_detection_band(band_from_zones(zonas, alto) if zonas else None)
    t = dict(cfg.get('tracker', {}))
    trk = VehicleTracker(max_age=t.get('max_age', 30), min_hits=t.get('min_hits', 3),
                         iou_threshold=t.get('iou_threshold', 0.3), config=t)
    contadores, meta = build_lane_counters(job.get('source_label') or '', alto, ancho,
                                           project_id=job['project_id'])
    recorridos = {}
    instante = Counter()
    n = 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        dets = filter_detections(zonas, det.detect(f)[0])
        tracks = trk.update(dets)
        for tr in tracks:
            x1, y1, x2, y2 = tr['bbox']
            recorridos.setdefault(tr['id'], []).append((n, x1, y1, x2, y2))
        for lane_id, contador in contadores.items():
            zona = meta[lane_id].get('zone_id')
            vistos = [tr for tr in tracks
                      if not zona or zone_for_bbox(zonas, tr['bbox']) == zona]
            r = contador.update(vistos)
            instante[lane_id] += len(r['in']) + len(r['out'])
        n += 1
    cap.release()

    lineas = [{'id': lid, 'puntos': m['points'], 'zone_id': m.get('zone_id')}
              for lid, m in meta.items()]
    cruces = conteo_trayectoria.contar(
        recorridos, lineas, fps,
        (lambda x, y: zone_for_point(zonas, x, y)) if zonas else None)
    return meta, instante, {lid: len(v) for lid, v in cruces.items()}, n


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--proyecto', type=int, required=True)
    ap.add_argument('--jobs', type=int, nargs='+', required=True)
    a = ap.parse_args()

    cfg = yaml.safe_load(open(os.path.join(RAIZ, 'configs', 'platform.yaml'))) or {}
    conn = traffic_db.get_connection()
    totales = Counter()
    print(f"{'video':16} {'carril':26} {'guardado':>9} {'instante':>9} {'trayectoria':>12}")
    for job_id in a.jobs:
        job = traffic_db.get_video_job(job_id)
        if job is None or job.get('project_id') != a.proyecto:
            print(f'  job {job_id}: no es de este proyecto')
            continue
        salida = procesar(job, cfg)
        if salida is None:
            print(f"  job {job_id}: no se pudo abrir {job['stored_path']}")
            continue
        meta, instante, trayectoria, n = salida
        for lane_id, m in meta.items():
            guardado = conn.execute(
                "SELECT COUNT(*) FROM crossings WHERE job_id=? AND lane_id=?",
                (job_id, lane_id)).fetchone()[0]
            print(f"{job['original_name'][:16]:16} {m['name'][:26]:26} {guardado:>9} "
                  f"{instante[lane_id]:>9} {trayectoria[lane_id]:>12}")
            totales['guardado'] += guardado
            totales['instante'] += instante[lane_id]
            totales['trayectoria'] += trayectoria[lane_id]
    print(f"\nTOTAL  guardado {totales['guardado']}  instante {totales['instante']}  "
          f"trayectoria {totales['trayectoria']}")
    if totales['instante']:
        print(f"trayectoria / instante = "
              f"{totales['trayectoria'] / totales['instante']:.3f}")


if __name__ == '__main__':
    main()
