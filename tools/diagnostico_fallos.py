"""
Mide DONDE falla el detector dentro del cuadro, sin necesidad de un conteo
manual.

La idea: la sustraccion de fondo (MOG2) encuentra lo que se MUEVE, sin saber
que es. YOLO encuentra lo que RECONOCE. Un blob en movimiento del tamano de
un vehiculo que YOLO no cubre con ninguna caja es, casi siempre, un vehiculo
perdido. Cruzando las dos senales sale un mapa de fallos por zona del cuadro,
que es lo que hace falta para saber si el problema esta en los vehiculos
lejanos (pequenos) o en los cercanos (enormes y recortados por el borde).

    python tools/diagnostico_fallos.py --job 164 --segundos 90
    python tools/diagnostico_fallos.py --job 164 --imgsz 1280 --modelo yolov8s.pt
"""

import argparse
import os
import sqlite3
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB = os.path.join('data', 'traffic.db')


def ruta_video(job_id):
    c = sqlite3.connect(DB)
    row = c.execute("SELECT stored_path FROM video_jobs WHERE id = ?", (job_id,)).fetchone()
    c.close()
    if row is None or not os.path.exists(row[0]):
        sys.exit("No se encontro el video del job {}".format(job_id))
    return row[0]


def iou_cubierto(blob, cajas):
    """Fraccion del blob que alguna caja de YOLO alcanza a cubrir."""
    bx1, by1, bx2, by2 = blob
    area = max(1, (bx2 - bx1) * (by2 - by1))
    mejor = 0.0
    for cx1, cy1, cx2, cy2 in cajas:
        ix1, iy1 = max(bx1, cx1), max(by1, cy1)
        ix2, iy2 = min(bx2, cx2), min(by2, cy2)
        if ix2 > ix1 and iy2 > iy1:
            mejor = max(mejor, (ix2 - ix1) * (iy2 - iy1) / area)
    return mejor


def _config():
    """
    Valores del detector tal como los usa producción.

    Las herramientas de diagnóstico traían yolov8n y imgsz 640 escritos a
    mano, que es la configuración que este proyecto ABANDONÓ por medición
    (75 contra 107 cruces). Quien las corriera sin pasar --modelo obtenía
    un diagnóstico que no correspondía a lo que de verdad cuenta el
    sistema — y sin ningún aviso de que estaba mirando otra cosa.
    """
    try:
        import yaml
        with open('configs/platform.yaml', encoding='utf-8') as fh:
            cfg = yaml.safe_load(fh) or {}
        det = cfg.get('detector', {})
        return (cfg.get('model_path', 'models/yolov8s.pt'),
                det.get('input_size', 1280),
                cfg.get('confidence_threshold', 0.25))
    except Exception:
        return 'models/yolov8s.pt', 1280, 0.25


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--job', type=int, required=True)
    ap.add_argument('--segundos', type=float, default=60)
    ap.add_argument('--desde', type=float, default=30)
    ap.add_argument('--salto', type=int, default=3, help='procesar 1 de cada N cuadros')
    ap.add_argument('--conf', type=float, default=0.25)
    modelo_cfg, imgsz_cfg, _ = _config()
    ap.add_argument('--imgsz', type=int, default=imgsz_cfg)
    ap.add_argument('--modelo', default=modelo_cfg)
    ap.add_argument('--area-min', type=int, default=250,
                    help='area minima del blob en px2 para considerarlo vehiculo')
    ap.add_argument('--guardar-fallos', default=None,
                    help='PNG con ejemplos de los blobs no detectados')
    args = ap.parse_args()

    from src.detector import VehicleDetector
    det = VehicleDetector(args.modelo, args.conf, 0.5, args.imgsz, 'auto')

    cap = cv2.VideoCapture(ruta_video(args.job))
    fps = cap.get(cv2.CAP_PROP_FPS) or 15
    cap.set(cv2.CAP_PROP_POS_MSEC, args.desde * 1000)
    mog = cv2.createBackgroundSubtractorMOG2(history=300, varThreshold=40, detectShadows=False)

    total_cuadros = int(args.segundos * fps / args.salto)
    # Tres bandas por altura: al fondo los vehiculos son chicos, al frente
    # son enormes. Es exactamente la distincion que hay que resolver.
    bandas = [('fondo (lejos)', 0.0, 0.45), ('medio', 0.45, 0.65), ('frente (cerca)', 0.65, 1.0)]
    stats = {b[0]: [0, 0] for b in bandas}   # [blobs, perdidos]
    ejemplos = []
    leidos = 0
    n = 0

    while leidos < total_cuadros:
        ok, frame = cap.read()
        if not ok:
            break
        n += 1
        if n % args.salto:
            continue
        leidos += 1
        h, w = frame.shape[:2]

        mask = mog.apply(frame)
        if leidos < 25:      # el modelo de fondo necesita calentar
            continue
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        mask = cv2.dilate(mask, np.ones((5, 5), np.uint8), iterations=2)
        nlab, _, stats_cc, cent = cv2.connectedComponentsWithStats(mask, 8)

        cajas = [tuple(d['bbox']) for d in det.detect(frame)[0]]

        for i in range(1, nlab):
            x, y, bw, bh, area = stats_cc[i]
            if area < args.area_min or bw < 8 or bh < 6:
                continue
            blob = (x, y, x + bw, y + bh)
            cubierto = iou_cubierto(blob, cajas)
            cy = (y + bh / 2) / h
            for nombre, lo, hi in bandas:
                if lo <= cy < hi:
                    stats[nombre][0] += 1
                    if cubierto < 0.3:
                        stats[nombre][1] += 1
                        if len(ejemplos) < 6 and area > 600:
                            ejemplos.append((frame.copy(), blob, cajas))
                    break
    cap.release()

    print("\nmodelo={}  imgsz={}  conf={}".format(
        os.path.basename(args.modelo), args.imgsz, args.conf))
    print("{:>16} {:>8} {:>9} {:>10}".format('zona', 'blobs', 'perdidos', '% perdido'))
    tb = tp = 0
    for nombre, _, _ in bandas:
        b, p = stats[nombre]
        tb += b
        tp += p
        pct = 100.0 * p / b if b else 0.0
        print("{:>16} {:>8} {:>9} {:>9.0f}%".format(nombre, b, p, pct))
    print("{:>16} {:>8} {:>9} {:>9.0f}%".format(
        'TOTAL', tb, tp, 100.0 * tp / tb if tb else 0))

    if args.guardar_fallos and ejemplos:
        celdas = []
        for frame, blob, cajas in ejemplos:
            for c in cajas:
                cv2.rectangle(frame, (int(c[0]), int(c[1])), (int(c[2]), int(c[3])),
                              (60, 220, 60), 1)
            cv2.rectangle(frame, (blob[0], blob[1]), (blob[2], blob[3]), (0, 0, 255), 2)
            cv2.putText(frame, "movimiento sin deteccion", (blob[0], max(10, blob[1] - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 255), 1, cv2.LINE_AA)
            celdas.append(cv2.resize(frame, None, fx=2.2, fy=2.2, interpolation=cv2.INTER_CUBIC))
        cols = 2
        filas = (len(celdas) + cols - 1) // cols
        ch, cw = celdas[0].shape[:2]
        hoja = np.zeros((filas * ch, cols * cw, 3), np.uint8)
        for i, c in enumerate(celdas):
            f, cl = divmod(i, cols)
            hoja[f * ch:(f + 1) * ch, cl * cw:(cl + 1) * cw] = c
        os.makedirs(os.path.dirname(args.guardar_fallos) or '.', exist_ok=True)
        cv2.imwrite(args.guardar_fallos, hoja)
        print("\nejemplos ->", args.guardar_fallos)


if __name__ == '__main__':
    main()
