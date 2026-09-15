"""
Vuelve a contar videos ya procesados SIN escribir en la base, con el
rastreador viejo y el corregido a la vez, y compara los dos contra lo que
hay guardado y contra el aforo manual.

Existe porque la corrección del rastreador (predict una vez por cuadro,
ver src/tracker.py) toca el aforo por línea que ya está validado contra el
conteo manual. Reprocesar el proyecto con "Volver a contar" borraría los
cruces validados antes de saber si el cambio mejora o empeora. Aquí se
decide con números y la base no se toca.

Una sola detección por cuadro alimenta a los DOS rastreadores: así la
diferencia entre ellos es solo del rastreador, no del ruido del detector.
La columna "viejo" debe reproducir lo guardado en la base; si no, la
emulación no es fiel y la comparación no vale.

    python tools/recontar_sin_guardar.py --proyecto 2 --jobs 89 90 91 92 93 94
"""

import argparse
import importlib.util
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import yaml

# La raíz del repo es el directorio de trabajo cuando ahí está src/ (en el
# Jetson las herramientas de prueba viven en data/od/herramientas, montado,
# y se corren desde /app); si no, la carpeta padre de tools/.
RAIZ = Path.cwd() if (Path.cwd() / 'src').is_dir() else Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src.detector import VehicleDetector                          # noqa: E402
from src.engine.lanes import build_lane_counters                  # noqa: E402
from src.engine.zones import (band_from_zones, filter_detections,  # noqa: E402
                              load_zones, zone_for_bbox)
from src.tracker import VehicleTracker                            # noqa: E402

BD = RAIZ / 'data' / 'traffic.db'


class RastreadorViejo(VehicleTracker):
    """El comportamiento anterior a la corrección, para compararlo con los
    mismos cuadros: predict() dentro del doble ciclo, sumando edad y
    ausencia una vez por cada detección."""

    def update(self, detections):
        self.frame_count += 1
        tracks = self.tracks
        if not tracks:
            matches, sin_det, sin_trk = [], list(range(len(detections))), []
        elif not detections:
            matches, sin_det, sin_trk = [], [], list(range(len(tracks)))
        else:
            import numpy as np
            from scipy.optimize import linear_sum_assignment
            costo = np.zeros((len(detections), len(tracks)))
            for d, det in enumerate(detections):
                for t, trk in enumerate(tracks):
                    pred = trk.predict()
                    trk.age += 1
                    trk.miss_streak += 1
                    costo[d, t] = 1 - self.calculate_iou(det['bbox'], pred)
            filas, cols = linear_sum_assignment(costo)
            matches, sin_det, sin_trk = [], [], list(range(len(tracks)))
            for d, t in zip(filas, cols):
                if 1 - costo[d, t] >= self.iou_threshold:
                    matches.append((d, t))
                    sin_trk.remove(t)
                else:
                    sin_det.append(d)
            # Igual que el original, incluido su duplicado: una detección
            # cuyo mejor emparejamiento tuvo IoU bajo entra dos veces aquí y
            # crea dos rastros. Se conserva para que "viejo" reproduzca la base.
            usados = {m[0] for m in matches}
            sin_det.extend(list(set(range(len(detections))) - usados))

        for d, t in matches:
            tracks[t].update(bbox=detections[d]['bbox'], confidence=detections[d]['confidence'],
                             frame_number=self.frame_count)
            tracks[t].age -= 1          # el update corregido suma edad; el viejo no
        for t in sin_trk:
            tracks[t].mark_missed()
        from src.tracker import Track
        for d in sin_det:
            det = detections[d]
            nuevo = Track(bbox=det['bbox'], class_id=det['class_id'], class_name=det['class_name'],
                          confidence=det['confidence'], buffer_size=self.buffer_size)
            self.tracks.append(nuevo)
            self.total_tracks_created += 1
        for trk in self.tracks:
            if not trk.is_confirmed and trk.hits >= self.min_hits:
                trk.is_confirmed = True
        self.tracks = [trk for trk in self.tracks if trk.miss_streak <= self.max_age]
        return [trk.get_state() for trk in self.tracks if trk.is_confirmed]


def _comparador():
    ruta = RAIZ / 'tools' / 'comparar_aforo_real.py'
    spec = importlib.util.spec_from_file_location('comparar_aforo_real', ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def contar_video(job, cfg, det):
    cap = cv2.VideoCapture(job['stored_path'])
    fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
    alto = int(cap.get(4))
    ancho = int(cap.get(3))
    zonas = load_zones(job['project_id'])
    nombre_zona = {z['id']: z['name'] for z in zonas}
    banda = band_from_zones(zonas, alto) if zonas else None
    det.set_detection_band(banda)
    inicio = datetime.fromisoformat(job['video_start_time'])

    t = cfg.get('tracker', {})
    variantes = {}
    for nombre, clase in (('viejo', RastreadorViejo), ('corregido', VehicleTracker)):
        contadores, meta = build_lane_counters(job['source_label'], alto, ancho,
                                               project_id=job['project_id'])
        variantes[nombre] = {
            'trk': clase(max_age=t.get('max_age', 30), min_hits=t.get('min_hits', 3),
                         iou_threshold=t.get('iou_threshold', 0.3), config=t),
            'contadores': contadores, 'meta': meta,
            'cuenta': defaultdict(lambda: defaultdict(int)),
        }

    n = 0
    while True:
        ok, cuadro = cap.read()
        if not ok:
            break
        dets, _ = det.detect(cuadro)
        dets = filter_detections(zonas, dets)
        minuto = inicio + timedelta(seconds=n / fps)
        bin_ = (minuto.hour * 60 + minuto.minute) // 15 * 15
        for v in variantes.values():
            # Copia de las detecciones: el rastreador no debe ver lo que
            # el otro haya modificado.
            tracks = v['trk'].update([dict(d) for d in dets])
            for lane_id, contador in v['contadores'].items():
                zona = v['meta'][lane_id].get('zone_id')
                vistos = [x for x in tracks if zone_for_bbox(zonas, x['bbox']) == zona] \
                    if zona and zonas else tracks
                cruces = contador.update(vistos)
                for c in cruces['in'] + cruces['out']:
                    trk = next((x for x in vistos if x['id'] == c['track_id']), None)
                    z = zone_for_bbox(zonas, trk['bbox']) if trk and zonas else None
                    v['cuenta'][nombre_zona.get(z, 'sin zona')][bin_] += 1
        n += 1
    cap.release()
    return {k: v['cuenta'] for k, v in variantes.items()}


def guardado(job_ids):
    con = sqlite3.connect(f'file:{BD}?mode=ro', uri=True)
    cuenta = defaultdict(lambda: defaultdict(int))
    for zona, ts in con.execute(
        f"select z.name, x.timestamp from crossings x left join zones z on z.id = x.zone_id "
        f"where x.job_id in ({','.join('?' * len(job_ids))})", job_ids):
        m = int(ts[11:13]) * 60 + int(ts[14:16])
        cuenta[zona or 'sin zona'][m // 15 * 15] += 1
    con.close()
    return cuenta


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--proyecto', type=int, required=True)
    ap.add_argument('--jobs', type=int, nargs='+', required=True)
    args = ap.parse_args()

    with open(RAIZ / 'configs' / 'platform.yaml', encoding='utf-8') as fh:
        cfg = yaml.safe_load(fh) or {}
    dcfg = cfg.get('detector', {})
    det = VehicleDetector(model_path=cfg.get('model_path', 'models/yolov8s.pt'),
                          confidence_threshold=cfg.get('confidence_threshold', 0.25),
                          iou_threshold=dcfg.get('iou_threshold', 0.5),
                          input_size=dcfg.get('input_size', 640),
                          device=cfg.get('device', 'auto'), config=dcfg)

    con = sqlite3.connect(f'file:{BD}?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    jobs = [dict(con.execute("select * from video_jobs where id = ? and project_id = ?",
                             (j, args.proyecto)).fetchone() or {}) for j in args.jobs]
    con.close()
    jobs = [j for j in jobs if j]

    total = {'viejo': defaultdict(lambda: defaultdict(int)),
             'corregido': defaultdict(lambda: defaultdict(int))}
    for job in jobs:
        print(f"  contando {job['original_name']} ({job['video_start_time']})", flush=True)
        res = contar_video(job, cfg, det)
        for var, por_zona in res.items():
            for zona, bins in por_zona.items():
                for b, v in bins.items():
                    total[var][zona][b] += v
    base = guardado([j['id'] for j in jobs])

    comp = _comparador()
    real = comp.cargar_referencia(comp.REFERENCIAS, 'manual')
    bins = sorted({b for var in total.values() for z in var.values() for b in z}
                  | {b for z in base.values() for b in z})
    # Solo cuartos de hora completos dentro de lo recontado.
    minutos = set()
    for job in jobs:
        h, m, _ = map(int, job['video_start_time'][11:].split(':'))
        dur = int((job['total_frames'] or 0) / (job['fps'] or 15) / 60)
        minutos.update(range(h * 60 + m, h * 60 + m + dur))
    bins = [b for b in bins if all(x in minutos for x in range(b, b + 15))]
    pares = comp.emparejar(real, {k: dict(v) for k, v in base.items()}, bins)

    print(f"\nCuartos de hora comparables: {len(bins)}")
    print(f"{'calzada':<18}{'guardado':>9}{'viejo':>8}{'corregido':>10}{'manual':>8}"
          f"{'viejo %':>9}{'corr. %':>9}")
    tg = tv = tc = tm = 0
    for zona, (sentido, _) in sorted(pares.items()):
        g = sum(base[zona].get(b, 0) for b in bins)
        v = sum(total['viejo'][zona].get(b, 0) for b in bins)
        c = sum(total['corregido'][zona].get(b, 0) for b in bins)
        m = int(sum(real[sentido].get(b, 0) for b in bins)) if sentido else 0
        tg, tv, tc, tm = tg + g, tv + v, tc + c, tm + m
        print(f"{zona:<18}{g:>9}{v:>8}{c:>10}{m:>8}"
              f"{(100 * v / m if m else 0):>8.0f}%{(100 * c / m if m else 0):>8.0f}%")
    print(f"{'AMBAS':<18}{tg:>9}{tv:>8}{tc:>10}{tm:>8}"
          f"{(100 * tv / tm if tm else 0):>8.0f}%{(100 * tc / tm if tm else 0):>8.0f}%")

    print('\nPor cuarto de hora (ambas calzadas): guardado / viejo / corregido / manual')
    for b in bins:
        g = sum(base[z].get(b, 0) for z in base)
        v = sum(total['viejo'][z].get(b, 0) for z in total['viejo'])
        c = sum(total['corregido'][z].get(b, 0) for z in total['corregido'])
        m = int(sum(real[s].get(b, 0) for s in real))
        print(f"  {b // 60:02d}:{b % 60:02d}  {g:>5} {v:>5} {c:>5} {m:>5}")


if __name__ == '__main__':
    main()
