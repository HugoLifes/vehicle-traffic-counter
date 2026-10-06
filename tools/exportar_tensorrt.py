"""
Crea el motor TensorRT FP16 que usa el detector para un proyecto.

TensorRT es la mitad del costo de detectar en el Orin, con las mismas
detecciones (medido sobre la franja del proyecto 7, 300 cuadros de día y 300
de noche: 1 944 y 298 detecciones con los dos, la misma clase en 99.6 y
100 %, confianza movida 0.001; 63 -> 30 ms por cuadro). Pero un motor sirve
para UN tamaño de entrada exacto, y ese tamaño sale de la franja de la vía y
del input_size del proyecto. Por eso se crea por proyecto, con esta
herramienta, y no al vuelo: tarda ~9 min de GPU en el Orin.

El detector lo toma solo cuando `use_tensorrt` está encendido en
configs/platform.yaml y existe el archivo; si no, cuenta con el .pt como
siempre. Hay que correrlo con la cola vacía: dos trabajos de GPU a la vez
en el Orin dan `NvMapMemAllocInternalTagged error 12` y cuadros sin detección.

    python tools/exportar_tensorrt.py --proyecto 7
    python tools/exportar_tensorrt.py --proyecto 7 --solo-ver   # qué motor necesita
"""
import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--proyecto", type=int, required=True)
    ap.add_argument("--solo-ver", action="store_true", help="decir qué motor hace falta y si ya existe")
    ap.add_argument("--forzar", action="store_true", help="exportar aunque haya videos en la cola")
    a = ap.parse_args()

    import cv2
    import yaml
    from src.detector import VehicleDetector
    from src.engine.zones import band_from_zones
    from src.storage import traffic_db

    cfg = yaml.safe_load(open(RAIZ / "configs" / "platform.yaml", encoding="utf-8"))
    det = cfg.get("detector", {})
    proyecto = traffic_db.get_project(a.proyecto)
    if proyecto is None:
        sys.exit(f"No existe el proyecto {a.proyecto}")
    perfil = proyecto.get("perfil_deteccion") or {}
    if isinstance(perfil, str):
        perfil = json.loads(perfil or "{}")
    modelo = perfil.get("modelo") or cfg.get("model_path") or det.get("model_path", "models/yolov8s.pt")
    input_size = perfil.get("input_size") or det.get("input_size", 640)

    # Tamaño del cuadro: el del primer video del proyecto que abra.
    alto = ancho = None
    for (ruta,) in traffic_db.get_connection().execute(
            "SELECT stored_path FROM video_jobs WHERE project_id = ? ORDER BY id", (a.proyecto,)):
        cap = cv2.VideoCapture(ruta)
        if cap.isOpened():
            ancho, alto = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()
            break
    if not alto:
        sys.exit("El proyecto no tiene ningún video legible para saber el tamaño del cuadro.")

    # La franja, igual que el procesador: zonas primero, si no, las líneas.
    banda = band_from_zones(traffic_db.list_zones(a.proyecto), alto)
    if banda is None:
        lineas = [l["points"] for l in traffic_db.list_lanes(project_id=a.proyecto) if l.get("points")]
        banda = VehicleDetector.band_from_lanes(
            lineas, alto, margin_ratio=det.get("band", {}).get("margin_ratio", 0.15)) if lineas else None
    alto_entrada = (banda[1] - banda[0]) if banda else alto

    d = VehicleDetector.__new__(VehicleDetector)
    d.input_size, d.model_path = input_size, modelo
    forma = d.forma_de_entrada(alto_entrada, ancho)
    destino = d.ruta_motor(forma)
    print(f"Proyecto {a.proyecto}: cuadro {ancho}x{alto}, franja {banda}, input_size {input_size}")
    print(f"Motor: {destino}  ({'ya existe' if destino.exists() else 'falta'})")
    print(f"TensorRT en platform.yaml: {'encendido' if det.get('use_tensorrt') else 'APAGADO'}")
    if a.solo_ver or destino.exists():
        return

    ocupados = sqlite3.connect(f"file:{traffic_db.DB_PATH}?mode=ro", uri=True).execute(
        "SELECT COUNT(*) FROM video_jobs WHERE status IN ('queued','processing') "
        "OR diag_estado IS NOT NULL OR anotado_estado IN ('en_cola','generando')").fetchone()[0]
    if ocupados and not a.forzar:
        sys.exit(f"Hay {ocupados} trabajos en la cola de la GPU. Espera a que terminen "
                 "(o --forzar, sabiendo que pueden salir cuadros sin detección).")

    from ultralytics import YOLO
    t0 = time.time()
    hecho = YOLO(modelo).export(format="engine", imgsz=forma, half=True, device=0, workspace=2)
    Path(hecho).rename(destino)
    Path(hecho).with_suffix(".onnx").unlink(missing_ok=True)
    print(f"Listo en {(time.time() - t0) / 60:.1f} min: {destino}. "
          "El siguiente video del proyecto ya lo usa (no hace falta reiniciar).")


if __name__ == "__main__":
    main()
