"""
Recorta los cruces que se contaron ANTES de que se guardara la posicion de
la caja, volviendo a detectar solo el segundo de cada uno.

La posicion del cruce (`bbox_x`, `bbox_y`, `cuadro`) se guarda desde el
23-sep-2026. En el aforo frontal de Cd. Juarez eso deja sin recorte todo lo
contado antes de las 18:20: justo las horas de dia, que son las que sirven
para revisar y etiquetar la clase de los pesados. Recontar esas horas son
unas 12 h de Jetson; esto cuesta minutos, porque de cada cruce ya se sabe el
segundo, el carril y el tamaño de la caja, y basta volver a detectar los
~20 cuadros de ese segundo para encontrar el vehiculo.

El vehiculo elegido es la deteccion, dentro de la calzada del carril, cuyo
punto de apoyo (centro del borde inferior, el mismo criterio del contador)
queda mas cerca de la linea y cuya caja mide lo mismo que la guardada.
Si nada se parece se descarta, no se adivina.

NO escribe en la base: deja los recortes y un indice JSON con el cuadro y la
caja encontrados. Usa la GPU; no correrlo con la cola trabajando (dos
trabajos de GPU a la vez en el Orin dan NvMapMemAllocInternalTagged).

    python tools/recortes_sin_posicion.py --proyecto 7 \\
        --desde "2026-09-19 12:00" --hasta "2026-09-19 18:20" \\
        --salida data/nuevos/pesados/dia
"""

import argparse
import json
import os
import statistics as st
import sys
from collections import defaultdict
from datetime import datetime

import cv2

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from src.engine.zones import _contiene, _punto_de_apoyo, band_from_zones, load_zones  # noqa: E402
from src.storage import traffic_db  # noqa: E402

# Cuanto puede diferir la caja encontrada de la guardada. La guardada es la
# del rastro en el cuadro del cruce, y la deteccion de un cuadro vecino mide
# casi lo mismo; mas diferencia es otro vehiculo.
TOL_ALTO = 0.20
TOL_ANCHO = 0.25


def distancia_a_linea(px, py, linea):
    (x1, y1), (x2, y2) = linea
    dx, dy = x2 - x1, y2 - y1
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / float(dx * dx + dy * dy or 1)))
    return ((px - x1 - t * dx) ** 2 + (py - y1 - t * dy) ** 2) ** 0.5


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--proyecto", type=int, required=True)
    ap.add_argument("--desde", required=True)
    ap.add_argument("--hasta", required=True)
    ap.add_argument("--clases", nargs="+", default=["truck", "bus"])
    ap.add_argument("--alto-rel-min", type=float, default=1.58,
                    help="solo cajas de al menos este multiplo del automovil mediano "
                         "de su carril (1.58 = el umbral de pesado)")
    ap.add_argument("--salida", required=True, help="carpeta de los recortes")
    a = ap.parse_args()

    import yaml
    from src.detector import VehicleDetector
    with open(os.path.join(RAIZ, "configs", "platform.yaml"), encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    # Igual que VideoJobProcessor._get_detector: el mismo detector que conto.
    det_cfg = dict(cfg.get("detector", {}))
    proyecto = traffic_db.get_project(a.proyecto)
    det = VehicleDetector(model_path=cfg.get("model_path", "models/yolov8s.pt"),
                          confidence_threshold=cfg.get("confidence_threshold", 0.25),
                          iou_threshold=det_cfg.get("iou_threshold", 0.5),
                          input_size=det_cfg.get("input_size", 640),
                          device=cfg.get("device", "auto"), config=det_cfg)
    det.nms_agnostico = bool(proyecto.get("nms_agnostico"))

    zonas = load_zones(a.proyecto)
    por_id = {z["id"]: z for z in zonas}
    carriles = {c["id"]: c for c in traffic_db.list_lanes(project_id=a.proyecto)}
    conn = traffic_db.get_connection()
    alto_auto = {}
    for lid in carriles:
        hs = [r[0] for r in conn.execute(
            "SELECT bbox_height FROM crossings WHERE lane_id=? AND vehicle_type='car' "
            "AND bbox_height IS NOT NULL", (lid,))]
        if len(hs) >= 30:
            alto_auto[lid] = st.median(hs)

    marcas = ",".join("?" * len(a.clases))
    cruces = conn.execute(
        f"""SELECT c.id, c.lane_id, c.timestamp, c.vehicle_type, c.bbox_height,
                   c.bbox_width, c.confidence, c.job_id, v.stored_path,
                   v.video_start_time
            FROM crossings c JOIN video_jobs v ON v.id = c.job_id
            JOIN lane_configs l ON l.id = c.lane_id
            WHERE l.project_id = ? AND c.timestamp >= ? AND c.timestamp < ?
              AND c.vehicle_type IN ({marcas}) AND c.bbox_height IS NOT NULL""",
        (a.proyecto, a.desde, a.hasta, *a.clases)).fetchall()
    cruces = [dict(c) for c in cruces
              if c["lane_id"] in alto_auto
              and c["bbox_height"] >= a.alto_rel_min * alto_auto[c["lane_id"]]]
    print(f"{len(cruces)} cruces por recortar")

    os.makedirs(a.salida, exist_ok=True)
    por_video = defaultdict(list)
    for c in cruces:
        por_video[c["stored_path"]].append(c)

    ruta_indice = os.path.join(a.salida, "indice.json")
    try:
        with open(ruta_indice, encoding="utf-8") as fh:
            indice = json.load(fh)
    except (OSError, ValueError):
        indice = []
    hechos = {e["cruce"] for e in indice}
    sin_pareja = 0
    for ruta, grupo in sorted(por_video.items()):
        grupo = [c for c in grupo if c["id"] not in hechos]
        if not grupo:
            continue
        cap = cv2.VideoCapture(ruta)
        fps = cap.get(cv2.CAP_PROP_FPS) or 20
        alto_cuadro = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        det.set_detection_band(band_from_zones(zonas, alto_cuadro))
        inicio = datetime.fromisoformat(grupo[0]["video_start_time"])
        # El segundo del cruce va truncado; se mira un poco a cada lado.
        ventanas = []
        for c in grupo:
            seg = (datetime.fromisoformat(c["timestamp"]) - inicio).total_seconds()
            primero = max(0, int(seg * fps) - 3)
            ventanas.append((primero, primero + int(fps) + 6, c))
        # Se lee el video DE CORRIDO y se detecta una sola vez por cuadro,
        # compartido entre los cruces cuya ventana lo incluye. Saltar con
        # cap.set a cada cruce obligaba a decodificar desde el ultimo cuadro
        # clave: a 2560x1440 salian ~6 recortes por minuto (mas de 30 h para
        # el dia); de corrido, unas 6 h.
        mejores = {}
        ultimo = max(v[1] for v in ventanas)
        n = 0
        while n < ultimo:
            ok, img = cap.read()
            if not ok:
                break
            activos = [c for ini, fin, c in ventanas if ini <= n < fin]
            if activos:
                dets, _ = det.detect(img)
                for c in activos:
                    carril = carriles[c["lane_id"]]
                    zona = por_id.get(carril.get("zone_id"))
                    linea = carril["points"][:2]
                    for d in dets:
                        x1, y1, x2, y2 = d["bbox"]
                        h, w = y2 - y1, x2 - x1
                        if abs(h / c["bbox_height"] - 1) > TOL_ALTO:
                            continue
                        if c["bbox_width"] and abs(w / c["bbox_width"] - 1) > TOL_ANCHO:
                            continue
                        px, py = _punto_de_apoyo(d["bbox"])
                        if zona and not _contiene(zona["points"], px, py):
                            continue
                        pena = (distancia_a_linea(px, py, linea) / c["bbox_height"]
                                + abs(h / c["bbox_height"] - 1)
                                + (abs(w / c["bbox_width"] - 1) if c["bbox_width"] else 0))
                        previo = mejores.get(c["id"])
                        if previo is None or pena < previo[0]:
                            m = int(0.15 * max(w, h))
                            rec = img[max(0, int(y1) - m):int(y2) + m,
                                      max(0, int(x1) - m):int(x2) + m].copy()
                            mejores[c["id"]] = (pena, n, (x1, y1, x2, y2), rec, d["class_name"])
            n += 1
        for _, _, c in ventanas:
            mejor = mejores.get(c["id"])
            if mejor is None or mejor[0] > 0.6:
                sin_pareja += 1
                continue
            pena, cuadro, (x1, y1, x2, y2), rec, clase_cuadro = mejor
            nombre = f"{c['id']}.jpg"
            cv2.imwrite(os.path.join(a.salida, nombre), rec, [cv2.IMWRITE_JPEG_QUALITY, 90])
            indice.append({
                "archivo": nombre, "cruce": c["id"], "carril": c["lane_id"],
                "hora": c["timestamp"], "clase": c["vehicle_type"],
                "clase_en_el_cuadro": clase_cuadro, "cuadro": cuadro,
                "caja": [round(v, 1) for v in (x1, y1, x2, y2)],
                "alto": c["bbox_height"], "ancho": c["bbox_width"],
                "alto_rel": round(c["bbox_height"] / alto_auto[c["lane_id"]], 3),
                "pena": round(pena, 3)})
        cap.release()
        # Indice al dia despues de cada video: se puede etiquetar mientras
        # sigue recortando, y si se corta se reanuda donde iba.
        with open(ruta_indice, "w", encoding="utf-8") as fh:
            json.dump(indice, fh, indent=0, ensure_ascii=False)
        print(f"  {os.path.basename(os.path.dirname(ruta))}/{os.path.basename(ruta)}: "
              f"{len(indice)} recortes, {sin_pareja} sin pareja", flush=True)

    with open(ruta_indice, "w", encoding="utf-8") as fh:
        json.dump(indice, fh, indent=0, ensure_ascii=False)
    print(f"{len(indice)} recortes; {sin_pareja} cruces sin un vehiculo que se parezca")


if __name__ == "__main__":
    main()
