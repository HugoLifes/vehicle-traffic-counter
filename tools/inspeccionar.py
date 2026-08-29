"""
Genera una hoja de contactos (varios cuadros en una sola imagen PNG) de un
video del aforo, con las detecciones y los carriles dibujados encima.

Existe por una razon concreta: quien desarrolla el sistema no puede abrir el
reproductor de video, pero si puede leer imagenes. Sin esto, cada duda sobre
lo que se ve en pantalla ("por que no conto ese carro?", "de noche se ve
mal?") depende de que el usuario lo describa con palabras, y hay cosas que
son muy dificiles de explicar asi. Con esto se mira el mismo cuadro.

Ejemplos:
    # 6 cuadros del video 12, uno cada 10 s, empezando en el minuto 1
    python tools/inspeccionar.py --job 12 --desde 60 --cada 10 --n 6

    # comparar el mismo momento de dia y de noche
    python tools/inspeccionar.py --job 12 --job 120 --desde 30 --n 3

    # acercarse a la linea de conteo (recorta y amplia esa franja)
    python tools/inspeccionar.py --job 12 --zoom-carriles
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import timedelta

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB = os.path.join('data', 'traffic.db')

COLOR_CAJA = (60, 220, 60)
COLOR_CAJA_DEBIL = (60, 160, 240)   # confianza < 0.4: naranja, para verlas aparte
COLOR_CARRIL = (255, 90, 200)
COLOR_TEXTO = (255, 255, 255)
COLOR_FONDO = (28, 28, 34)


def _conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def job_info(job_id):
    with _conn() as c:
        row = c.execute(
            "SELECT id, original_name, stored_path, project_id, video_start_time, fps"
            " FROM video_jobs WHERE id = ?", (job_id,)
        ).fetchone()
    if row is None:
        sys.exit("No existe el video {}".format(job_id))
    if not os.path.exists(row['stored_path']):
        sys.exit("El archivo del video {} ya no esta en {}".format(job_id, row['stored_path']))
    return dict(row)


def carriles(project_id):
    if project_id is None:
        return []
    with _conn() as c:
        rows = c.execute(
            "SELECT name, line_type, points_json FROM lane_configs"
            " WHERE project_id = ? AND active = 1", (project_id,)
        ).fetchall()
    return [
        {'name': r['name'], 'line_type': r['line_type'], 'points': json.loads(r['points_json'])}
        for r in rows
    ]


def dibujar_carriles(frame, lanes):
    for lane in lanes:
        pts = lane['points']
        if len(pts) < 2:
            continue
        p1 = (int(pts[0][0]), int(pts[0][1]))
        p2 = (int(pts[1][0]), int(pts[1][1]))
        cv2.line(frame, p1, p2, COLOR_CARRIL, 2)
        cv2.putText(frame, lane['name'], (p1[0] + 4, max(12, p1[1] - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, COLOR_CARRIL, 1, cv2.LINE_AA)
    return frame


def dibujar_detecciones(frame, detections):
    for d in detections:
        x1, y1, x2, y2 = [int(v) for v in d['bbox']]
        conf = d['confidence']
        color = COLOR_CAJA if conf >= 0.4 else COLOR_CAJA_DEBIL
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 1)
        # El alto en pixeles es el dato que decide si YOLO puede o no con el
        # vehiculo, asi que va en la etiqueta junto con la confianza.
        cv2.putText(frame, "{:.2f} {}px".format(conf, y2 - y1), (x1, max(9, y1 - 3)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.32, color, 1, cv2.LINE_AA)
    return frame


def barra(frame, texto):
    """Franja de titulo sobre el cuadro, para no tapar la escena."""
    alto = 20
    encabezado = np.full((alto, frame.shape[1], 3), COLOR_FONDO, np.uint8)
    cv2.putText(encabezado, texto, (6, 14), cv2.FONT_HERSHEY_SIMPLEX,
                0.42, COLOR_TEXTO, 1, cv2.LINE_AA)
    return np.vstack([encabezado, frame])


def hoja_de_contactos(celdas, columnas):
    if not celdas:
        sys.exit("No se pudo leer ningun cuadro")
    filas = (len(celdas) + columnas - 1) // columnas
    ch, cw = celdas[0].shape[:2]
    hoja = np.full((filas * ch, columnas * cw, 3), COLOR_FONDO, np.uint8)
    for i, celda in enumerate(celdas):
        f, c = divmod(i, columnas)
        hoja[f * ch:(f + 1) * ch, c * cw:(c + 1) * cw] = celda
    return hoja


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--job', type=int, action='append', required=True,
                    help='id del video (se puede repetir para comparar varios)')
    ap.add_argument('--desde', type=float, default=0, help='segundo inicial')
    ap.add_argument('--cada', type=float, default=5, help='segundos entre cuadros')
    ap.add_argument('--n', type=int, default=4, help='cuantos cuadros por video')
    ap.add_argument('--escala', type=float, default=2.0,
                    help='amplia el cuadro; a 640x360 hace falta para ver algo')
    ap.add_argument('--columnas', type=int, default=2)
    ap.add_argument('--zoom-carriles', action='store_true',
                    help='recorta la franja alrededor de los carriles y la amplia')
    ap.add_argument('--sin-detectar', action='store_true',
                    help='solo el video crudo, sin pasar YOLO (mucho mas rapido)')
    ap.add_argument('--conf', type=float, default=0.25)
    ap.add_argument('--salida', default=None)
    args = ap.parse_args()

    detector = None
    if not args.sin_detectar:
        from src.detector import VehicleDetector
        detector = VehicleDetector(model_path='models/yolov8n.pt',
                                   confidence_threshold=args.conf,
                                   iou_threshold=0.5, input_size=640, device='auto')

    celdas = []
    for job_id in args.job:
        info = job_info(job_id)
        lanes = carriles(info['project_id'])
        cap = cv2.VideoCapture(info['stored_path'])

        for k in range(args.n):
            t = args.desde + k * args.cada
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, frame = cap.read()
            if not ok:
                break

            detections = detector.detect(frame)[0] if detector is not None else []

            frame = dibujar_detecciones(frame, detections)
            frame = dibujar_carriles(frame, lanes)

            if args.zoom_carriles and lanes:
                ys = [p[1] for l in lanes for p in l['points']]
                y0 = max(0, int(min(ys)) - 60)
                y1 = min(frame.shape[0], int(max(ys)) + 60)
                frame = frame[y0:y1]

            if args.escala != 1:
                frame = cv2.resize(frame, None, fx=args.escala, fy=args.escala,
                                   interpolation=cv2.INTER_CUBIC)

            reloj = str(timedelta(seconds=int(t)))
            inicio = info['video_start_time'] or ''
            hora = inicio[11:16] if len(inicio) > 15 else ''
            celdas.append(barra(frame, "#{} {}  +{}  {}  {} det".format(
                job_id, info['original_name'][:26], reloj, hora, len(detections))))
        cap.release()

    # Todas las celdas deben medir igual para poder apilarse.
    ancho = max(c.shape[1] for c in celdas)
    alto = max(c.shape[0] for c in celdas)
    celdas = [cv2.copyMakeBorder(c, 0, alto - c.shape[0], 0, ancho - c.shape[1],
                                 cv2.BORDER_CONSTANT, value=COLOR_FONDO)
              for c in celdas]

    salida = args.salida or os.path.join(
        os.environ.get('TEMP', '.'), 'claude', 'inspeccion.png')
    os.makedirs(os.path.dirname(salida) or '.', exist_ok=True)
    hoja = hoja_de_contactos(celdas, args.columnas)
    cv2.imwrite(salida, hoja)
    print("{}  ({}x{})".format(salida, hoja.shape[1], hoja.shape[0]))


if __name__ == '__main__':
    main()
