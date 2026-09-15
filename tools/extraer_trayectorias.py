"""
Guarda el recorrido COMPLETO de cada vehículo de un video, cuadro a cuadro.

El aforo por línea solo necesita saber que un vehículo cruzó. El aforo
direccional (origen-destino) necesita saber POR DÓNDE ENTRÓ y POR DÓNDE
SALIÓ, y eso exige que el rastro sobreviva todo el trayecto por la
intersección. Es la parte frágil: la literatura coincide en que el error
dominante del conteo por movimiento no es la detección sino el rastro que
se parte por una oclusión — un vehículo tapado por otro reaparece con otro
identificador y queda contado como dos movimientos a medias.

Detectar es lo caro (6 min por cada 10 de video en el Jetson). Esto lo hace
una sola vez y deja un JSON; sobre él se prueban después, en segundos, las
zonas de acceso, la unión de rastros partidos y los rastreadores.

    python tools/extraer_trayectorias.py --video data/od_videos/X/07-49-57_2ta.mkv \\
        --rastreador bytetrack --minutos 5

Rastreadores:
  · propio     — IoU + Kalman de src/tracker.py, el que cuenta producción.
  · bytetrack  — el de ultralytics. Asocia en dos pasadas y la segunda usa
                 las detecciones de BAJA confianza, que es justo lo que
                 queda de un vehículo medio tapado.
  · botsort    — ByteTrack más compensación del movimiento de cámara.
"""

import argparse
import json
import os
import sys
import time
import types

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.detector import VehicleDetector   # noqa: E402
from src.tracker import VehicleTracker     # noqa: E402

NOMBRES = {2: 'car', 3: 'motorcycle', 5: 'bus', 7: 'truck'}


def _config():
    try:
        import yaml
        with open('configs/platform.yaml', encoding='utf-8') as fh:
            return yaml.safe_load(fh) or {}
    except OSError:
        return {}


class _RastreadorUltralytics:
    """Adapta BYTETracker/BOTSORT a la salida de nuestro detector.

    Se usa el rastreador suelto y no model.track() porque nuestro detector
    infiere sobre una franja recortada y ampliada (set_detection_band), y
    model.track() trabajaría sobre el cuadro completo: se estaría comparando
    otro detector, no otro rastreador.
    """

    def __init__(self, tipo, fps):
        import yaml
        import ultralytics
        from ultralytics.engine.results import Boxes
        self._Boxes = Boxes
        base = os.path.join(os.path.dirname(ultralytics.__file__), 'cfg', 'trackers')
        with open(os.path.join(base, f'{tipo}.yaml'), encoding='utf-8') as fh:
            opciones = types.SimpleNamespace(**yaml.safe_load(fh))
        if tipo == 'bytetrack':
            from ultralytics.trackers.byte_tracker import BYTETracker
            self._t = BYTETracker(opciones, frame_rate=int(round(fps)))
        else:
            from ultralytics.trackers.bot_sort import BOTSORT
            opciones.with_reid = False
            self._t = BOTSORT(opciones, frame_rate=int(round(fps)))
        self.umbral_bajo = getattr(opciones, 'track_low_thresh', 0.1)

    def update(self, dets, frame):
        if dets:
            datos = np.array([[*d['bbox'], d['confidence'], d['class_id']] for d in dets],
                             dtype=np.float32)
        else:
            datos = np.zeros((0, 6), dtype=np.float32)
        salida = self._t.update(self._Boxes(datos, frame.shape[:2]), frame)
        tracks = []
        for fila in salida:
            x1, y1, x2, y2, tid, conf, cls = fila[:7]
            tracks.append({'id': int(tid), 'bbox': [float(x1), float(y1), float(x2), float(y2)],
                           'confidence': float(conf), 'class_id': int(cls),
                           'class_name': NOMBRES.get(int(cls), str(int(cls)))})
        return tracks


def main():
    cfg = _config()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--video', required=True)
    ap.add_argument('--rastreador', choices=('propio', 'bytetrack', 'botsort'),
                    default='propio')
    ap.add_argument('--desde', type=float, default=0, help='minuto inicial')
    ap.add_argument('--minutos', type=float, default=0, help='0 = el video completo')
    ap.add_argument('--banda', type=int, nargs=2, metavar=('Y0', 'Y1'), default=None,
                    help='franja vertical donde detectar; por omisión el cuadro completo')
    ap.add_argument('--imgsz', type=int, default=cfg.get('input_size', 1280))
    ap.add_argument('--salida', default=None)
    args = ap.parse_args()

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        sys.exit(f'No abre: {args.video}')
    fps = cap.get(cv2.CAP_PROP_FPS) or 15
    if args.desde:
        cap.set(cv2.CAP_PROP_POS_MSEC, args.desde * 60000)

    # ByteTrack necesita ver las detecciones flojas para su segunda pasada;
    # con el umbral de producción (0.25) nunca le llegarían.
    if args.rastreador == 'propio':
        conf = cfg.get('confidence_threshold', 0.25)
    else:
        conf = 0.1
    det = VehicleDetector(cfg.get('model_path', 'models/yolov8s.pt'), conf,
                          cfg.get('iou_threshold', 0.5), args.imgsz, 'auto')
    det.set_detection_band(tuple(args.banda) if args.banda else None)

    if args.rastreador == 'propio':
        t = cfg.get('tracker', {})
        trk = VehicleTracker(max_age=t.get('max_age', 30), min_hits=t.get('min_hits', 3),
                             iou_threshold=t.get('iou_threshold', 0.3), config=t)
    else:
        trk = _RastreadorUltralytics(args.rastreador, fps)

    rastros = {}
    primero = None
    n = 0
    tope = int(args.minutos * 60 * fps) if args.minutos else None
    inicio = time.time()
    while tope is None or n < tope:
        ok, f = cap.read()
        if not ok:
            break
        if primero is None:
            primero = f.copy()
        dets, _ = det.detect(f)
        if args.rastreador == 'propio':
            tracks = trk.update(dets)
        else:
            tracks = trk.update(dets, f)
        for tr in tracks:
            r = rastros.setdefault(tr['id'], {'clases': {}, 'p': []})
            x1, y1, x2, y2 = tr['bbox']
            r['p'].append([n, round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1),
                           round(tr['confidence'], 2)])
            r['clases'][tr['class_name']] = r['clases'].get(tr['class_name'], 0) + 1
        n += 1
        if n % 1500 == 0:
            print(f'  {n} cuadros, {n / (time.time() - inicio):.1f} c/s, '
                  f'{len(rastros)} rastros', flush=True)
    cap.release()

    salida = args.salida or os.path.join(
        'data', 'od', 'tray',
        os.path.basename(os.path.dirname(args.video)).replace(' ', '_') + '__'
        + os.path.splitext(os.path.basename(args.video))[0] + f'__{args.rastreador}.json')
    os.makedirs(os.path.dirname(salida), exist_ok=True)
    if primero is not None:
        cv2.imwrite(salida.replace('.json', '.jpg'), primero)
    with open(salida, 'w', encoding='utf-8') as fh:
        json.dump({
            'video': args.video, 'rastreador': args.rastreador, 'fps': fps,
            'ancho': primero.shape[1] if primero is not None else None,
            'alto': primero.shape[0] if primero is not None else None,
            'desde_min': args.desde, 'cuadros': n,
            # Cada punto: [cuadro, x1, y1, x2, y2, confianza]
            'rastros': {str(k): v for k, v in rastros.items()},
        }, fh, separators=(',', ':'))
    dur = time.time() - inicio
    print(f'{n} cuadros en {dur / 60:.1f} min ({n / dur:.1f} c/s), '
          f'{len(rastros)} rastros -> {salida}')


if __name__ == '__main__':
    main()
