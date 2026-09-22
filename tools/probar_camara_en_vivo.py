"""
¿Esta cámara en vivo sirve, y el Jetson alcanza a procesarla? Sin guardar video.

    python tools/probar_camara_en_vivo.py https://zoocams.elpasozoo.org/BridgeZaragoza2.m3u8 \
        --minutos 3 --salida data/envivo/zaragoza2

Lee la transmisión (RTSP, HTTP o HLS .m3u8) con el mismo camino que la
cámara en vivo de la plataforma (`open_video_source` y reconexión), detecta
y rastrea cada cuadro que alcanza, y al final dice:

  · a cuántos cuadros por segundo llega la cámara y a cuántos procesa el
    equipo. En vivo no hay cola: el cuadro que no alcanza a procesarse se
    pierde. Si se procesa mucho menos de lo que llega, los rastros se parten.
  · cuántos vehículos ve por cuadro, de qué alto en píxeles y con qué
    confianza, con los mismos umbrales del diagnóstico de encuadre.
  · un cuadro anotado de muestra (el único archivo que escribe).

Existe porque las cámaras públicas de los puentes Juárez–El Paso transmiten
en HLS a 1920×1080 y 19 cuadros por segundo, y antes de contar sobre una de
ellas hay que saber si el equipo aguanta ese ritmo.

No correr mientras haya videos contándose: comparte la GPU.
"""

import argparse
import json
import os
import sys
import time

import cv2

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from src.detector import VehicleDetector                   # noqa: E402
from src.engine.diagnostico_encuadre import ALTO_BUENO, ALTO_MINIMO  # noqa: E402
from src.tracker import VehicleTracker                     # noqa: E402
from src.video_processor import open_video_source, read_with_reconnect  # noqa: E402


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
    ap.add_argument('fuente', help='URL rtsp://, http(s):// o .m3u8, o índice de webcam')
    ap.add_argument('--minutos', type=float, default=2.0)
    ap.add_argument('--salida', default='data/envivo/prueba',
                    help='prefijo del cuadro anotado (.jpg) y del resumen (.json)')
    a = ap.parse_args()

    det = VehicleDetector(cfg.get('model_path', 'models/yolov8s.pt'),
                          cfg.get('confidence_threshold', 0.25),
                          cfg.get('iou_threshold', 0.5),
                          cfg.get('input_size', 1280), 'auto')
    det.set_detection_band(None)
    t = cfg.get('tracker', {})
    trk = VehicleTracker(max_age=t.get('max_age', 30), min_hits=t.get('min_hits', 3),
                         iou_threshold=t.get('iou_threshold', 0.3), config=t)

    cap, en_vivo = open_video_source(a.fuente)
    if not cap.isOpened():
        sys.exit(f'No se pudo abrir {a.fuente}')
    fps_fuente = cap.get(cv2.CAP_PROP_FPS) or 0
    # Algunas transmisiones HLS declaran 90000 (la base de tiempo del
    # contenedor) en vez de los cuadros por segundo reales.
    if fps_fuente > 120:
        fps_fuente = 0

    inicio = time.time()
    procesados = fallos = 0
    detecciones = []
    altos = []
    confianzas = []
    rastros = set()
    mejor = None
    while time.time() - inicio < a.minutos * 60:
        ok, f, cap = read_with_reconnect(cap, a.fuente, en_vivo, max_retries=3)
        if not ok:
            fallos += 1
            if fallos > 20:
                break
            continue
        dets, _ = det.detect(f)
        tracks = trk.update(dets)
        procesados += 1
        detecciones.append(len(dets))
        for d in dets:
            altos.append(d['bbox'][3] - d['bbox'][1])
            confianzas.append(d['confidence'])
        rastros.update(tr['id'] for tr in tracks)
        # Se guarda el cuadro con más vehículos: es el que más dice.
        if mejor is None or len(dets) > mejor[0]:
            mejor = (len(dets), f.copy(), dets)
    dur = time.time() - inicio
    cap.release()
    if not procesados:
        sys.exit('No llegó ningún cuadro de la transmisión')

    altos.sort()
    mediana = altos[len(altos) // 2] if altos else 0
    resumen = {
        'fuente': a.fuente,
        'segundos': round(dur, 1),
        'resolucion': list(mejor[1].shape[1::-1]),
        'fps_fuente': round(fps_fuente, 1),
        'fps_procesados': round(procesados / dur, 1),
        'lecturas_fallidas': fallos,
        'detecciones_por_cuadro': round(sum(detecciones) / procesados, 2),
        'alto_mediano_px': round(mediana, 1),
        'confianza_media': round(sum(confianzas) / len(confianzas), 2) if confianzas else None,
        'rastros': len(rastros),
    }

    os.makedirs(os.path.dirname(a.salida) or '.', exist_ok=True)
    _, img, dets = mejor
    for d in dets:
        x1, y1, x2, y2 = (int(v) for v in d['bbox'])
        alto = y2 - y1
        color = (80, 220, 80) if alto >= ALTO_BUENO else (0, 180, 255) if alto >= ALTO_MINIMO else (60, 60, 230)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        cv2.putText(img, f'{alto}px', (x1, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    cv2.imwrite(a.salida + '.jpg', img)
    with open(a.salida + '.json', 'w', encoding='utf-8') as fh:
        json.dump(resumen, fh, indent=1)

    print(json.dumps(resumen, indent=1, ensure_ascii=False))
    if resumen['fps_fuente'] and resumen['fps_procesados'] < 0.5 * resumen['fps_fuente']:
        print(f"\nAVISO: llegan {resumen['fps_fuente']} cuadros por segundo y se procesan "
              f"{resumen['fps_procesados']}. En vivo el cuadro que no se alcanza se pierde y los "
              "rastros se parten; bajar input_size o la resolución de la cámara.")
    if mediana and mediana < ALTO_MINIMO:
        print(f'\nAVISO: el vehículo mediano mide {mediana:.0f} px; por debajo de {ALTO_MINIMO} px '
              'el conteo no es confiable. Acercar el encuadre o subir la resolución.')


if __name__ == '__main__':
    main()
