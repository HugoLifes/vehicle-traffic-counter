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


def _leer_zona(valor):
    if os.path.exists(valor):
        with open(valor, encoding='utf-8') as fh:
            texto = fh.read().strip()
        if texto.startswith('['):
            return json.loads(texto)
        return [[float(v) for v in renglon.split(',')] for renglon in texto.splitlines()
                if renglon.strip()]
    return json.loads(valor)


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
    ap.add_argument('--zona', action='append', default=None,
                    help='polígono donde se cuenta: JSON [[x,y],...] o archivo con '
                         'un "x,y" por renglón (formato ROI de AI City). Repetible.')
    a = ap.parse_args()

    det = VehicleDetector(cfg.get('model_path', 'models/yolov8s.pt'),
                          cfg.get('confidence_threshold', 0.25),
                          cfg.get('iou_threshold', 0.5),
                          cfg.get('input_size', 1280), 'auto')
    det.set_detection_band(None)
    zonas = [_leer_zona(z) for z in a.zona] if a.zona else None
    m = medir_imagen(a.video, det, a.muestras, zonas=zonas)
    # Un video que no abre no es un encuadre malo. Antes salía "NO SIRVE
    # (0/100), puede estar de noche o desenfocado": pasó con 30 videos de AI
    # City cuya ruta llevaba un retorno de carro invisible de la lista.
    if m.get('error'):
        sys.exit(f'No se pudo leer el video {a.video!r}: {m["error"]}. '
                 'Revisa la ruta; no es un veredicto sobre el encuadre.')
    m.pop('_ejemplo', None)
    imagen = calificar(m, direccional=a.direccional)

    rastreo = None
    if not a.solo_imagen and imagen['puntaje'] > 0:
        # ByteTrack necesita ver las detecciones flojas para su segunda pasada.
        det.confidence_threshold = min(det.confidence_threshold, RastreadorBytetrack.CONF_MINIMA)
        rastreo = medir_rastreo(a.video, det, a.minutos, zonas=zonas)
        rastreo = dict(rastreo, **calificar_rastreo(
            rastreo, m.get('detecciones_por_cuadro')))

    d = combinar(imagen, rastreo)
    print(f"\n{os.path.basename(a.video)}")
    print(f"  {m.get('resolucion')}, {m.get('fps')} fps, {m.get('kbps')} kb/s")
    print(f"  medido en: {m.get('region')}")
    print(f"  vehículo {m.get('alto_mediana') or 0:.0f} px de alto, confianza {m.get('confianza')}, "
          f"brillo {m.get('brillo')}, nitidez {m.get('nitidez')}")
    if rastreo:
        nota = '' if rastreo.get('concluyente', True) else '  (no concluyente: poco tránsito)'
        print(f"  rastreo: {rastreo['rastros']} vehículos, extremos en 6 celdas "
              f"{rastreo['concentracion']:.0f} %, en la orilla {rastreo['borde']:.0f} %, "
              f"partidos {rastreo['partidos_pct']:.0f} %{nota}")
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
