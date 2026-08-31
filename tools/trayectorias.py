"""
Extrae las trayectorias reales de los vehículos y las agrupa por sentido.

Colocar una línea de conteo "a ojo" falla de dos maneras que no se ven
hasta que el aforo ya salió mal: la línea queda casi paralela al tránsito
(y entonces los vehículos avanzan A LO LARGO de ella sin cruzarla), o
queda corta y pasan por los lados. El mapa de calor muestra DÓNDE hay
movimiento pero no HACIA DÓNDE, así que no basta para decidir el ángulo.

Esto rastrea de verdad y guarda el recorrido de cada vehículo. Con eso se
puede:
  · ver cuántos corredores de tránsito hay y por dónde van;
  · separar los sentidos (el que sube contra el que baja);
  · calcular la perpendicular a cada corredor, que es la orientación
    correcta para su línea de conteo.

    python tools/trayectorias.py --job 168 --minutos 3
"""

import argparse
import math
import os
import sqlite3
import sys
from collections import defaultdict

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.detector import VehicleDetector          # noqa: E402
from src.tracker import VehicleTracker            # noqa: E402
from src.engine.zones import band_from_zones, load_zones   # noqa: E402

DB = os.path.join('data', 'traffic.db')

# Un color por sentido, en pasos de 45 grados. El sentido es lo que
# decide dónde va la línea, así que es lo que tiene que saltar a la vista.
COLORES = [
    (80, 80, 255), (80, 180, 255), (80, 255, 255), (80, 255, 120),
    (255, 200, 80), (255, 120, 80), (255, 80, 200), (200, 80, 255),
]


def sector(dx, dy):
    """Sentido del recorrido, redondeado a uno de ocho sectores."""
    ang = math.degrees(math.atan2(-dy, dx)) % 360
    return int((ang + 22.5) % 360 // 45)


NOMBRES = ['→ este', '↗ noreste', '↑ norte', '↖ noroeste',
           '← oeste', '↙ suroeste', '↓ sur', '↘ sureste']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--job', type=int, required=True)
    ap.add_argument('--minutos', type=float, default=2)
    ap.add_argument('--desde', type=float, default=0)
    ap.add_argument('--min-recorrido', type=float, default=25,
                    help='px que debe recorrer un track para contar como trayectoria')
    ap.add_argument('--salida', default=None)
    args = ap.parse_args()

    c = sqlite3.connect(DB)
    row = c.execute("SELECT stored_path, project_id FROM video_jobs WHERE id = ?",
                    (args.job,)).fetchone()
    if row is None:
        sys.exit(f"No existe el video {args.job}")
    path, project_id = row

    zonas = load_zones(project_id)
    det = VehicleDetector('models/yolov8s.pt', 0.25, 0.5, 1280, 'auto')
    # A propósito NO se filtra por zonas aquí: el objetivo es ver todo el
    # tránsito que hay, incluido el que las zonas actuales estén dejando
    # fuera por estar mal dibujadas.
    det.set_detection_band(band_from_zones(zonas, 360) if zonas else None)
    trk = VehicleTracker(max_age=30, min_hits=3, iou_threshold=0.3)

    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 15
    if args.desde:
        cap.set(cv2.CAP_PROP_POS_MSEC, args.desde * 1000)
    ok, base = cap.read()
    alto, ancho = base.shape[:2]

    caminos = defaultdict(list)
    n = 0
    total = int(args.minutos * 60 * fps)
    while n < total:
        ok, f = cap.read()
        if not ok:
            break
        n += 1
        d, _ = det.detect(f)
        for t in trk.update(d):
            x1, y1, x2, y2 = t['bbox']
            caminos[t['id']].append(((x1 + x2) / 2, y2))   # apoyo en el suelo
    cap.release()

    # Solo recorridos con desplazamiento real: un vehículo detenido genera
    # un track largo que no dice nada sobre el sentido del tránsito.
    utiles = {}
    for tid, pts in caminos.items():
        if len(pts) < 4:
            continue
        dx = pts[-1][0] - pts[0][0]
        dy = pts[-1][1] - pts[0][1]
        if math.hypot(dx, dy) < args.min_recorrido:
            continue
        utiles[tid] = (pts, sector(dx, dy), math.hypot(dx, dy))

    print(f"\n{len(caminos)} tracks, {len(utiles)} con recorrido real "
          f"(>{args.min_recorrido:.0f} px) en {n} cuadros\n")

    por_sector = defaultdict(list)
    for tid, (pts, sec, dist) in utiles.items():
        por_sector[sec].append((pts, dist))

    print(f"{'sentido':<12} {'trayectorias':>13} {'px recorridos (mediana)':>24} "
          f"{'angulo de la LINEA':>20}")
    for sec, items in sorted(por_sector.items(), key=lambda kv: -len(kv[1])):
        if len(items) < 3:
            continue
        med = sorted(d for _, d in items)[len(items) // 2]
        # La línea de conteo va PERPENDICULAR al sentido del tránsito.
        ang_mov = sec * 45
        ang_linea = (ang_mov + 90) % 180
        print(f"{NOMBRES[sec]:<12} {len(items):>13} {med:>24.0f} "
              f"{ang_linea:>19.0f}°")

    # Dibujo: cada recorrido en el color de su sentido.
    img = base.copy()
    capa = np.zeros_like(img)
    for tid, (pts, sec, _) in utiles.items():
        col = COLORES[sec]
        for a, b in zip(pts, pts[1:]):
            cv2.line(capa, (int(a[0]), int(a[1])), (int(b[0]), int(b[1])), col, 1, cv2.LINE_AA)
        cv2.circle(capa, (int(pts[-1][0]), int(pts[-1][1])), 2, col, -1)
    cv2.addWeighted(capa, 0.85, img, 1.0, 0, img)

    y = 14
    for sec, items in sorted(por_sector.items(), key=lambda kv: -len(kv[1])):
        if len(items) < 3:
            continue
        cv2.rectangle(img, (5, y - 7), (13, y + 1), COLORES[sec], -1)
        cv2.putText(img, f"{NOMBRES[sec]} x{len(items)}", (17, y + 1),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.3, COLORES[sec], 1, cv2.LINE_AA)
        y += 11

    salida = args.salida or os.path.join(
        os.environ.get('TEMP', '.'), 'claude', 'trayectorias.png')
    os.makedirs(os.path.dirname(salida) or '.', exist_ok=True)
    cv2.imwrite(salida, cv2.resize(img, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC))
    print(f"\n{salida}")


if __name__ == '__main__':
    main()
