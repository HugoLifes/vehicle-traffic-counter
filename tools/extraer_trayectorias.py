"""
Guarda el recorrido COMPLETO de cada vehículo de un video, cuadro a cuadro.

El aforo por línea solo necesita saber que un vehículo cruzó. El aforo
direccional (origen-destino) necesita saber POR DÓNDE ENTRÓ y POR DÓNDE
SALIÓ, y eso exige que el rastro sobreviva todo el trayecto por la
intersección. Es la parte frágil: la literatura coincide en que el error
dominante del conteo por movimiento no es la detección sino el rastro que
se parte por una oclusión — un vehículo tapado por otro reaparece con otro
identificador y queda contado como dos movimientos a medias.

Detectar es lo caro. Por eso se puede separar en dos pasos:

  1. Detectar UNA vez en el Jetson y guardar las detecciones crudas:
       --guardar-detecciones data/od/det/X.json
  2. Rastrear desde ese archivo, en CPU y en segundos, tantas veces como
     haga falta para comparar rastreadores y parámetros:
       --desde-detecciones data/od/det/X.json --rastreador bytetrack --track-buffer 60

Las detecciones se guardan con confianza desde 0.1, que es lo que necesita
la segunda pasada de ByteTrack; el rastreador propio filtra por su cuenta
al umbral de producción.

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

NOMBRES = {2: 'car', 3: 'motorcycle', 5: 'bus', 7: 'truck'}
CONF_CRUDA = 0.1


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

    def __init__(self, tipo, fps, ajustes):
        import yaml
        import ultralytics
        from ultralytics.engine.results import Boxes
        self._Boxes = Boxes
        base = os.path.join(os.path.dirname(ultralytics.__file__), 'cfg', 'trackers')
        with open(os.path.join(base, f'{tipo}.yaml'), encoding='utf-8') as fh:
            opciones = types.SimpleNamespace(**yaml.safe_load(fh))
        for k, v in ajustes.items():
            if v is not None:
                setattr(opciones, k, v)
        if tipo == 'bytetrack':
            from ultralytics.trackers.byte_tracker import BYTETracker as clase
        else:
            from ultralytics.trackers.bot_sort import BOTSORT as clase
            opciones.with_reid = False
        # La firma cambió entre versiones de ultralytics: antes recibía
        # frame_rate aparte y en la 8.4 lo lee de las opciones. Se dan las
        # dos formas para no depender de la versión del contenedor.
        opciones.frame_rate = int(round(fps))
        try:
            self._t = clase(opciones, frame_rate=opciones.frame_rate)
        except TypeError:
            self._t = clase(opciones)
        self.opciones = opciones

    def update(self, dets, frame):
        if dets:
            datos = np.array([[*d['bbox'], d['confidence'], d['class_id']] for d in dets],
                             dtype=np.float32)
        else:
            datos = np.zeros((0, 6), dtype=np.float32)
        forma = frame.shape[:2] if frame is not None else self._forma
        salida = self._t.update(self._Boxes(datos, forma), frame)
        tracks = []
        for fila in salida:
            x1, y1, x2, y2, tid, conf, cls = fila[:7]
            tracks.append({'id': int(tid), 'bbox': [float(x1), float(y1), float(x2), float(y2)],
                           'confidence': float(conf), 'class_id': int(cls),
                           'class_name': NOMBRES.get(int(cls), str(int(cls)))})
        return tracks


def _fuente_video(args, cfg):
    """Genera (n, cuadro, detecciones) leyendo y detectando el video."""
    from src.detector import VehicleDetector
    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        sys.exit(f'No abre: {args.video}')
    fps = cap.get(cv2.CAP_PROP_FPS) or 15
    if args.desde:
        cap.set(cv2.CAP_PROP_POS_MSEC, args.desde * 60000)
    det = VehicleDetector(cfg.get('model_path', 'models/yolov8s.pt'), CONF_CRUDA,
                          cfg.get('iou_threshold', 0.5), args.imgsz, 'auto')
    det.set_detection_band(tuple(args.banda) if args.banda else None)
    tope = int(args.minutos * 60 * fps) if args.minutos else None

    def gen():
        n = 0
        while tope is None or n < tope:
            ok, f = cap.read()
            if not ok:
                break
            dets, _ = det.detect(f)
            yield n, f, dets
            n += 1
        cap.release()
    return fps, gen()


def _fuente_json(ruta):
    with open(ruta, encoding='utf-8') as fh:
        datos = json.load(fh)

    def gen():
        for n, cuadro in enumerate(datos['d']):
            dets = [{'bbox': d[:4], 'confidence': d[4], 'class_id': int(d[5]),
                     'class_name': NOMBRES.get(int(d[5]), str(int(d[5])))} for d in cuadro]
            yield n, None, dets
    return datos, gen()


def main():
    cfg = _config()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--video')
    ap.add_argument('--desde-detecciones', default=None,
                    help='rastrear desde detecciones guardadas, sin video ni GPU')
    ap.add_argument('--guardar-detecciones', default=None,
                    help='además de rastrear, guardar las detecciones crudas')
    ap.add_argument('--rastreador', choices=('propio', 'bytetrack', 'botsort'),
                    default='propio')
    ap.add_argument('--track-buffer', type=int, default=None,
                    help='ByteTrack: cuadros (a 30 fps) que se conserva un rastro perdido')
    ap.add_argument('--match-thresh', type=float, default=None)
    ap.add_argument('--track-high-thresh', type=float, default=None)
    ap.add_argument('--new-track-thresh', type=float, default=None)
    ap.add_argument('--max-age', type=int, default=None, help='propio: cuadros sin ver')
    ap.add_argument('--desde', type=float, default=0, help='minuto inicial')
    ap.add_argument('--minutos', type=float, default=0, help='0 = el video completo')
    ap.add_argument('--banda', type=int, nargs=2, metavar=('Y0', 'Y1'), default=None,
                    help='franja vertical donde detectar; por omisión el cuadro completo')
    ap.add_argument('--imgsz', type=int, default=cfg.get('input_size', 1280))
    ap.add_argument('--salida', default=None)
    args = ap.parse_args()
    if not args.video and not args.desde_detecciones:
        sys.exit('Hace falta --video o --desde-detecciones')

    if args.desde_detecciones:
        meta, fuente = _fuente_json(args.desde_detecciones)
        fps, ancho, alto = meta['fps'], meta['ancho'], meta['alto']
        video = meta['video']
        imagen = args.desde_detecciones.replace('.json', '.jpg')
    else:
        fps, fuente = _fuente_video(args, cfg)
        ancho = alto = None
        video = args.video
        imagen = None

    umbral_propio = cfg.get('confidence_threshold', 0.25)
    if args.rastreador == 'propio':
        from src.tracker import VehicleTracker
        t = dict(cfg.get('tracker', {}))
        if args.max_age is not None:
            t['max_age'] = args.max_age
        trk = VehicleTracker(max_age=t.get('max_age', 30), min_hits=t.get('min_hits', 3),
                             iou_threshold=t.get('iou_threshold', 0.3), config=t)
    else:
        trk = _RastreadorUltralytics(args.rastreador, fps, {
            'track_buffer': args.track_buffer, 'match_thresh': args.match_thresh,
            'track_high_thresh': args.track_high_thresh,
            'new_track_thresh': args.new_track_thresh,
        })
        trk._forma = (alto or 720, ancho or 1280)

    rastros = {}
    crudas = []
    primero = None
    n = 0
    inicio = time.time()
    for n, f, dets in fuente:
        if f is not None and primero is None:
            primero = f.copy()
            alto, ancho = f.shape[:2]
        if args.guardar_detecciones:
            crudas.append([[round(v, 1) for v in d['bbox']] + [round(d['confidence'], 3),
                                                              d['class_id']] for d in dets])
        if args.rastreador == 'propio':
            # El propio trabaja al umbral de producción, como el procesador.
            tracks = trk.update([d for d in dets if d['confidence'] >= umbral_propio])
        else:
            tracks = trk.update(dets, f)
        for tr in tracks:
            r = rastros.setdefault(tr['id'], {'clases': {}, 'p': []})
            x1, y1, x2, y2 = tr['bbox']
            r['p'].append([n, round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1),
                           round(tr['confidence'], 2)])
            r['clases'][tr['class_name']] = r['clases'].get(tr['class_name'], 0) + 1
        if (n + 1) % 1500 == 0:
            print(f'  {n + 1} cuadros, {(n + 1) / (time.time() - inicio):.1f} c/s, '
                  f'{len(rastros)} rastros', flush=True)
    cuadros = n + 1

    nombre = (os.path.basename(os.path.dirname(video)).replace(' ', '_') + '__'
              + os.path.splitext(os.path.basename(video))[0])
    etiqueta = args.rastreador
    if args.track_buffer is not None:
        etiqueta += f'_tb{args.track_buffer}'
    if args.match_thresh is not None:
        etiqueta += f'_mt{args.match_thresh}'
    if args.max_age is not None:
        etiqueta += f'_ma{args.max_age}'
    salida = args.salida or os.path.join('data', 'od', 'tray', f'{nombre}__{etiqueta}.json')
    os.makedirs(os.path.dirname(salida), exist_ok=True)

    if primero is not None:
        cv2.imwrite(salida.replace('.json', '.jpg'), primero)
    elif imagen and os.path.exists(imagen):
        import shutil
        shutil.copyfile(imagen, salida.replace('.json', '.jpg'))

    if args.guardar_detecciones:
        os.makedirs(os.path.dirname(args.guardar_detecciones) or '.', exist_ok=True)
        with open(args.guardar_detecciones, 'w', encoding='utf-8') as fh:
            json.dump({'video': video, 'fps': fps, 'ancho': ancho, 'alto': alto,
                       'conf_minima': CONF_CRUDA, 'd': crudas}, fh, separators=(',', ':'))
        if primero is not None:
            cv2.imwrite(args.guardar_detecciones.replace('.json', '.jpg'), primero)

    with open(salida, 'w', encoding='utf-8') as fh:
        json.dump({
            'video': video, 'rastreador': etiqueta, 'fps': fps,
            'ancho': ancho, 'alto': alto, 'desde_min': args.desde, 'cuadros': cuadros,
            # Cada punto: [cuadro, x1, y1, x2, y2, confianza]
            'rastros': {str(k): v for k, v in rastros.items()},
        }, fh, separators=(',', ':'))
    dur = time.time() - inicio
    print(f'{cuadros} cuadros en {dur / 60:.1f} min ({cuadros / dur:.1f} c/s), '
          f'{len(rastros)} rastros -> {salida}')


if __name__ == '__main__':
    main()
