"""
Clip corto para presentar el sistema: el video de la cámara con cada
vehículo que cruza la línea, su clase y el conteo por sentido.

    python3 tools/video_presentacion.py --proyecto 7 --hora "2026-09-19 14:56:00" \
        --desde 0 --segundos 30 --salida data/presentacion/aforo_14-56.mp4

No escribe en la base: detecta, rastrea, cuenta y clasifica por el mismo
camino que producción (perfil de detección del proyecto, zonas, líneas
atadas a su calzada, regla del alto y clasificadores del perfil) y solo
dibuja. El anotado de la plataforma es para revisar líneas y zonas —trae
las etiquetas de COCO ("truck") y no la clase que se entrega—; este muestra
lo que la empresa recibe: automóvil, camioneta, pickup, moto, autobús,
camión, tractocamión y tractor.

Arranca a contar unos segundos ANTES del tramo para que el rastreador ya
venga siguiendo a los vehículos: al empezar un archivo el que va cruzando
no se cuenta (ver "Cada archivo que empieza cuesta 0.3-0.5 %" en CLAUDE.md).
Lo que cruza en esos segundos previos no entra en el marcador.

Al final compara su conteo con lo guardado en la base para el mismo tramo:
si no coincide, el clip no muestra lo que la plataforma contó.
"""
import argparse
import os
import statistics
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta

import cv2
import imageio_ffmpeg
import numpy as np
import yaml
from PIL import Image, ImageDraw, ImageFont

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from src.detector import VehicleDetector                                    # noqa: E402
from src.engine import perfil_deteccion                                     # noqa: E402
from src.engine.clasificacion import (clasificar, nivel_de_calzada,         # noqa: E402
                                      perfil_de_calzada)
from src.engine.clasificador_pesados import (ClasificadorPesados,           # noqa: E402
                                             clase_final, subtipo_final)
from src.engine.lanes import build_lane_counters                            # noqa: E402
from src.engine.zones import (band_from_zones, filter_detections,           # noqa: E402
                              load_zones, zone_for_bbox)
from src.storage import traffic_db                                          # noqa: E402
from src.tracker import VehicleTracker                                      # noqa: E402

ANCHO, ALTO = 1920, 1080
# Segundos que se procesan antes del tramo, solo para que el rastreador
# llegue al primer cuadro con los vehículos ya seguidos.
PREVIO_S = 3.0

# Orden y nombre de las clases tal como las entrega el Excel.
CLASES = [
    ("AUTO", "Automóvil", (79, 195, 247)),
    ("CAMIONETA", "Camioneta / SUV", (129, 199, 132)),
    ("PICKUP", "Pickup", (255, 213, 79)),
    ("MOTO", "Motocicleta", (240, 98, 146)),
    ("B", "Autobús", (255, 138, 101)),
    ("C", "Camión", (186, 104, 200)),
    ("T-S", "Tractocamión", (229, 115, 115)),
    ("TRACTOR", "Tractor sin caja", (188, 170, 164)),
]
NOMBRE = {k: n for k, n, _ in CLASES}
COLOR = {k: c for k, _, c in CLASES}
# A sin subtipo (el clasificador dudó): se cuenta como liviano sin más.
NOMBRE["A"] = "Otro liviano"
COLOR["A"] = (220, 220, 220)


def fuente(tam, negrita=False):
    nombre = "DejaVuSans-Bold.ttf" if negrita else "DejaVuSans.ttf"
    for base in ("/usr/share/fonts/truetype/dejavu", "C:/Windows/Fonts"):
        ruta = os.path.join(base, nombre)
        if os.path.exists(ruta):
            return ImageFont.truetype(ruta, tam)
    return ImageFont.load_default()


def escala_por_carril(project_id):
    """Umbral de pesado y perfil (fino, silueta del auto) de cada línea,
    con las horas de día del propio aforo, igual que get_interval_counts."""
    conn = traffic_db.get_connection()
    filas = conn.execute(
        """SELECT cr.lane_id, cr.vehicle_type, cr.bbox_height, cr.bbox_width, cr.confidence
           FROM crossings cr JOIN lane_configs l ON l.id = cr.lane_id
           WHERE l.project_id = ? AND substr(cr.timestamp, 12, 2) BETWEEN '08' AND '18'""",
        (project_id,)).fetchall()
    umbral, perfil = {}, {}
    for lane in {f[0] for f in filas}:
        propios = [f for f in filas if f[0] == lane]
        umbral[lane] = nivel_de_calzada(f[2] for f in propios if f[1] == "car")[1]
        perfil[lane] = perfil_de_calzada([
            {"vehicle_type": f[1], "bbox_height": f[2], "bbox_width": f[3]} for f in propios])
    return umbral, perfil


def pastilla(d, x, y, texto, color, f):
    """Etiqueta con fondo del color de la clase, encima de la caja."""
    l, t, r, b = d.textbbox((0, 0), texto, font=f)
    w, h = r - l + 14, b - t + 8
    y = max(0, y - h - 3)
    d.rounded_rectangle((x, y, x + w, y + h), radius=5, fill=color + (235,))
    d.text((x + 7, y + 4 - t), texto, font=f, fill=(20, 20, 24, 255))


def panel(d, x, y, titulo, subtitulo, conteo, recien, fuentes):
    """Marcador de un sentido: total grande y el desglose por clase."""
    f_tit, f_sub, f_total, f_fila = fuentes
    filas = len(CLASES) + (1 if conteo.get("A") else 0)
    w, h = 380, 132 + 29 * filas
    d.rounded_rectangle((x, y, x + w, y + h), radius=14, fill=(14, 18, 24, 190))
    d.text((x + 20, y + 14), titulo, font=f_tit, fill=(255, 255, 255, 255))
    total = sum(conteo.values())
    d.text((x + 20, y + 44), f"{total}", font=f_total, fill=(255, 255, 255, 255))
    d.text((x + 24 + d.textlength(f"{total}", font=f_total), y + 74), subtitulo,
           font=f_sub, fill=(170, 180, 190, 255))
    yy = y + 118
    for clave, nombre, color in CLASES + [("A", NOMBRE["A"], COLOR["A"])]:
        n = conteo.get(clave, 0)
        if clave == "A" and not n:
            continue
        brillo = 255 if n else 110
        resaltar = recien.get(clave, 0) > 0
        if resaltar:
            d.rounded_rectangle((x + 10, yy - 3, x + w - 10, yy + 25), radius=6,
                                fill=color + (80,))
        d.rounded_rectangle((x + 20, yy + 3, x + 36, yy + 19), radius=4,
                            fill=color + ((255,) if n else (90,)))
        d.text((x + 48, yy), nombre, font=f_fila, fill=(brillo, brillo, brillo, 255))
        txt = str(n)
        d.text((x + w - 22 - d.textlength(txt, font=f_fila), yy), txt, font=f_fila,
               fill=(brillo, brillo, brillo, 255))
        yy += 29


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    ap.add_argument("--proyecto", type=int, required=True)
    ap.add_argument("--hora", required=True,
                    help='inicio del video, como está en la base: "2026-09-19 14:56:00"')
    ap.add_argument("--desde", type=float, default=0.0, help="segundo del video donde empieza el clip")
    ap.add_argument("--segundos", type=float, default=30.0)
    ap.add_argument("--salida", required=True)
    ap.add_argument("--lugar", default="Blvd. Miguel de la Madrid · Cd. Juárez")
    ap.add_argument("--tapar", default=None,
                    help="x1,y1,x2,y2 del clip (1920x1080) a difuminar: la leyenda de "
                         "la cámara, que en el frontal dice otra fecha y otra hora "
                         "(ver revisar_reloj.py)")
    a = ap.parse_args()

    traffic_db.init_schema()
    conn = traffic_db.get_connection()
    fila = conn.execute(
        "SELECT id FROM video_jobs WHERE project_id = ? AND video_start_time = ?",
        (a.proyecto, a.hora)).fetchone()
    if fila is None:
        sys.exit(f"No hay video del proyecto {a.proyecto} que empiece a las {a.hora}")
    job = traffic_db.get_video_job(fila[0])
    proyecto = traffic_db.get_project(a.proyecto) or {}
    perfil = perfil_deteccion.leer(proyecto)
    cfg = yaml.safe_load(open(os.path.join(RAIZ, "configs", "platform.yaml"))) or {}
    det_cfg = cfg.get("detector", {})

    cap = cv2.VideoCapture(job["stored_path"])
    if not cap.isOpened():
        sys.exit(f"No abre {job['stored_path']}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
    alto, ancho = int(cap.get(4)), int(cap.get(3))

    zonas = load_zones(a.proyecto)
    det = VehicleDetector(perfil.get("modelo") or cfg.get("model_path"),
                          cfg.get("confidence_threshold", 0.25),
                          det_cfg.get("iou_threshold", 0.5),
                          perfil.get("input_size") or det_cfg.get("input_size", 1280), "auto")
    det.nms_agnostico = bool(proyecto.get("nms_agnostico"))
    det.confidence_threshold = perfil_deteccion.umbral_de_deteccion(
        perfil, cfg.get("confidence_threshold", 0.25))
    det.set_detection_band(band_from_zones(zonas, alto) if zonas else None)
    t = dict(cfg.get("tracker", {}))
    trk = VehicleTracker(max_age=t.get("max_age", 30), min_hits=t.get("min_hits", 3),
                         iou_threshold=t.get("iou_threshold", 0.3), config=t)
    contadores, meta = build_lane_counters(job.get("source_label") or "", alto, ancho,
                                           project_id=a.proyecto)
    pesados = (ClasificadorPesados(os.path.join(RAIZ, perfil["clasificador_pesados"]))
               if perfil.get("clasificador_pesados") else None)
    livianos = (ClasificadorPesados(os.path.join(RAIZ, perfil["clasificador_livianos"]))
                if perfil.get("clasificador_livianos") else None)
    umbral, perfil_carril = escala_por_carril(a.proyecto)
    horas_sub = perfil.get("horas_subtipo", (7, 19))
    inicio = datetime.fromisoformat(job["video_start_time"])

    s = ANCHO / ancho
    os.makedirs(os.path.dirname(os.path.abspath(a.salida)), exist_ok=True)
    ff = subprocess.Popen(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{ANCHO}x{ALTO}", "-r", f"{fps}",
         "-i", "-", "-c:v", "libx264", "-preset", "slow", "-crf", "18",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", a.salida],
        stdin=subprocess.PIPE)

    f_tit, f_sub = fuente(24, True), fuente(18)
    f_total, f_fila = fuente(54, True), fuente(20)
    f_etq, f_cab, f_reloj = fuente(20, True), fuente(30, True), fuente(24)
    # Sentido de cada línea por su calzada, con el nombre que lleva el Excel.
    sentidos = {}
    for lane_id, m in meta.items():
        nombre = m["name"].replace("Carril ", "")
        nombre = nombre.replace("camara", "cámara").replace("alejandose", "alejándose")
        sentidos[lane_id] = nombre[:1].upper() + nombre[1:]
    destello = {lid: (0, None) for lid in meta}   # cuadros que le quedan, color
    conteo = {lid: Counter() for lid in meta}
    recien = {lid: Counter() for lid in meta}
    contados = {}   # track_id -> (clase, cuadro del cruce)
    cuadro0 = int((a.desde - PREVIO_S) * fps)
    cuadro_ini = int(a.desde * fps)
    cuadro_fin = int((a.desde + a.segundos) * fps)
    n = 0
    while n < cuadro_fin:
        ok, frame = cap.read()
        if not ok:
            break
        if n < cuadro0:
            n += 1
            continue
        dets = det.detect(frame)[0]
        dets = perfil_deteccion.filtrar_por_clase(dets, perfil, cfg.get("confidence_threshold", 0.25))
        dets = filter_detections(zonas, dets)
        tracks = trk.update(dets)
        hora = (inicio + timedelta(seconds=n / fps))
        for lid, cont in contadores.items():
            zona = meta[lid].get("zone_id")
            vistos = [tr for tr in tracks if not zona or zone_for_bbox(zonas, tr["bbox"]) == zona]
            cruces = cont.update(vistos)
            for c in cruces["in"] + cruces["out"]:
                tr = next((x for x in vistos if x["id"] == c["track_id"]), None)
                if tr is None or n < cuadro_ini:
                    continue
                x1, y1, x2, y2 = tr["bbox"]
                pc = perfil_carril.get(lid) or {}
                clase = clasificar(tr["class_name"], y2 - y1, umbral.get(lid), ancho=x2 - x1,
                                   perfil=pc)
                if pesados is not None:
                    r = pesados.clasificar(frame, tr["bbox"])
                    if r:
                        clase = clase_final(clase, r[0], r[1], bool(pc.get("fino")))
                if clase == "A" and livianos is not None:
                    r = livianos.clasificar(frame, tr["bbox"])
                    sub = subtipo_final(r[0] if r else None, r[1] if r else None,
                                        hora.hour, horas_sub, bool(pc.get("fino")))
                    if sub != "SIN_SUBTIPO":
                        clase = sub
                contados[tr["id"]] = (clase, n)
                conteo[lid][clase] += 1
                recien[lid][clase] = int(fps * 0.8)
                destello[lid] = (int(fps * 0.4), COLOR.get(clase, (255, 255, 255)))
        if n < cuadro_ini:
            n += 1
            continue

        cuadro = cv2.resize(frame, (ANCHO, ALTO), interpolation=cv2.INTER_AREA)
        if a.tapar:
            tx1, ty1, tx2, ty2 = (int(v) for v in a.tapar.split(","))
            cuadro[ty1:ty2, tx1:tx2] = cv2.GaussianBlur(cuadro[ty1:ty2, tx1:tx2], (0, 0), 14)
        img = Image.fromarray(cv2.cvtColor(cuadro, cv2.COLOR_BGR2RGB)).convert("RGBA")
        capa = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(capa)
        # Líneas de conteo, sobre la calzada de cada sentido.
        for lid, m in meta.items():
            (ax, ay), (bx, by) = m["points"][0], m["points"][-1]
            quedan, col = destello[lid]
            if quedan:
                d.line((ax * s, ay * s, bx * s, by * s), fill=col + (255,), width=9)
                destello[lid] = (quedan - 1, col)
            else:
                d.line((ax * s, ay * s, bx * s, by * s), fill=(255, 255, 255, 210), width=4)
        for tr in tracks:
            x1, y1, x2, y2 = (v * s for v in tr["bbox"])
            if tr["id"] in contados:
                clase, _ = contados[tr["id"]]
                col = COLOR.get(clase, (220, 220, 220))
                d.rounded_rectangle((x1, y1, x2, y2), radius=4, outline=col + (255,), width=3)
                # Lejos, la etiqueta tapa a los vecinos y ya no se lee.
                if y2 - y1 >= 45:
                    pastilla(d, x1, y1, NOMBRE.get(clase, clase), col, f_etq)
            else:
                d.rounded_rectangle((x1, y1, x2, y2), radius=4, outline=(255, 255, 255, 110), width=2)
        # Encabezado: qué es, dónde y la hora real del video.
        d.rounded_rectangle((ANCHO // 2 - 380, 18, ANCHO // 2 + 380, 112), radius=14,
                            fill=(14, 18, 24, 200))
        cab = "Aforo vehicular automático"
        d.text((ANCHO // 2 - d.textlength(cab, font=f_cab) / 2, 30), cab, font=f_cab,
               fill=(255, 255, 255, 255))
        sub = f"{a.lugar}  ·  {hora:%d-%m-%Y  %H:%M:%S}"
        d.text((ANCHO // 2 - d.textlength(sub, font=f_reloj) / 2, 72), sub, font=f_reloj,
               fill=(190, 200, 210, 255))
        orden = sorted(meta, key=lambda lid: "alej" in meta[lid]["name"])
        for i, lid in enumerate(orden):
            x = 24 if i == 0 else ANCHO - 24 - 380
            panel(d, x, 18, sentidos[lid], "vehículos",
                  conteo[lid], recien[lid], (f_tit, f_sub, f_total, f_fila))
            for k in list(recien[lid]):
                recien[lid][k] = max(0, recien[lid][k] - 1)
        img = Image.alpha_composite(img, capa).convert("RGB")
        ff.stdin.write(np.asarray(img).tobytes())
        n += 1
    ff.stdin.close()
    ff.wait()

    # Lo mismo que guardó la plataforma en ese tramo, para comprobar.
    t0 = inicio + timedelta(seconds=a.desde)
    t1 = inicio + timedelta(seconds=a.desde + a.segundos)
    guardado = conn.execute(
        """SELECT lane_id, count(*) FROM crossings WHERE job_id = ?
           AND timestamp >= ? AND timestamp < ? GROUP BY lane_id""",
        (job["id"], t0.strftime("%Y-%m-%d %H:%M:%S"), t1.strftime("%Y-%m-%d %H:%M:%S"))).fetchall()
    guardado = dict(guardado)
    for lid in meta:
        print(f"{sentidos[lid]:24} clip {sum(conteo[lid].values()):3}  base {guardado.get(lid, 0):3}  "
              + "  ".join(f"{NOMBRE.get(k, k)} {v}" for k, v in conteo[lid].most_common()))
    print(f"Listo: {a.salida}")


if __name__ == "__main__":
    main()
