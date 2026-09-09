#!/usr/bin/env python3
"""
Hoja de contactos de vehiculos recortados, con lo que el sistema dice de
cada uno. Para comprobar la clasificacion MIRANDOLA, no por agregados.

Existe porque validar la clasificacion comparando totales tiene un hueco:
un automovil mal llamado camion y un camion mal llamado automovil se
cancelan, y el total cuadra igual. La unica forma de saber si separa bien
es ver los vehiculos uno por uno.

Los recortes salen ORDENADOS POR ALTO, que es como se ve si la regla del
umbral cae donde debe: si al recorrer la hoja los camiones de verdad
empiezan justo donde la regla dice, la regla sirve; si estan mezclados con
camionetas a lo largo de toda la hoja, no.

Uso:
    python tools/hoja_clases.py --proyecto 2 --zona "Calzada oriente" \
        --salida data/clases.png
"""
from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys
from pathlib import Path

import cv2
import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.detector import VehicleDetector  # noqa: E402
from src.engine.zones import (band_from_zones, load_zones,  # noqa: E402
                              zone_for_bbox)

RAIZ = Path(__file__).resolve().parent.parent
COL_LIGERO = (120, 220, 120)
COL_PESADO = (80, 140, 255)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--proyecto", type=int, required=True)
    p.add_argument("--zona", required=True)
    p.add_argument("--salida", type=Path, required=True)
    p.add_argument("--n", type=int, default=54, help="cuantos vehiculos mostrar")
    p.add_argument("--cada", type=float, default=3.0, help="segundos entre cuadros")
    p.add_argument("--multiplo", type=float, default=1.58,
                   help="umbral pesado = multiplo x alto mediano del automovil")
    p.add_argument("--celda", type=int, default=190)
    # En el Jetson la GPU la tiene tomada el servidor de la plataforma, y
    # este diagnostico son unas decenas de cuadros: en CPU tarda poco y no
    # compite por los 8 GB compartidos.
    p.add_argument("--dispositivo", default="cpu", choices=("cpu", "auto", "cuda"))
    p.add_argument("--margen", type=float, default=45,
                   help="pixeles a cada lado de la linea de conteo")
    a = p.parse_args()

    cfg = yaml.safe_load(open(RAIZ / "configs" / "platform.yaml", encoding="utf-8"))
    det = VehicleDetector(model_path=cfg.get("model_path", "models/yolov8s.pt"),
                          confidence_threshold=cfg.get("confidence_threshold", 0.25),
                          iou_threshold=cfg.get("iou_threshold", 0.5),
                          input_size=cfg.get("input_size", 1280),
                          device=a.dispositivo)

    con = sqlite3.connect("file:data/traffic.db?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    zonas = load_zones(a.proyecto)
    zid = next((z["id"] for z in zonas if z["name"] == a.zona), None)
    if zid is None:
        sys.exit(f"No existe la zona {a.zona!r} en el proyecto {a.proyecto}")
    banda = band_from_zones(zonas, 360)
    if banda:
        det.set_detection_band(banda)

    # Solo vehiculos que pasan POR LA LINEA de esa calzada. Sin esto la
    # hoja mezcla distancias —un vehiculo al fondo de la zona mide 19 px y
    # el mismo vehiculo en la linea mide 33— y entonces el alto ya no dice
    # nada del tamano real, que es justo la premisa de la regla.
    import json
    linea = con.execute(
        "select points_json from lane_configs where project_id=? and zone_id=? "
        "and active=1", (a.proyecto, zid)).fetchone()
    if not linea:
        sys.exit(f"La zona {a.zona!r} no tiene ninguna linea activa atada.")
    pts = json.loads(linea["points_json"])
    x_linea = (pts[0][0] + pts[1][0]) / 2

    trabajos = [dict(r) for r in con.execute(
        "select id, stored_path, fps from video_jobs where project_id=? "
        "order by video_start_time", (a.proyecto,))]
    con.close()
    if not trabajos:
        sys.exit("El proyecto no tiene videos.")

    recortes = []
    for job in trabajos:
        cap = cv2.VideoCapture(job["stored_path"])
        fps = job["fps"] or 15
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        for f in range(0, total, int(a.cada * fps)):
            cap.set(cv2.CAP_PROP_POS_FRAMES, f)
            ok, cuadro = cap.read()
            if not ok:
                break
            for d in det.detect(cuadro)[0]:
                if zone_for_bbox(zonas, d["bbox"]) != zid:
                    continue
                x1, y1, x2, y2 = [int(v) for v in d["bbox"]]
                alto = y2 - y1
                if alto < 8 or abs((x1 + x2) / 2 - x_linea) > a.margen:
                    continue
                # Margen para ver la forma del vehiculo, no solo la caja
                m = max(3, alto // 6)
                rec = cuadro[max(0, y1 - m):min(360, y2 + m),
                             max(0, x1 - m):min(640, x2 + m)]
                if rec.size:
                    recortes.append((alto, d["class_name"], d["confidence"], rec))
            if len(recortes) >= a.n * 4:
                break
        cap.release()
        if len(recortes) >= a.n * 4:
            break

    if not recortes:
        sys.exit("No se encontro ningun vehiculo en esa zona.")

    autos = [h for h, c, _, _ in recortes if c == "car"]
    umbral = a.multiplo * statistics.median(autos) if autos else 0
    print(f"{len(recortes)} vehiculos vistos; alto mediano del automovil "
          f"{statistics.median(autos):.0f} px; umbral pesado {umbral:.0f} px")

    # Repartir la muestra a lo largo de todo el rango de alturas, para que
    # la hoja muestre la transicion y no solo los casos abundantes.
    recortes.sort(key=lambda r: r[0])
    paso = max(1, len(recortes) // a.n)
    muestra = recortes[::paso][:a.n]

    cols = 9
    filas = (len(muestra) + cols - 1) // cols
    C = a.celda
    hoja = np.full((filas * (C + 26), cols * C, 3), 28, np.uint8)

    for i, (alto, clase, conf, rec) in enumerate(muestra):
        f, c = divmod(i, cols)
        h, w = rec.shape[:2]
        esc = min((C - 8) / w, (C - 8) / h)
        vis = cv2.resize(rec, (max(1, int(w * esc)), max(1, int(h * esc))),
                         interpolation=cv2.INTER_CUBIC)
        y0, x0 = f * (C + 26) + 26, c * C
        oy, ox = (C - vis.shape[0]) // 2, (C - vis.shape[1]) // 2
        hoja[y0 + oy:y0 + oy + vis.shape[0], x0 + ox:x0 + ox + vis.shape[1]] = vis
        pesado = clase == "truck" and alto > umbral or clase == "bus"
        col = COL_PESADO if pesado else COL_LIGERO
        cv2.rectangle(hoja, (x0 + 2, y0 - 22), (x0 + C - 2, y0 + C - 2), col, 1)
        cv2.putText(hoja, f"{clase} {alto}px {conf:.2f}", (x0 + 6, y0 - 7),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, col, 1, cv2.LINE_AA)

    a.salida.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(a.salida), hoja)
    print(f"{a.salida}  {hoja.shape[1]}x{hoja.shape[0]}  "
          f"({len(muestra)} vehiculos, ordenados por alto)")
    print("verde = el sistema lo cuenta como liviano; naranja = como pesado")


if __name__ == "__main__":
    main()
