"""
Velocidad de videos ya contados, sin recontarlos (src/engine/remedir_velocidad.py).

    python3 tools/remedir_velocidad.py --proyecto 7 --tramos-de 9 \
        --horas "2026-09-19 13:10:00" "2026-09-19 16:10:00" "2026-09-19 21:10:00"

Para cada video cuenta en memoria con el tramo de velocidad y empareja los
cruces recalculados con los guardados. Dice cuántos se reproducen, a cuántos
les da velocidad y la mediana y el percentil 85 por línea. `--tramos-de`
toma el tramo de las líneas de OTRO proyecto con el mismo nombre (el 9 se
calibró sobre la misma cámara que el 7): sirve para probar antes de poner el
tramo en el proyecto. Sin `--aplicar` no escribe nada.
"""
import argparse
import os
import statistics
import sys

import yaml

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from src.detector import VehicleDetector                                    # noqa: E402
from src.engine import perfil_deteccion, remedir_velocidad                  # noqa: E402
from src.engine.velocidad import kmh_de                                     # noqa: E402
from src.storage import traffic_db                                          # noqa: E402


def p85(xs):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(0.85 * (len(xs) - 1))))] if xs else None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    ap.add_argument("--proyecto", type=int, required=True)
    ap.add_argument("--horas", nargs="+", required=True,
                    help='inicio de cada video, como está en la base')
    ap.add_argument("--tramos-de", type=int, default=None)
    ap.add_argument("--aplicar", action="store_true")
    a = ap.parse_args()

    traffic_db.init_schema()
    conn = traffic_db.get_connection()
    perfil = perfil_deteccion.leer(traffic_db.get_project(a.proyecto))
    cfg = yaml.safe_load(open(os.path.join(RAIZ, "configs", "platform.yaml"))) or {}
    det_cfg = cfg.get("detector", {})
    det = VehicleDetector(perfil.get("modelo") or cfg.get("model_path"),
                          cfg.get("confidence_threshold", 0.25), det_cfg.get("iou_threshold", 0.5),
                          perfil.get("input_size") or det_cfg.get("input_size", 1280), "auto")
    lineas = traffic_db.list_lanes(project_id=a.proyecto)
    tramos = None
    if a.tramos_de:
        otras = {l["name"]: l.get("tramo") for l in traffic_db.list_lanes(project_id=a.tramos_de)}
        tramos = {l["id"]: otras.get(l["name"]) for l in lineas}
        print("tramos:", {l["name"]: tramos[l["id"]] and tramos[l["id"]]["distancia_m"] for l in lineas})
    distancia = {l["id"]: ((tramos or {}).get(l["id"]) or l.get("tramo") or {}).get("distancia_m")
                 for l in lineas}
    nombre = {l["id"]: l["name"] for l in lineas}

    for hora in a.horas:
        fila = conn.execute("SELECT id FROM video_jobs WHERE project_id = ? AND video_start_time = ?",
                            (a.proyecto, hora)).fetchone()
        if fila is None:
            print(f"{hora}: no hay video")
            continue
        job = traffic_db.get_video_job(fila[0])
        cruces, _ = remedir_velocidad.medir(job, det, cfg, tramos=tramos)
        pares = remedir_velocidad.emparejar(job, cruces)
        guardados = conn.execute("SELECT count(*) FROM crossings WHERE job_id = ?",
                                 (job["id"],)).fetchone()[0]
        con = [p for p in pares if p[1] is not None]
        print(f"{hora[11:16]}  guardados {guardados}  recalculados {len(cruces)}  "
              f"emparejados {len(pares)} ({100 * len(pares) / max(1, guardados):.0f} %)  "
              f"con velocidad {len(con)} ({100 * len(con) / max(1, guardados):.0f} %)")
        por_linea = {}
        ids = {cid: s for cid, s in con}
        for cid, lid in conn.execute("SELECT id, lane_id FROM crossings WHERE job_id = ?",
                                     (job["id"],)).fetchall():
            if cid in ids and distancia.get(lid):
                k = kmh_de(distancia[lid], ids[cid])
                if k is not None:
                    por_linea.setdefault(lid, []).append(k)
        for lid, ks in por_linea.items():
            print(f"      {nombre[lid]:22} n={len(ks):3}  mediana {statistics.median(ks):5.1f}  "
                  f"p85 {p85(ks):5.1f} km/h")
        if a.aplicar:
            print("      escritos:", remedir_velocidad.aplicar(pares))


if __name__ == "__main__":
    main()
