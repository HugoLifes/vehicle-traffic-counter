#!/usr/bin/env python3
"""
¿Puede un modelo de visión clasificar el vehículo mejor que la regla del
alto? Se mide antes de construir nada encima.

El detector solo conoce las cinco clases de COCO, y ahí no existe "pickup":
por eso hoy solo se entrega liviano contra pesado. Un modelo de visión sí
puede responder en las categorías de la SCT, pero a la distancia de esta
cámara el vehículo mide entre 33 y 90 px, y eso es poco para pedirle que
distinga una camioneta de un camión de redilas.

La prueba: se recortan vehículos EN LA LÍNEA de conteo, se numeran, se le
pregunta a cada uno al modelo, y se guarda todo para poder revisarlo a ojo
y comparar. Sin la revisión a ojo esto no prueba nada — el modelo podría
equivocarse igual que el detector y quedar una comparación de dos errores.

Produce tres cosas en `data/`:
  - `clasificador_hoja.png`  hoja numerada, para etiquetar mirando
  - `clasificador_crops/`    cada recorte suelto
  - `clasificador.json`      lo que respondió el modelo, por número

Uso, dentro del contenedor del Jetson:
    python3 tools/probar_clasificador_visual.py --proyecto 2 \
        --zona "Calzada oriente" --n 36
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ai import nvidia_client  # noqa: E402
from src.detector import VehicleDetector  # noqa: E402
from src.engine.zones import (band_from_zones, load_zones,  # noqa: E402
                              zone_for_bbox)

RAIZ = Path(__file__).resolve().parent.parent

# Las categorías de la empresa, no las de COCO. Se le dan al modelo tal
# cual para que responda en el vocabulario del entregable.
PROMPT = (
    "Esta es una foto de un vehiculo captada por una camara de aforo "
    "vehicular en una avenida de Ciudad Juarez, Mexico. La imagen es de "
    "baja resolucion.\n\n"
    "Clasificalo en UNA de estas categorias de la SCT mexicana:\n"
    "  AUTO  - automovil, sedan, hatchback\n"
    "  SUV   - camioneta cerrada tipo SUV o minivan\n"
    "  PICKUP- camioneta de batea (pick-up)\n"
    "  MOTO  - motocicleta\n"
    "  BUS   - autobus o microbus de pasajeros\n"
    "  CAMION- camion unitario de carga (redilas, caja chica, volteo)\n"
    "  TRACTO- tractocamion con semirremolque (trailer)\n\n"
    "Responde SOLO con la palabra de la categoria, nada mas."
)

VALIDAS = ("AUTO", "SUV", "PICKUP", "MOTO", "BUS", "CAMION", "TRACTO")


def normalizar(texto: str) -> str:
    """La respuesta llega con explicaciones por mucho que se pida lo
    contrario; se busca la categoria dentro del texto."""
    t = (texto or "").strip().upper()
    for v in VALIDAS:
        if v in t:
            return v
    return "?"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--proyecto", type=int, required=True)
    p.add_argument("--zona", required=True)
    p.add_argument("--n", type=int, default=36)
    p.add_argument("--cada", type=float, default=2.0)
    p.add_argument("--margen", type=float, default=45)
    p.add_argument("--escala", type=int, default=6,
                   help="cuanto se amplia el recorte antes de mandarlo")
    p.add_argument("--hora", default="12")
    # Los pesados son el 11 % del transito, asi que una muestra al azar trae
    # cuatro o cinco y no alcanza para medir nada. Con esto se pide solo la
    # franja alta, que es justo donde el modelo aporta lo que YOLO no puede:
    # separar autobus de camion de tractocamion.
    p.add_argument("--min-alto", type=int, default=0,
                   help="ignorar vehiculos mas bajos que esto, en pixeles")
    a = p.parse_args()

    if not nvidia_client.is_configured():
        sys.exit("El cliente de NVIDIA no esta configurado (falta .env).")

    cfg = yaml.safe_load(open(RAIZ / "configs" / "platform.yaml", encoding="utf-8"))
    det = VehicleDetector(model_path=cfg.get("model_path", "models/yolov8s.pt"),
                          confidence_threshold=cfg.get("confidence_threshold", .25),
                          iou_threshold=cfg.get("iou_threshold", .5),
                          input_size=cfg.get("input_size", 1280), device="cpu")

    con = sqlite3.connect("file:data/traffic.db?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    zonas = load_zones(a.proyecto)
    zid = next((z["id"] for z in zonas if z["name"] == a.zona), None)
    if zid is None:
        sys.exit(f"No existe la zona {a.zona!r}")
    banda = band_from_zones(zonas, 360)
    if banda:
        det.set_detection_band(banda)

    fila = con.execute(
        "select points_json from lane_configs where project_id=? and zone_id=? "
        "and active=1", (a.proyecto, zid)).fetchone()
    if not fila:
        sys.exit(f"La zona {a.zona!r} no tiene linea activa")
    pts = json.loads(fila["points_json"])
    x_linea = (pts[0][0] + pts[1][0]) / 2

    trabajos = [dict(r) for r in con.execute(
        "select id, stored_path, fps from video_jobs where project_id=? "
        "  and substr(video_start_time,12,2)=? order by video_start_time",
        (a.proyecto, a.hora))]
    con.close()
    if not trabajos:
        sys.exit(f"No hay videos de la hora {a.hora}")

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
                x1, y1, x2, y2 = [int(v) for v in d["bbox"]]
                if zone_for_bbox(zonas, d["bbox"]) != zid:
                    continue
                if abs((x1 + x2) / 2 - x_linea) > a.margen:
                    continue
                alto = y2 - y1
                if alto < max(12, a.min_alto):
                    continue
                m = max(3, alto // 6)
                rec = cuadro[max(0, y1 - m):min(360, y2 + m),
                             max(0, x1 - m):min(640, x2 + m)]
                if rec.size:
                    recortes.append((alto, d["class_name"], d["confidence"], rec))
            if len(recortes) >= a.n * 5:
                break
        cap.release()
        if len(recortes) >= a.n * 5:
            break

    if len(recortes) < a.n:
        print(f"Solo se juntaron {len(recortes)} recortes")

    # Repartir la muestra por todo el rango de alturas: los casos frontera
    # son los que deciden si el modelo sirve, y son los escasos.
    recortes.sort(key=lambda r: r[0])
    paso = max(1, len(recortes) // a.n)
    muestra = recortes[::paso][:a.n]

    carpeta = Path("data/clasificador_crops")
    carpeta.mkdir(parents=True, exist_ok=True)
    resultados = []
    print(f"{len(muestra)} vehiculos. Preguntando al modelo de vision...")
    for i, (alto, coco, conf, rec) in enumerate(muestra, start=1):
        h, w = rec.shape[:2]
        grande = cv2.resize(rec, (w * a.escala, h * a.escala),
                            interpolation=cv2.INTER_CUBIC)
        cv2.imwrite(str(carpeta / f"{i:02d}.png"), grande)
        try:
            crudo = nvidia_client.vision(PROMPT, grande, max_tokens=20)
            clase = normalizar(crudo)
        except Exception as e:  # el free tier da 502 esporadicos
            crudo, clase = f"ERROR: {e}", "?"
        resultados.append({"n": i, "alto_px": alto, "coco": coco,
                           "conf": round(conf, 2), "modelo": clase,
                           "crudo": (crudo or "")[:120]})
        print(f"  {i:>2}. {alto:>3}px  coco={coco:<11} modelo={clase}")
        time.sleep(0.4)   # no atropellar el free tier

    # Hoja numerada, para etiquetarla mirando
    cols, C = 6, 230
    filas_n = (len(muestra) + cols - 1) // cols
    hoja = np.full((filas_n * (C + 26), cols * C, 3), 28, np.uint8)
    for i, (alto, coco, conf, rec) in enumerate(muestra):
        f, c = divmod(i, cols)
        h, w = rec.shape[:2]
        esc = min((C - 8) / w, (C - 8) / h)
        vis = cv2.resize(rec, (max(1, int(w * esc)), max(1, int(h * esc))),
                         interpolation=cv2.INTER_CUBIC)
        y0, x0 = f * (C + 26) + 26, c * C
        oy, ox = (C - vis.shape[0]) // 2, (C - vis.shape[1]) // 2
        hoja[y0 + oy:y0 + oy + vis.shape[0], x0 + ox:x0 + ox + vis.shape[1]] = vis
        cv2.rectangle(hoja, (x0 + 2, y0 - 22), (x0 + C - 2, y0 + C - 2),
                      (120, 220, 120), 1)
        cv2.putText(hoja, f"{i + 1:02d}  {alto}px  {resultados[i]['modelo']}",
                    (x0 + 6, y0 - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.46,
                    (120, 220, 120), 1, cv2.LINE_AA)
    cv2.imwrite("data/clasificador_hoja.png", hoja)

    Path("data/clasificador.json").write_text(
        json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\ndata/clasificador_hoja.png   (numerada, para revisar a ojo)")
    print("data/clasificador.json       (lo que respondio el modelo)")
    reparto = {}
    for r in resultados:
        reparto[r["modelo"]] = reparto.get(r["modelo"], 0) + 1
    print(f"reparto de respuestas: {reparto}")


if __name__ == "__main__":
    main()
