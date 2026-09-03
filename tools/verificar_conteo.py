"""
Genera un video de verificación para contar a mano y comparar.

Responde a la única pregunta que no se puede contestar con más software:
"¿el número que da el sistema es el correcto?". Todo lo demás que se ha
medido en este proyecto es relativo —"cuenta un 43 % más que antes"— y un
informe de aforo necesita declarar una exactitud, no una mejora.

El video que produce lleva, sobre cada vehículo contado, un número
correlativo que se queda pegado unos segundos. Así se puede parar, contar
a mano los vehículos que pasan, y comparar contra el último número. Si al
final del minuto el sistema marcó 34 y a mano salen 36, la exactitud es
del 94 % — y eso ya es una cifra defendible.

Salen dos archivos: el video y un CSV con un renglón por cruce
(número, segundo, calzada, sentido, tipo, confianza) para revisar los
casos dudosos sin volver a mirar el video entero.

    python tools/verificar_conteo.py --job 181 --minutos 2
"""

import argparse
import csv
import os
import subprocess
import sys
from collections import deque

import cv2
import imageio_ffmpeg
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.detector import VehicleDetector                      # noqa: E402
from src.tracker import VehicleTracker                        # noqa: E402
from src.engine.lanes import build_lane_counters              # noqa: E402
from src.engine.zones import (band_from_zones, draw_zones,    # noqa: E402
                              filter_detections, load_zones, zone_for_bbox)
from src.storage import traffic_db                            # noqa: E402

VERDE = (90, 235, 90)
AMBAR = (60, 190, 250)
BLANCO = (255, 255, 255)
FONDO = (24, 24, 28)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--job', type=int, required=True)
    ap.add_argument('--minutos', type=float, default=2)
    ap.add_argument('--desde', type=float, default=0)
    ap.add_argument('--marca-segundos', type=float, default=3,
                    help='cuánto se queda pegado el número sobre el vehículo')
    ap.add_argument('--salida', default='input')
    args = ap.parse_args()

    job = traffic_db.get_video_job(args.job)
    if job is None:
        sys.exit(f"No existe el video {args.job}")
    project_id = job.get('project_id')

    zonas = load_zones(project_id)
    counters, meta = build_lane_counters(
        job.get('source_label') or 'x', 360, 640, project_id=project_id)
    if not counters:
        sys.exit("El proyecto no tiene líneas de conteo definidas")

    cfg = {}
    try:
        import yaml
        with open('configs/platform.yaml', encoding='utf-8') as fh:
            cfg = yaml.safe_load(fh) or {}
    except Exception:
        pass
    det_cfg = cfg.get('detector', {})

    det = VehicleDetector(
        cfg.get('model_path', 'models/yolov8s.pt'),
        cfg.get('confidence_threshold', 0.25),
        det_cfg.get('iou_threshold', 0.5),
        det_cfg.get('input_size', 1280), 'auto')
    det.set_detection_band(band_from_zones(zonas, 360) if zonas else None)
    trk = VehicleTracker(max_age=30, min_hits=3, iou_threshold=0.3)

    cap = cv2.VideoCapture(job['stored_path'])
    fps = cap.get(cv2.CAP_PROP_FPS) or 15
    if args.desde:
        cap.set(cv2.CAP_PROP_POS_MSEC, args.desde * 1000)

    os.makedirs(args.salida, exist_ok=True)
    crudo = os.path.join(args.salida, f'verificacion_{args.job}_raw.mp4')
    final = os.path.join(args.salida, f'verificacion_{args.job}.mp4')
    ruta_csv = os.path.join(args.salida, f'verificacion_{args.job}.csv')
    writer = cv2.VideoWriter(crudo, cv2.VideoWriter_fourcc(*'mp4v'), fps, (640, 360))

    nombres = {z['id']: z['name'] for z in zonas}
    filas = []
    marcas = deque()          # (frame_expira, x, y, numero)
    numero = 0
    n = 0
    total = int(args.minutos * 60 * fps)
    vida = int(args.marca_segundos * fps)

    while n < total:
        ok, frame = cap.read()
        if not ok:
            break
        n += 1

        dets = filter_detections(zonas, det.detect(frame)[0])
        tracks = trk.update(dets)

        for lane_id, counter in counters.items():
            zona_carril = meta[lane_id].get('zone_id')
            vistos = (
                [t for t in tracks if zone_for_bbox(zonas, t['bbox']) == zona_carril]
                if (zona_carril and zonas) else tracks
            )
            r = counter.update(vistos)
            for cr in r['in'] + r['out']:
                tr = next((t for t in vistos if t['id'] == cr['track_id']), None)
                if tr is None:
                    continue
                numero += 1
                x1, y1, x2, y2 = [int(v) for v in tr['bbox']]
                marcas.append((n + vida, (x1 + x2) // 2, y1, numero))
                zid = zone_for_bbox(zonas, tr['bbox'])
                filas.append({
                    'numero': numero,
                    'segundo': round(args.desde + n / fps, 1),
                    'linea': meta[lane_id]['name'],
                    'calzada': nombres.get(zid, ''),
                    'sentido': cr['direction'],
                    'tipo': cr['vehicle_type'],
                    'confianza': round(tr.get('confidence') or 0, 2),
                })

        vis = draw_zones(frame.copy(), zonas)
        for lane_id, m in meta.items():
            p = m['points']
            cv2.line(vis, (int(p[0][0]), int(p[0][1])), (int(p[1][0]), int(p[1][1])),
                     (255, 90, 200), 2)

        # Cajas de lo que se está siguiendo, sin etiqueta: aquí lo que se
        # verifica es el CONTEO, y un texto por vehículo taparía la escena.
        for t in tracks:
            x1, y1, x2, y2 = [int(v) for v in t['bbox']]
            cv2.rectangle(vis, (x1, y1), (x2, y2), VERDE, 1)

        while marcas and marcas[0][0] < n:
            marcas.popleft()
        for expira, mx, my, num in marcas:
            cv2.circle(vis, (mx, my - 6), 9, FONDO, -1)
            cv2.circle(vis, (mx, my - 6), 9, AMBAR, 1)
            txt = str(num)
            (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.32, 1)
            cv2.putText(vis, txt, (mx - tw // 2, my - 6 + th // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.32, AMBAR, 1, cv2.LINE_AA)

        # Marcador grande: es el número contra el que se compara al contar
        # a mano, así que tiene que leerse sin pausar el video.
        cv2.rectangle(vis, (0, 0), (150, 34), FONDO, -1)
        cv2.putText(vis, f'CONTADOS: {numero}', (8, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, BLANCO, 1, cv2.LINE_AA)
        seg = args.desde + n / fps
        cv2.putText(vis, f'{int(seg // 60):02d}:{int(seg % 60):02d}', (585, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, BLANCO, 1, cv2.LINE_AA)

        writer.write(vis)

    cap.release()
    writer.release()

    with open(ruta_csv, 'w', newline='', encoding='utf-8-sig') as fh:
        w = csv.DictWriter(fh, fieldnames=list(filas[0].keys()) if filas else
                           ['numero', 'segundo', 'linea', 'calzada', 'sentido',
                            'tipo', 'confianza'])
        w.writeheader()
        w.writerows(filas)

    # H.264 para que se pueda abrir en cualquier reproductor y navegador.
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    r = subprocess.run([ffmpeg, '-y', '-i', crudo, '-c:v', 'libx264',
                        '-pix_fmt', 'yuv420p', '-movflags', '+faststart', final],
                       capture_output=True, text=True)
    if r.returncode == 0:
        os.remove(crudo)
    else:
        final = crudo

    print(f"\n{numero} cruces contados en {args.minutos:g} min "
          f"({n} cuadros a {fps:g} fps)")
    por_calzada = {}
    for f in filas:
        por_calzada[f['calzada']] = por_calzada.get(f['calzada'], 0) + 1
    for k, v in sorted(por_calzada.items(), key=lambda kv: -kv[1]):
        print(f"   {k or 'sin calzada':<22} {v:>4}")
    print(f"\nvideo: {final}\ncsv:   {ruta_csv}")


if __name__ == '__main__':
    main()
