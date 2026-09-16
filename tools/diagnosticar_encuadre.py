"""
¿Este video sirve para aforar? Diagnóstico en dos etapas, antes de procesar.

Existe porque descubrirlo contando cuesta horas: Blvd Independencia se contó
4 h para concluir que el puente tapa dos accesos, y la Glorieta 1.5 h para
ver que solo se veía un tercio del tránsito.

  Etapa 1 — por imagen (segundos): tamaño del vehículo, exposición, nitidez
  y confianza del detector sobre unos cuadros de muestra.
  Etapa 2 — por rastreo (un minuto): dónde nacen y mueren los rastros. Si se
  concentran en pocos puntos, se ve por dónde entra y sale cada vehículo; si
  están regados a media escena, algo los tapa o el acceso queda fuera.

La etapa 1 sola NO alcanza: calificaba mejor a Blvd Independencia (41 px,
que falló) que a Entrada y salida Altozano (43 px, el único que sirvió).

    python tools/diagnosticar_encuadre.py VIDEO.mkv [--minutos 1] [--json salida.json]
"""

import argparse
import json
import os
import sys
from collections import Counter

import cv2

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, 'tools'))

from src.detector import VehicleDetector                          # noqa: E402
from src.engine.diagnostico_encuadre import (calificar,           # noqa: E402
                                             calificar_rastreo, combinar,
                                             medir_imagen, medir_rastreo,
                                             resumen_texto)
from src.engine.rastreo_bytetrack import RastreadorBytetrack      # noqa: E402


def _config():
    try:
        import yaml
        with open(os.path.join(RAIZ, 'configs', 'platform.yaml'), encoding='utf-8') as fh:
            return yaml.safe_load(fh) or {}
    except OSError:
        return {}


def main():
    cfg = _config()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('video')
    ap.add_argument('--minutos', type=float, default=1.0, help='minutos de rastreo (etapa 2)')
    ap.add_argument('--muestras', type=int, default=10, help='cuadros de muestra (etapa 1)')
    ap.add_argument('--direccional', action='store_true',
                    help='califica para aforo direccional, que exige más')
    ap.add_argument('--solo-imagen', action='store_true', help='omitir la etapa de rastreo')
    ap.add_argument('--json', dest='salida_json', default=None)
    a = ap.parse_args()

    det = VehicleDetector(cfg.get('model_path', 'models/yolov8s.pt'),
                          cfg.get('confidence_threshold', 0.25),
                          cfg.get('iou_threshold', 0.5),
                          cfg.get('input_size', 1280), 'auto')
    det.set_detection_band(None)
    m = medir_imagen(a.video, det, a.muestras)
    m.pop('_ejemplo', None)
    imagen = calificar(m, direccional=a.direccional)

    rastreo = None
    if not a.solo_imagen and imagen['puntaje'] > 0:
        # ByteTrack necesita ver las detecciones flojas para su segunda pasada.
        det.confidence_threshold = min(det.confidence_threshold, RastreadorBytetrack.CONF_MINIMA)
        rastreo = medir_rastreo(a.video, det, a.minutos)
        rastreo = dict(rastreo, **calificar_rastreo(rastreo))

    d = combinar(imagen, rastreo)
    print(f"\n{os.path.basename(a.video)}")
    print(f"  {m.get('resolucion')}, {m.get('fps')} fps, {m.get('kbps')} kb/s")
    print(f"  vehículo {m.get('alto_mediana', 0):.0f} px de alto, confianza {m.get('confianza')}, "
          f"brillo {m.get('brillo')}, nitidez {m.get('nitidez')}")
    if rastreo:
        print(f"  rastreo: {rastreo['rastros']} vehículos, extremos en 6 celdas "
              f"{rastreo['concentracion']:.0f} %, en la orilla {rastreo['borde']:.0f} %, "
              f"partidos {rastreo['partidos_pct']:.0f} %")
    print(f"\n  {resumen_texto(d)}")
    for av in d['avisos']:
        print(f"   · {av}")
    if a.salida_json:
        with open(a.salida_json, 'w', encoding='utf-8') as fh:
            json.dump({'medidas': m, 'rastreo': rastreo, 'diagnostico': d}, fh,
                      ensure_ascii=False, indent=1)
        print(f"\n{a.salida_json}")


if __name__ == '__main__':
    main()
