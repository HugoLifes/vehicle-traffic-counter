"""
Velocidad de un video ya contado, sin recontarlo.

La velocidad se mide al contar (MedidorVelocidad, en el procesador): un
video contado cuando su línea no tenía tramo se queda sin velocidad. Volver
a contarlo la daría, pero recontar borra los cruces y con ellos lo que se
les agregó después —en el aforo frontal, la clase revisada de 879 pesados—.

Aquí se cuenta en memoria por el mismo camino que _process_job, con el tramo
vigente, y solo se escribe el TIEMPO de paso en los cruces que ya existen.
Cada cruce recalculado se empareja con el guardado de la misma línea, del
mismo segundo y con la caja del mismo alto (el conteo es determinista: con
la misma configuración reproduce lo guardado). Lo que no se empareja se
queda sin velocidad, y la hora solo publica velocidad si se midió a la
mayoría de sus vehículos (velocidad.FRACCION_MINIMA).

No usa el arranque con el archivo anterior (arranque.py): los cruces
guardados se contaron sin él, y el emparejamiento tiene que ver lo mismo.
"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import cv2

# Diferencia de alto de caja tolerada al emparejar un cruce recalculado con
# el guardado del mismo segundo y la misma línea.
TOLERANCIA_ALTO = 0.12


def medir(job: Dict, detector, config: Dict, detener=None, progreso=None,
          tramos: Optional[Dict[int, Dict]] = None
          ) -> Tuple[List[Dict], Dict[Tuple[int, int], float]]:
    """(cruces recalculados, {(lane_id, track_id): segundos de tramo}).

    `tramos` ({lane_id: tramo}) sustituye al de las líneas: sirve para probar
    un tramo antes de ponerlo en el proyecto."""
    from src.detector import VehicleDetector
    from src.engine import perfil_deteccion
    from src.engine.lanes import build_lane_counters
    from src.engine.velocidad import MedidorVelocidad
    from src.engine.zones import band_from_zones, filter_detections, load_zones, zone_for_bbox
    from src.storage import traffic_db
    from src.tracker import VehicleTracker

    proyecto = traffic_db.get_project(job.get("project_id")) or {}
    perfil = perfil_deteccion.leer(proyecto)
    general = config.get("confidence_threshold", 0.25)
    cap = cv2.VideoCapture(job["stored_path"])
    if not cap.isOpened():
        raise RuntimeError(f"No se pudo abrir {job['stored_path']}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
    H, W = int(cap.get(4)), int(cap.get(3))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or None
    zonas = load_zones(job.get("project_id"))
    contadores, meta = build_lane_counters(job.get("source_label") or "", H, W,
                                           project_id=job.get("project_id"))
    tramo_de = {lid: (tramos or {}).get(lid) or m.get("tramo") for lid, m in meta.items()}
    medidores = {lid: MedidorVelocidad(meta[lid]["points"], tr["linea"], tr["distancia_m"], fps)
                 for lid, tr in tramo_de.items() if tr and tr.get("distancia_m")}
    if not medidores:
        cap.release()
        raise RuntimeError("Ninguna línea del proyecto tiene tramo de velocidad")
    detector.nms_agnostico = bool(proyecto.get("nms_agnostico"))
    detector.confidence_threshold = perfil_deteccion.umbral_de_deteccion(perfil, general)
    band_cfg = config.get("detector", {}).get("band", {})
    if band_cfg.get("enabled", True):
        banda = band_from_zones(zonas, H) if zonas else None
        if banda is None:
            banda = VehicleDetector.band_from_lanes(
                [m["points"] for m in meta.values()], H,
                margin_ratio=band_cfg.get("margin_ratio", 0.15))
        detector.set_detection_band(banda)
    else:
        detector.set_detection_band(None)
    t = dict(config.get("tracker", {}))
    tracker = VehicleTracker(max_age=t.get("max_age", 30), min_hits=t.get("min_hits", 3),
                             iou_threshold=t.get("iou_threshold", 0.3), config=t)
    quitar_nacidos = bool(perfil.get("quitar_nacidos_en_pesado"))
    vistos_ids, nacidos = set(), set()
    cruces, tiempos = [], {}
    n = 0
    try:
        while True:
            if detener is not None and detener():
                raise InterruptedError("Se detuvo el servicio")
            ok, cuadro = cap.read()
            if not ok:
                break
            dets = perfil_deteccion.filtrar_por_clase(detector.detect(cuadro)[0], perfil, general)
            dets = filter_detections(zonas, dets)
            if perfil.get("quitar_anidadas"):
                dets = perfil_deteccion.quitar_anidadas(dets, perfil["quitar_anidadas"])
            tracks = tracker.update(dets)
            if quitar_nacidos:
                for tr in tracks:
                    if tr["id"] not in vistos_ids:
                        vistos_ids.add(tr["id"])
                        if perfil_deteccion.nacio_dentro_de_pesado(
                                tr["bbox"], tracks, propio_id=tr["id"]) is not None:
                            nacidos.add(tr["id"])
            for lid, cont in contadores.items():
                zona = meta[lid].get("zone_id")
                vistos = ([x for x in tracks if zone_for_bbox(zonas, x["bbox"]) == zona]
                          if zona and zonas else tracks)
                for c in (lambda r: r["in"] + r["out"])(cont.update(vistos)):
                    if c["track_id"] in nacidos:
                        continue
                    tr = next((x for x in vistos if x["id"] == c["track_id"]), None)
                    if tr is not None:
                        cruces.append({"lane_id": lid, "track_id": tr["id"], "cuadro": n,
                                       "alto": int(tr["bbox"][3] - tr["bbox"][1])})
                if lid in medidores:
                    for m in medidores[lid].observar(n, vistos):
                        tiempos[(lid, m["track_id"])] = m["segundos"]
            n += 1
            if progreso is not None and total and n % 100 == 0:
                progreso(min(1.0, n / total))
    finally:
        cap.release()
    for c in cruces:
        c["segundos"] = tiempos.get((c["lane_id"], c["track_id"]))
        c["fps"] = fps
    return cruces, tiempos


def emparejar(job: Dict, cruces: List[Dict]) -> List[Tuple[int, Optional[float]]]:
    """[(id del cruce guardado, segundos de tramo o None)] para los cruces
    guardados del video que tienen pareja recalculada."""
    from src.storage import traffic_db
    inicio = (datetime.fromisoformat(job["video_start_time"])
              if job.get("video_start_time") else None)
    guardados = traffic_db.get_connection().execute(
        "SELECT id, lane_id, track_id, timestamp, bbox_height FROM crossings WHERE job_id = ?",
        (job["id"],)).fetchall()
    libres = list(cruces)
    pares = []
    # Primero por identidad del rastro: con la misma configuración el conteo
    # reproduce los mismos números de rastro.
    por_id = {(c["lane_id"], c["track_id"]): c for c in libres}
    pendientes = []
    for g in guardados:
        c = por_id.get((g[1], g[2]))
        if c is not None and _mismo_cruce(c, g, inicio):
            pares.append((g[0], c["segundos"]))
            libres.remove(c)
            por_id.pop((g[1], g[2]))
        else:
            pendientes.append(g)
    # Lo demás, por línea, segundo y alto de la caja.
    for g in pendientes:
        candidatos = [c for c in libres if _mismo_cruce(c, g, inicio)]
        if candidatos:
            c = min(candidatos, key=lambda x: abs(x["alto"] - (g[4] or 0)))
            pares.append((g[0], c["segundos"]))
            libres.remove(c)
    return pares


def _mismo_cruce(c: Dict, g, inicio) -> bool:
    if c["lane_id"] != g[1]:
        return False
    if inicio is not None and g[3]:
        segundo = (inicio + timedelta(seconds=c["cuadro"] / c["fps"])).strftime("%Y-%m-%d %H:%M:%S")
        guardado = datetime.fromisoformat(g[3])
        if abs((datetime.fromisoformat(segundo) - guardado).total_seconds()) > 1:
            return False
    if g[4]:
        return abs(c["alto"] - g[4]) <= TOLERANCIA_ALTO * g[4]
    return True


def aplicar(pares: List[Tuple[int, Optional[float]]]) -> int:
    """Escribe el tiempo de tramo en los cruces emparejados; devuelve cuántos
    quedaron con velocidad."""
    from src.storage import traffic_db
    con = [(round(s, 4), cid) for cid, s in pares if s is not None]
    if not con:
        return 0
    conn = traffic_db.get_connection()
    conn.executemany("UPDATE crossings SET tiempo_tramo_s = ? WHERE id = ?", con)
    conn.commit()
    return len(con)
