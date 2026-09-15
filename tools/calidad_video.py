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
    cap = cv2.VideoCapture(ruta)
    if not cap.isOpened():
        return {'ruta': ruta, 'error': 'no abre'}
    ancho = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    alto = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 0
    declarados = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    # El total que declara el contenedor .mkv miente (9001 contra 6059
    # reales en el material anterior), y con él saldría mal el bitrate. Se
    # busca el final de verdad saltando al último tramo.
    reales = declarados
    if declarados > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, declarados - 1))
        ok, _ = cap.read()
        if not ok:
            lo, hi = 0, declarados
            while hi - lo > fps:
                mid = (lo + hi) // 2
                cap.set(cv2.CAP_PROP_POS_FRAMES, mid)
                ok, _ = cap.read()
                lo, hi = (mid, hi) if ok else (lo, mid)
            reales = lo
    segundos = reales / fps if fps else 0
    kbps = os.path.getsize(ruta) * 8 / segundos / 1000 if segundos else None

    altos, confs, brillo, contraste, nitidez = [], [], [], [], []
    por_clase = {}
    ejemplo = None
    mejor = -1
    for i in range(muestras):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int((i + 0.5) * reales / muestras))
        ok, f = cap.read()
        if not ok:
            continue
        gris = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        brillo.append(float(gris.mean()))
        contraste.append(float(gris.std()))
        nitidez.append(float(cv2.Laplacian(gris, cv2.CV_64F).var()))
        dets, _ = det.detect(f)
        for d in dets:
            x1, y1, x2, y2 = d['bbox']
            altos.append(y2 - y1)
            confs.append(d['confidence'])
            por_clase[d['class_name']] = por_clase.get(d['class_name'], 0) + 1
        # El cuadro con más vehículos es el que mejor enseña la escena.
        if len(dets) > mejor:
            mejor = len(dets)
            ejemplo = f.copy()
            for d in dets:
                x1, y1, x2, y2 = map(int, d['bbox'])
                cv2.rectangle(ejemplo, (x1, y1), (x2, y2), (0, 255, 255), 1)
                cv2.putText(ejemplo, f"{y2 - y1}", (x1, max(8, y1 - 2)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 255), 1)
    cap.release()

    return {
        'ruta': ruta,
        'resolucion': f'{ancho}x{alto}',
        'fps': round(fps, 1),
        'minutos': round(segundos / 60, 1),
        'kbps': round(kbps) if kbps else None,
        'brillo': round(statistics.mean(brillo)) if brillo else None,
        'contraste': round(statistics.mean(contraste)) if contraste else None,
        'nitidez': round(statistics.median(nitidez)) if nitidez else None,
        'detecciones_por_cuadro': round(len(altos) / max(1, len(brillo)), 1),
        'alto_p25': _percentil(altos, .25),
        'alto_mediana': _percentil(altos, .5),
        'alto_p75': _percentil(altos, .75),
        'pct_bajo_20px': round(100 * sum(a < 20 for a in altos) / len(altos)) if altos else None,
        'pct_40px_o_mas': round(100 * sum(a >= 40 for a in altos) / len(altos)) if altos else None,
        'confianza': round(statistics.mean(confs), 2) if confs else None,
        'clases': por_clase,
        '_ejemplo': ejemplo,
    }


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
