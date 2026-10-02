"""
¿Cuánto recupera arrancar cada archivo con los últimos segundos del anterior?

    python3 tools/probar_arranque_archivo.py --proyecto 7 \
        --desde "2026-09-19 13:00:00" --hasta "2026-09-19 15:00:00" \
        --segundos 8 --hoja data/presentacion/arranque_13-15.png

Cuenta los primeros `--segundos` de cada archivo dos veces sobre la MISMA
detección —desde cero, como se contó, y con el arranque de
src/engine/arranque.py— por el camino de producción y sin escribir en la
base. "Desde cero" tiene que reproducir lo guardado; si no, la emulación no
es fiel y lo demás no vale.

Lo que el arranque agrega se recorta en su cuadro exacto (`--hoja`) para
revisarlo a ojo: tiene que ser un vehículo de verdad que cruza en el primer
segundo. Al lado va lo que el archivo ANTERIOR contó en sus últimos segundos
en la misma línea, para descartar a ojo que sea el mismo vehículo contado dos
veces.
"""
import argparse
import os
import sys
from datetime import datetime, timedelta

import cv2
import numpy as np
import yaml

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from src.detector import VehicleDetector                                    # noqa: E402
from src.engine import perfil_deteccion                                     # noqa: E402
from src.engine.arranque import archivo_previo_continuo, cuadros_finales    # noqa: E402
from src.engine.lanes import build_lane_counters                            # noqa: E402
from src.engine.zones import (band_from_zones, filter_detections,           # noqa: E402
                              load_zones, zone_for_bbox)
from src.storage import traffic_db                                          # noqa: E402
from src.tracker import VehicleTracker                                      # noqa: E402


class Conteo:
    """Rastreador y contadores de una corrida, como en _process_job."""

    def __init__(self, job, cfg, alto, ancho, zonas):
        t = dict(cfg.get("tracker", {}))
        self.tracker = VehicleTracker(max_age=t.get("max_age", 30), min_hits=t.get("min_hits", 3),
                                      iou_threshold=t.get("iou_threshold", 0.3), config=t)
        self.contadores, self.meta = build_lane_counters(
            job.get("source_label") or "", alto, ancho, project_id=job["project_id"])
        self.zonas = zonas
        self.cruces = []   # (lane_id, cuadro, bbox, tipo)

    def paso(self, dets, cuadro, registrar=True):
        tracks = self.tracker.update([dict(d) for d in dets])
        for lid, cont in self.contadores.items():
            zona = self.meta[lid].get("zone_id")
            vistos = [t for t in tracks
                      if not (zona and self.zonas) or zone_for_bbox(self.zonas, t["bbox"]) == zona]
            c = cont.update(vistos)
            for x in c["in"] + c["out"]:
                tr = next((t for t in vistos if t["id"] == x["track_id"]), None)
                if registrar and tr is not None:
                    self.cruces.append((lid, cuadro, list(tr["bbox"]), tr.get("class_name")))


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0


def sobrantes(b, a):
    """Cruces de `b` sin pareja en `a` (misma línea, ±3 cuadros, caja encimada)."""
    usados, fuera = set(), []
    for cb in b:
        par = next((i for i, ca in enumerate(a) if i not in usados and ca[0] == cb[0]
                    and abs(ca[1] - cb[1]) <= 3 and iou(ca[2], cb[2]) > 0.3), None)
        if par is None:
            fuera.append(cb)
        else:
            usados.add(par)
    return fuera


def recorte(cuadro, bbox, alto=220):
    x1, y1, x2, y2 = (int(v) for v in bbox)
    m = int(0.15 * max(x2 - x1, y2 - y1))
    H, W = cuadro.shape[:2]
    r = cuadro[max(0, y1 - m):min(H, y2 + m), max(0, x1 - m):min(W, x2 + m)]
    if r.size == 0:
        return np.zeros((alto, alto, 3), np.uint8)
    return cv2.resize(r, (int(r.shape[1] * alto / r.shape[0]), alto))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    ap.add_argument("--proyecto", type=int, required=True)
    ap.add_argument("--desde", required=True)
    ap.add_argument("--hasta", required=True)
    ap.add_argument("--segundos", type=float, default=8.0)
    ap.add_argument("--hoja", default=None)
    a = ap.parse_args()

    traffic_db.init_schema()
    conn = traffic_db.get_connection()
    proyecto = traffic_db.get_project(a.proyecto)
    perfil = perfil_deteccion.leer(proyecto)
    if perfil.get("quitar_nacidos_en_pesado") or proyecto.get("conteo_trayectoria"):
        sys.exit("Este proyecto cuenta con opciones que la emulación no reproduce")
    cfg = yaml.safe_load(open(os.path.join(RAIZ, "configs", "platform.yaml"))) or {}
    det_cfg = cfg.get("detector", {})
    general = cfg.get("confidence_threshold", 0.25)
    det = VehicleDetector(perfil.get("modelo") or cfg.get("model_path"), general,
                          det_cfg.get("iou_threshold", 0.5),
                          perfil.get("input_size") or det_cfg.get("input_size", 1280), "auto")
    det.nms_agnostico = bool(proyecto.get("nms_agnostico"))
    det.confidence_threshold = perfil_deteccion.umbral_de_deteccion(perfil, general)
    zonas = load_zones(a.proyecto)

    def detectar(cuadro):
        d = det.detect(cuadro)[0]
        d = perfil_deteccion.filtrar_por_clase(d, perfil, general)
        d = filter_detections(zonas, d)
        if perfil.get("quitar_anidadas"):
            d = perfil_deteccion.quitar_anidadas(d, perfil["quitar_anidadas"])
        return d

    ids = [r[0] for r in conn.execute(
        """SELECT id FROM video_jobs WHERE project_id = ? AND status = 'done'
           AND video_start_time >= ? AND video_start_time < ? ORDER BY video_start_time""",
        (a.proyecto, a.desde, a.hasta)).fetchall()]
    tot = {"archivos": 0, "sin_previo": 0, "guardado": 0, "desde_cero": 0, "arranque": 0,
           "infiel": 0}
    recortes = []
    for jid in ids:
        job = traffic_db.get_video_job(jid)
        previo = archivo_previo_continuo(job)
        if previo is None:
            tot["sin_previo"] += 1
            continue
        cap = cv2.VideoCapture(job["stored_path"])
        fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
        alto, ancho = int(cap.get(4)), int(cap.get(3))
        det.set_detection_band(band_from_zones(zonas, alto) if zonas else None)
        cero, arr = Conteo(job, cfg, alto, ancho, zonas), Conteo(job, cfg, alto, ancho, zonas)
        n_prev = 0
        for indice, cuadro in cuadros_finales(previo["stored_path"]):
            arr.paso(detectar(cuadro), indice, registrar=False)
            n_prev += 1
        guardados_cuadros = {}
        for n in range(int(a.segundos * fps)):
            ok, cuadro = cap.read()
            if not ok:
                break
            d = detectar(cuadro)
            antes = len(arr.cruces)
            cero.paso(d, n)
            arr.paso(d, n)
            if len(arr.cruces) > antes:
                guardados_cuadros[n] = cuadro
        cap.release()

        inicio = datetime.fromisoformat(job["video_start_time"])
        fin = (inicio + timedelta(seconds=a.segundos)).strftime("%Y-%m-%d %H:%M:%S")
        guardado = conn.execute(
            "SELECT count(*) FROM crossings WHERE job_id = ? AND timestamp < ?",
            (jid, fin)).fetchone()[0]
        tot["archivos"] += 1
        tot["guardado"] += guardado
        tot["desde_cero"] += len(cero.cruces)
        tot["arranque"] += len(arr.cruces)
        if len(cero.cruces) != guardado:
            tot["infiel"] += 1
        extra = sobrantes(arr.cruces, cero.cruces)
        falta = sobrantes(cero.cruces, arr.cruces)
        for lid, n, bbox, tipo in extra:
            # Lo que el archivo anterior contó en sus últimos 3 s en esa línea.
            fin_prev = (inicio - timedelta(seconds=3)).strftime("%Y-%m-%d %H:%M:%S")
            prev = conn.execute(
                """SELECT timestamp, bbox_height, vehicle_type FROM crossings
                   WHERE job_id = ? AND lane_id = ? AND timestamp >= ? ORDER BY timestamp""",
                (previo["id"], lid, fin_prev)).fetchall()
            print(f"  + {job['original_name']:12} {inicio:%H:%M} línea {lid} seg {n / fps:4.1f} "
                  f"{tipo} {int(bbox[3] - bbox[1])} px | el anterior contó al final: "
                  + (", ".join(f"{t[11:19]} {h}px {v}" for t, h, v in prev) or "nada"))
            if a.hoja and n in guardados_cuadros:
                r = recorte(guardados_cuadros[n], bbox)
                cv2.putText(r, f"{inicio:%H:%M} L{lid} s{n / fps:.1f}", (6, 22),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
                recortes.append(r)
        for lid, n, bbox, tipo in falta:
            print(f"  - {job['original_name']:12} {inicio:%H:%M} línea {lid} seg {n / fps:4.1f} "
                  f"{tipo}: lo contaba desde cero y con arranque no")

    print(f"\nArchivos: {tot['archivos']} (sin anterior continuo: {tot['sin_previo']})")
    print(f"Primeros {a.segundos:g} s de cada uno: guardado {tot['guardado']}, desde cero "
          f"{tot['desde_cero']} (no reproduce lo guardado en {tot['infiel']}), con arranque "
          f"{tot['arranque']} ({tot['arranque'] - tot['desde_cero']:+d})")
    if a.hoja and recortes:
        filas, ancho_fila, fila = [], 1800, []
        for r in recortes:
            if sum(x.shape[1] for x in fila) + r.shape[1] > ancho_fila and fila:
                filas.append(fila)
                fila = []
            fila.append(r)
        filas.append(fila)
        lienzo = np.zeros((220 * len(filas), ancho_fila, 3), np.uint8)
        for i, f in enumerate(filas):
            x = 0
            for r in f:
                lienzo[i * 220:(i + 1) * 220, x:x + r.shape[1]] = r
                x += r.shape[1]
        cv2.imwrite(a.hoja, lienzo)
        print(f"Hoja: {a.hoja}")


if __name__ == "__main__":
    main()
