"""
ByteTrack (de ultralytics) detrás de la misma interfaz que VehicleTracker.

Se usa para el aforo direccional y NO para el aforo por línea:

  · Direccional: en Entrada y salida Altozano (5 min, accesos dibujados)
    dejó 47 % de movimientos completos contra 15-16 % del rastreador propio.
    Su segunda pasada asocia las detecciones de baja confianza, que es lo
    que queda de un vehículo medio tapado; el propio las descarta a 0.25 y
    el rastro se parte a campo abierto.
  · Por línea: el conteo validado contra el aforo manual se hizo con el
    rastreador propio. Cambiarlo ahí exige volver a validarlo, así que no
    se toca.

Se usa el rastreador suelto y no model.track(): nuestro detector infiere
sobre una franja recortada y ampliada (set_detection_band), y model.track()
trabajaría sobre el cuadro completo con otro resultado de detección.
"""

import os
import types
from typing import Dict, List

import numpy as np

NOMBRES = {2: 'car', 3: 'motorcycle', 5: 'bus', 7: 'truck'}


class RastreadorBytetrack:
    # Confianza mínima que tiene que dejar pasar el detector para que exista
    # la segunda pasada (track_low_thresh de ultralytics es 0.1).
    CONF_MINIMA = 0.1

    def __init__(self, fps: float, ajustes: Dict = None):
        import yaml
        import ultralytics
        from ultralytics.engine.results import Boxes
        from ultralytics.trackers.byte_tracker import BYTETracker

        self._Boxes = Boxes
        ruta = os.path.join(os.path.dirname(ultralytics.__file__), 'cfg', 'trackers',
                            'bytetrack.yaml')
        with open(ruta, encoding='utf-8') as fh:
            opciones = types.SimpleNamespace(**yaml.safe_load(fh))
        for k, v in (ajustes or {}).items():
            setattr(opciones, k, v)
        # track_buffer se deja en el valor de ultralytics a propósito:
        # alargarlo no subió los movimientos completos (30/60/90 → 53/50/51 %
        # sobre las mismas detecciones); lo que recupera al vehículo tapado
        # es la unión de pedazos del motor direccional.
        opciones.frame_rate = int(round(fps or 15))
        # La firma cambió entre versiones: antes frame_rate iba aparte.
        try:
            self._t = BYTETracker(opciones, frame_rate=opciones.frame_rate)
        except TypeError:
            self._t = BYTETracker(opciones)

    def update(self, detections: List[Dict], frame) -> List[Dict]:
        if detections:
            datos = np.array([[*d['bbox'], d['confidence'], d['class_id']] for d in detections],
                             dtype=np.float32)
        else:
            datos = np.zeros((0, 6), dtype=np.float32)
        salida = self._t.update(self._Boxes(datos, frame.shape[:2]), frame)
        tracks = []
        for fila in salida:
            x1, y1, x2, y2, tid, conf, cls = fila[:7]
            tracks.append({
                'id': int(tid), 'bbox': [float(x1), float(y1), float(x2), float(y2)],
                'confidence': float(conf), 'class_id': int(cls),
                'class_name': NOMBRES.get(int(cls), str(int(cls))),
            })
        return tracks
