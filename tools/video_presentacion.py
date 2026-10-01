"""
Clip corto para presentar el sistema: el video de la cámara con cada
vehículo que cruza la línea, su clase y el conteo por sentido.

    python3 tools/video_presentacion.py --proyecto 7 --hora "2026-09-19 14:56:00" \
        --desde 0 --segundos 30 --salida data/presentacion/aforo_14-56.mp4

Es el mismo dibujo que el visor en vivo y el video con detecciones de la
plataforma (src/engine/presentacion.py), a 1920 de ancho. No escribe en la
base: detecta, rastrea, cuenta y clasifica por el camino de producción y
solo dibuja. El título de cada marcador es el nombre de la línea, el
encabezado lleva la dirección del proyecto y la hora real del video, y la
leyenda de la cámara se difumina si el perfil trae `tapar_leyenda`.

Al final compara su conteo con lo guardado en la base para el mismo tramo:
si no coincide, el clip no muestra lo que la plataforma contó.
"""
import argparse
import os
import sys
from datetime import datetime, timedelta

import yaml

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from src.detector import VehicleDetector                                    # noqa: E402
from src.engine import perfil_deteccion                                     # noqa: E402
from src.engine.clasificador_pesados import ClasificadorPesados             # noqa: E402
from src.engine.presentacion import generar_video, nombre_sentido           # noqa: E402
from src.storage import traffic_db                                          # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    ap.add_argument("--proyecto", type=int, required=True)
    ap.add_argument("--hora", required=True,
                    help='inicio del video, como está en la base: "2026-09-19 14:56:00"')
    ap.add_argument("--desde", type=float, default=0.0,
                    help="segundo del video donde empieza el clip; negativo toma los últimos "
                         "segundos del video anterior")
    ap.add_argument("--segundos", type=float, default=30.0)
    ap.add_argument("--salida", required=True)
    ap.add_argument("--lugar", default=None,
                    help="texto junto a la hora; por omisión, la dirección del proyecto")
    a = ap.parse_args()

    traffic_db.init_schema()
    conn = traffic_db.get_connection()
    fila = conn.execute(
        "SELECT id FROM video_jobs WHERE project_id = ? AND video_start_time = ?",
        (a.proyecto, a.hora)).fetchone()
    if fila is None:
        sys.exit(f"No hay video del proyecto {a.proyecto} que empiece a las {a.hora}")
    job = traffic_db.get_video_job(fila[0])
    perfil = perfil_deteccion.leer(traffic_db.get_project(a.proyecto))
    cfg = yaml.safe_load(open(os.path.join(RAIZ, "configs", "platform.yaml"))) or {}
    det_cfg = cfg.get("detector", {})
    det = VehicleDetector(perfil.get("modelo") or cfg.get("model_path"),
                          cfg.get("confidence_threshold", 0.25),
                          det_cfg.get("iou_threshold", 0.5),
                          perfil.get("input_size") or det_cfg.get("input_size", 1280), "auto")
    clasif = tuple(ClasificadorPesados(os.path.join(RAIZ, perfil[c])) if perfil.get(c) else None
                   for c in ("clasificador_pesados", "clasificador_livianos"))

    os.makedirs(os.path.dirname(os.path.abspath(a.salida)), exist_ok=True)
    fuente, desde, temporal = job, a.desde, None
    # Un clip que empieza en el corte entre dos archivos: el vehículo que va
    # cruzando en el primer cuadro cruzó en el archivo ANTERIOR, y el clip lo
    # enseñaba pasando la línea sin contarse (14:56:00, una camioneta). Con
    # --desde negativo se pegan los segundos finales del archivo previo, para
    # que se vea llegar y contarse; solo si los dos son consecutivos.
    if a.desde < 0:
        previo = conn.execute(
            """SELECT id FROM video_jobs WHERE project_id = ? AND video_start_time < ?
               ORDER BY video_start_time DESC LIMIT 1""", (a.proyecto, a.hora)).fetchone()
        if previo is None:
            sys.exit("No hay un video anterior del que tomar los segundos previos")
        anterior = traffic_db.get_video_job(previo[0])
        dur = (anterior.get("total_frames") or 0) / (anterior.get("fps") or 20.0)
        fin_anterior = datetime.fromisoformat(anterior["video_start_time"]) + timedelta(seconds=dur)
        hueco = (datetime.fromisoformat(job["video_start_time"]) - fin_anterior).total_seconds()
        if abs(hueco) > 1.0:
            sys.exit(f"El video anterior no es continuo ({hueco:+.1f} s entre los dos): "
                     "pegarlos correría la hora")
        import subprocess
        import tempfile
        import imageio_ffmpeg
        temporal = os.path.join(RAIZ, "data", "presentacion", f"_pegado_{job['id']}.mp4")
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as lista:
            lista.write(f"file '{os.path.abspath(anterior['stored_path'])}'\n")
            lista.write(f"file '{os.path.abspath(job['stored_path'])}'\n")
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "concat",
                        "-safe", "0", "-i", lista.name, "-c", "copy", temporal], check=True)
        os.unlink(lista.name)
        fuente = dict(job, stored_path=temporal, video_start_time=anterior["video_start_time"])
        desde = dur + a.desde
    try:
        conteo = generar_video(fuente, det, cfg, a.salida, ancho=1920, desde=desde,
                               segundos=a.segundos, clasificadores=clasif, lugar=a.lugar,
                               para_web=False)
    finally:
        if temporal:
            os.unlink(temporal)

    # Lo que guardó la plataforma en ese tramo, para comprobar (los dos
    # archivos, si se pegó el anterior).
    inicio = datetime.fromisoformat(job["video_start_time"])
    ids = (job["id"], previo[0]) if a.desde < 0 else (job["id"], job["id"])
    t0 = (inicio + timedelta(seconds=a.desde)).strftime("%Y-%m-%d %H:%M:%S")
    t1 = (inicio + timedelta(seconds=a.desde + a.segundos)).strftime("%Y-%m-%d %H:%M:%S")
    guardado = dict(conn.execute(
        """SELECT lane_id, count(*) FROM crossings WHERE job_id IN (?, ?)
           AND timestamp >= ? AND timestamp < ? GROUP BY lane_id""",
        (*ids, t0, t1)).fetchall())
    nombres = {l["id"]: l["name"] for l in traffic_db.list_lanes(project_id=a.proyecto)}
    for lid, c in conteo.items():
        print(f"{nombre_sentido(nombres.get(lid, str(lid))):24} clip {sum(c.values()):3}  "
              f"base {guardado.get(lid, 0):3}  "
              + "  ".join(f"{k} {v}" for k, v in c.most_common()))
    print(f"Listo: {a.salida}")


if __name__ == "__main__":
    main()
