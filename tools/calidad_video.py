"""
¿Cuánto trae una grabación? Mide la calidad de videos que todavía no son
proyecto de la plataforma, antes de invertir horas en contarlos.

El límite de este sistema es el tamaño del vehículo en píxeles, no el
software (ver CLAUDE.md): con 36 px de alto se cuenta al 99 %, con 14 px no
se clasifica. Así que la cifra que decide si un video sirve no es la
resolución del archivo sino el ALTO DE LOS VEHÍCULOS dentro de él, y eso
solo se sabe detectando.

Por cada video toma cuadros repartidos a lo largo de la grabación y mide:
  · resolución, fps y bitrate real del archivo;
  · brillo y contraste (la noche sobreexpone, no oscurece);
  · nitidez, como varianza del laplaciano (el movimiento barrido la hunde);
  · alto de los vehículos detectados y su confianza.

Agrupa por la carpeta que contiene los videos, que en el material de la
empresa es el nombre del aforo.

    python tools/calidad_video.py data/od_videos --salida data/od/calidad
"""

import argparse
import glob
import json
import os
import statistics
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.detector import VehicleDetector   # noqa: E402
from src.engine.diagnostico_encuadre import medir_imagen   # noqa: E402

EXTENSIONES = ('.mkv', '.mp4', '.avi', '.mov', '.ts')


def _config():
    try:
        import yaml
        with open('configs/platform.yaml', encoding='utf-8') as fh:
            return yaml.safe_load(fh) or {}
    except OSError:
        return {}


def _percentil(valores, p):
    if not valores:
        return None
    v = sorted(valores)
    return v[min(len(v) - 1, int(p * len(v)))]


def medir(ruta, det, muestras):
    """Las medidas las hace el motor (src/engine/diagnostico_encuadre), que
    es el mismo que usan el diagnóstico y la API: si cada herramienta tuviera
    su copia terminarían midiendo cosas distintas con el mismo nombre. Aquí
    solo se agrega el cuadro de ejemplo dibujado."""
    m = medir_imagen(ruta, det, muestras)
    m['ruta'] = ruta
    ejemplo = m.pop('_ejemplo', None)
    if ejemplo is not None:
        cuadro, dets = ejemplo
        img = cuadro.copy()
        for d in dets:
            x1, y1, x2, y2 = map(int, d['bbox'])
            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 255), 1)
            cv2.putText(img, f"{y2 - y1}", (x1, max(8, y1 - 2)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 255), 1)
        m['_ejemplo'] = img
    else:
        m['_ejemplo'] = None
    return m


def main():
    cfg = _config()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('rutas', nargs='+', help='videos o carpetas')
    ap.add_argument('--muestras', type=int, default=12, help='cuadros por video')
    ap.add_argument('--salida', default='data/od/calidad')
    ap.add_argument('--imgsz', type=int, default=cfg.get('input_size', 1280))
    ap.add_argument('--modelo', default=cfg.get('model_path', 'models/yolov8s.pt'))
    args = ap.parse_args()

    videos = []
    for r in args.rutas:
        if os.path.isdir(r):
            for ext in EXTENSIONES:
                videos += glob.glob(os.path.join(r, '**', f'*{ext}'), recursive=True)
        else:
            videos.append(r)
    videos.sort()
    if not videos:
        sys.exit('No se encontraron videos')

    det = VehicleDetector(args.modelo, cfg.get('confidence_threshold', 0.25),
                          cfg.get('iou_threshold', 0.5), args.imgsz, 'auto')
    det.set_detection_band(None)
    os.makedirs(args.salida, exist_ok=True)

    resultados = []
    ejemplos = {}
    for v in videos:
        r = medir(v, det, args.muestras)
        sitio = os.path.basename(os.path.dirname(v))
        r['aforo'] = sitio
        img = r.pop('_ejemplo', None)
        if img is not None and sitio not in ejemplos:
            ejemplos[sitio] = img
            nombre = ''.join(c if c.isalnum() else '_' for c in sitio)
            cv2.imwrite(os.path.join(args.salida, f'{nombre}.png'),
                        cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
                        if img.shape[1] < 1000 else img)
        resultados.append(r)
        print(f"{sitio[:34]:<34} {os.path.basename(v):<18} {r.get('resolucion')} "
              f"{r.get('fps')}fps {r.get('kbps')}kb/s  alto med {r.get('alto_mediana')} px "
              f"(<20: {r.get('pct_bajo_20px')}%, >=40: {r.get('pct_40px_o_mas')}%) "
              f"conf {r.get('confianza')} brillo {r.get('brillo')} nitidez {r.get('nitidez')}",
              flush=True)

    with open(os.path.join(args.salida, 'calidad.json'), 'w', encoding='utf-8') as fh:
        json.dump(resultados, fh, ensure_ascii=False, indent=1)
    print(f"\n{os.path.join(args.salida, 'calidad.json')}")


if __name__ == '__main__':
    main()
