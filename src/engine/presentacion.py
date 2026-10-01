"""
Cómo se ve un aforo sobre el video: cada vehículo con la clase que se
entrega, el conteo de cada sentido desglosado y la hora real.

Es lo que dibujan el visor en vivo, el video anotado de la plataforma y los
clips de presentación (tools/video_presentacion.py): los tres pasan por
`Marcador`, así que se ven igual. Antes el anotado ponía la etiqueta de COCO
("car", "truck") y un recuadro con los totales por línea; servía para revisar
la calibración, pero no enseñaba lo que la empresa recibe: la pickup salía
como "truck" en el video y como automóvil en el Excel.

La clase de cada cruce sale por el mismo camino que `get_interval_counts`:
la regla del alto con la escala de su línea y los clasificadores del perfil
solo donde la calzada da para clases finas. La escala se toma de los cruces
ya guardados del proyecto (horas con confianza suficiente); en un proyecto
nuevo, sin cruces, se aprende de los primeros 30 automóviles del video y
mientras tanto la clase es provisional (la de COCO, sin separar pesados).
Lo que la empresa recibe se sigue calculando al leer, con la revisión del
modelo de visión si la hay: lo dibujado es la lectura en vivo.

Todas las medidas están pensadas sobre 1920 de ancho y se escalan al tamaño
de salida, para que el anotado a 1280 y el clip a 1920 sean el mismo dibujo.
"""
import os
import statistics
from collections import Counter
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from src.engine.clasificacion import (CONFIANZA_MINIMA, clasificar, nivel_de_calzada,
                                      perfil_de_calzada)
from src.engine.clasificador_pesados import clase_final, subtipo_final

# Orden y nombre de las clases tal como las entrega el Excel.
CLASES_FINAS = [
    ("AUTO", "Automóvil", (79, 195, 247)),
    ("CAMIONETA", "Camioneta / SUV", (129, 199, 132)),
    ("PICKUP", "Pickup", (255, 213, 79)),
    ("MOTO", "Motocicleta", (240, 98, 146)),
    ("B", "Autobús", (255, 138, 101)),
    ("C", "Camión", (186, 104, 200)),
    ("T-S", "Tractocamión", (229, 115, 115)),
    ("TRACTOR", "Tractor sin caja", (188, 170, 164)),
]
# Donde el vehículo es chico (cámara lejana) solo se separa liviano de pesado.
CLASES_GRUESAS = [
    ("A", "Liviano", (79, 195, 247)),
    ("PESADO", "Pesado", (229, 115, 115)),
]
NOMBRE = {k: n for k, n, _ in CLASES_FINAS + CLASES_GRUESAS}
COLOR = {k: c for k, _, c in CLASES_FINAS + CLASES_GRUESAS}
NOMBRE["SIN_RESOLVER"] = "Vehículo"
COLOR["SIN_RESOLVER"] = (220, 220, 220)
# A sin subtipo (de noche, o el clasificador dudó) en una calzada fina.
A_FINA = ("Otro liviano", (220, 220, 220))

ANCHO_BASE = 1920
# Por debajo de este alto (a 1920) la etiqueta tapa a los vecinos y ya no se
# lee: el vehículo lejano queda solo con su caja de color.
ALTO_ETIQUETA = 45
# Provisional mientras no hay escala: lo que COCO no deja en duda.
PROVISIONAL = {"car": "A", "motorcycle": "MOTO", "bus": "B"}

_fuentes: Dict[Tuple[int, bool], ImageFont.FreeTypeFont] = {}


def fuente(tam: int, negrita: bool = False):
    clave = (tam, negrita)
    if clave not in _fuentes:
        # DejaVu es la del contenedor del Jetson; Arial, la de una PC con Windows.
        candidatas = (
            ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf")
            if negrita else
            ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf"))
        f = None
        for ruta in candidatas:
            if os.path.exists(ruta):
                f = ImageFont.truetype(ruta, tam)
                break
        _fuentes[clave] = f or ImageFont.load_default(size=tam)
    return _fuentes[clave]


def escala_por_carril(project_id: int) -> Tuple[Dict, Dict]:
    """(umbral de pesado, perfil fino) de cada línea del proyecto, con sus
    cruces guardados en las horas que se pueden medir (confianza media del
    proyecto ≥ CONFIANZA_MINIMA, como en get_interval_counts)."""
    from src.storage import traffic_db
    filas = traffic_db.get_connection().execute(
        """SELECT cr.lane_id, cr.vehicle_type, cr.bbox_height, cr.bbox_width,
                  cr.confidence, substr(cr.timestamp, 12, 2)
           FROM crossings cr JOIN lane_configs l ON l.id = cr.lane_id
           WHERE l.project_id = ?""", (project_id,)).fetchall()
    confianzas: Dict[str, List[float]] = {}
    for f in filas:
        if f[4] is not None:
            confianzas.setdefault(f[5], []).append(f[4])
    medibles = {h for h, cs in confianzas.items() if statistics.fmean(cs) >= CONFIANZA_MINIMA}
    umbral, perfil = {}, {}
    for lane in {f[0] for f in filas}:
        propios = [f for f in filas if f[0] == lane and f[5] in medibles]
        umbral[lane] = nivel_de_calzada(f[2] for f in propios if f[1] == "car")[1]
        perfil[lane] = perfil_de_calzada([
            {"vehicle_type": f[1], "bbox_height": f[2], "bbox_width": f[3]} for f in propios])
    return umbral, perfil


def nombre_sentido(nombre_linea: str) -> str:
    """El título del marcador: el nombre de la línea sin "Carril"."""
    n = (nombre_linea or "").strip()
    if n.lower().startswith("carril "):
        n = n[7:]
    n = n.replace("camara", "cámara").replace("alejandose", "alejándose")
    return n[:1].upper() + n[1:]


class Marcador:
    """Estado de lo que se dibuja: qué rastro se contó y con qué clase, el
    conteo de cada sentido y los destellos. Se alimenta en CADA cuadro aunque
    solo se dibuje de vez en cuando (el visor en vivo dibuja uno por
    segundo): el conteo no puede depender de cuándo se mira."""

    def __init__(self, meta: Dict[int, Dict], fps: float, umbral: Dict, perfil: Dict,
                 horas_subtipo=(7, 19), inicio: Optional[datetime] = None,
                 lugar: str = "", tapar=None):
        self.meta = meta
        self.fps = fps or 20.0
        self.umbral = dict(umbral)
        self.perfil = dict(perfil)
        self.horas_subtipo = tuple(horas_subtipo)
        self.inicio = inicio
        self.lugar = lugar
        self.tapar = tapar
        self.titulos = {lid: nombre_sentido(m.get("name", "")) for lid, m in meta.items()}
        self.conteo = {lid: Counter() for lid in meta}
        self.recien = {lid: Counter() for lid in meta}
        self.destello = {lid: (0, None) for lid in meta}
        self.contados: Dict[int, Tuple[int, str]] = {}   # rastro -> (línea, clase)
        self._muestras = {lid: [] for lid in meta}

    # --- Clase y conteo ---------------------------------------------------

    def _fino(self, lane_id) -> bool:
        return bool((self.perfil.get(lane_id) or {}).get("fino"))

    def _aprender(self, lane_id, tipo, alto, ancho):
        """Sin cruces guardados, la escala sale de los automóviles de este
        mismo video en cuanto haya los 30 que pide nivel_de_calzada."""
        if self.umbral.get(lane_id) is not None:
            return
        m = self._muestras.setdefault(lane_id, [])
        m.append({"vehicle_type": tipo, "bbox_height": alto, "bbox_width": ancho})
        autos = [x["bbox_height"] for x in m if x["vehicle_type"] == "car"]
        if len(autos) >= 30:
            self.umbral[lane_id] = nivel_de_calzada(autos)[1]
            self.perfil[lane_id] = perfil_de_calzada(m)

    def clase(self, lane_id, track, cuadro: int, clase_modelo=None, prob_modelo=None,
              subtipo=None, prob_subtipo=None) -> str:
        x1, y1, x2, y2 = track["bbox"]
        alto, ancho, tipo = y2 - y1, x2 - x1, track.get("class_name", "")
        self._aprender(lane_id, tipo, alto, ancho)
        umbral = self.umbral.get(lane_id)
        if umbral is None:
            return PROVISIONAL.get(tipo, "SIN_RESOLVER")
        fino = self._fino(lane_id)
        clase = clasificar(tipo, alto, umbral, ancho=ancho, perfil=self.perfil.get(lane_id))
        clase = clase_final(clase, clase_modelo, prob_modelo, fino)
        if clase == "A":
            hora = self.hora(cuadro)
            # Sin hora del video no se sabe si es de día: se deja decidir al
            # clasificador.
            h = hora.hour if hora else self.horas_subtipo[0]
            sub = subtipo_final(subtipo, prob_subtipo, h, self.horas_subtipo, fino)
            if sub != "SIN_SUBTIPO":
                clase = sub
        return clase

    def registrar(self, lane_id, track_id, clase: str):
        self.contados[track_id] = (lane_id, clase)
        self.conteo[lane_id][clase] += 1
        self.recien[lane_id][clase] = int(self.fps * 0.8)
        self.destello[lane_id] = (int(self.fps * 0.4), self._color(lane_id, clase))

    def avanzar(self):
        """Un cuadro menos para los resaltados. Una vez por cuadro."""
        for lid in self.meta:
            for k in list(self.recien[lid]):
                self.recien[lid][k] = max(0, self.recien[lid][k] - 1)
            quedan, col = self.destello[lid]
            if quedan:
                self.destello[lid] = (quedan - 1, col)

    def hora(self, cuadro: int) -> Optional[datetime]:
        if self.inicio is None:
            return None
        return self.inicio + timedelta(seconds=cuadro / self.fps)

    def _nombre(self, lane_id, clase):
        if clase == "A" and self._fino(lane_id):
            return A_FINA[0]
        return NOMBRE.get(clase, clase)

    def _color(self, lane_id, clase):
        if clase == "A" and self._fino(lane_id):
            return A_FINA[1]
        return COLOR.get(clase, (220, 220, 220))

    def _filas(self, lane_id):
        base = CLASES_FINAS if self._fino(lane_id) else CLASES_GRUESAS
        filas = [(k, self._nombre(lane_id, k), self._color(lane_id, k)) for k, _, _ in base]
        claves = {k for k, _, _ in base}
        # Lo que salió fuera de la lista (A sin subtipo, sin escala todavía)
        # se agrega solo si hay algo que contar.
        for k, n in self.conteo[lane_id].items():
            if n and k not in claves:
                filas.append((k, self._nombre(lane_id, k), self._color(lane_id, k)))
        return filas

    # --- Dibujo -----------------------------------------------------------

    def dibujar(self, frame: np.ndarray, tracks: List[Dict], cuadro: int,
                ancho: int, alto: Optional[int] = None) -> np.ndarray:
        """El cuadro de salida (BGR) a `ancho` de ancho, con todo encima. El
        alto se puede fijar para que case con el del VideoWriter: un cuadro de
        otro tamaño se descarta sin error."""
        H, W = frame.shape[:2]
        s = ancho / W
        alto = alto or int(round(H * s)) // 2 * 2
        ancho = ancho // 2 * 2
        k = ancho / ANCHO_BASE
        img_bgr = cv2.resize(frame, (ancho, alto),
                             interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
        if self.tapar:
            # La leyenda de la cámara: en el frontal dice otra fecha y otra
            # hora (ver revisar_reloj.py) y contradice el encabezado.
            x1, y1, x2, y2 = (int(round(v * s)) for v in self.tapar)
            x1, y1 = max(0, x1), max(0, y1)
            if x2 > x1 and y2 > y1:
                img_bgr[y1:y2, x1:x2] = cv2.GaussianBlur(img_bgr[y1:y2, x1:x2], (0, 0), 14 * k)
        img = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)).convert("RGBA")
        capa = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(capa)

        # Líneas de conteo; destellan del color de la clase al contar.
        for lid, m in self.meta.items():
            pts = m.get("points") or []
            if len(pts) < 2:
                continue
            (ax, ay), (bx, by) = pts[0], pts[-1]
            quedan, col = self.destello[lid]
            if quedan:
                d.line((ax * s, ay * s, bx * s, by * s), fill=col + (255,), width=max(2, int(9 * k)))
            else:
                d.line((ax * s, ay * s, bx * s, by * s), fill=(255, 255, 255, 210),
                       width=max(1, int(4 * k)))

        f_etq = fuente(max(9, int(20 * k)), True)
        for tr in tracks:
            x1, y1, x2, y2 = (v * s for v in tr["bbox"])
            contado = self.contados.get(tr["id"])
            if contado is None:
                d.rounded_rectangle((x1, y1, x2, y2), radius=max(1, int(4 * k)),
                                    outline=(255, 255, 255, 110), width=max(1, int(2 * k)))
                continue
            lane, clase = contado
            col = self._color(lane, clase)
            d.rounded_rectangle((x1, y1, x2, y2), radius=max(1, int(4 * k)),
                                outline=col + (255,), width=max(1, int(3 * k)))
            if y2 - y1 >= ALTO_ETIQUETA * k:
                self._pastilla(d, x1, y1, self._nombre(lane, clase), col, f_etq, k)

        self._encabezado(d, ancho, k, self.hora(cuadro))
        # Un marcador por sentido: a la izquierda las líneas de la izquierda.
        orden = sorted(self.meta, key=lambda lid: sum(p[0] for p in (self.meta[lid].get("points") or [[0, 0]]))
                       / max(1, len(self.meta[lid].get("points") or [1])))
        mitad = (len(orden) + 1) // 2
        for col_i, grupo in enumerate((orden[:mitad], orden[mitad:])):
            y = 18 * k
            for lid in grupo:
                x = 24 * k if col_i == 0 else ancho - (24 + 380) * k
                y += self._panel(d, x, y, lid, k) + 14 * k
        img = Image.alpha_composite(img, capa).convert("RGB")
        return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)

    @staticmethod
    def _pastilla(d, x, y, texto, color, f, k):
        l, t, r, b = d.textbbox((0, 0), texto, font=f)
        w, h = r - l + 14 * k, b - t + 8 * k
        y = max(0, y - h - 3 * k)
        d.rounded_rectangle((x, y, x + w, y + h), radius=max(1, int(5 * k)), fill=color + (235,))
        d.text((x + 7 * k, y + 4 * k - t), texto, font=f, fill=(20, 20, 24, 255))

    def _encabezado(self, d, ancho, k, hora):
        f_cab, f_sub = fuente(max(10, int(30 * k)), True), fuente(max(9, int(24 * k)))
        cab = "Aforo vehicular automático"
        partes = [p for p in (self.lugar, f"{hora:%d-%m-%Y  %H:%M:%S}" if hora else "") if p]
        sub = "  ·  ".join(partes)
        w = max(760 * k, d.textlength(sub, font=f_sub) + 40 * k) if sub else 760 * k
        h = (94 if sub else 58) * k
        d.rounded_rectangle((ancho / 2 - w / 2, 18 * k, ancho / 2 + w / 2, 18 * k + h),
                            radius=max(1, int(14 * k)), fill=(14, 18, 24, 200))
        d.text((ancho / 2 - d.textlength(cab, font=f_cab) / 2, 30 * k), cab, font=f_cab,
               fill=(255, 255, 255, 255))
        if sub:
            d.text((ancho / 2 - d.textlength(sub, font=f_sub) / 2, 72 * k), sub, font=f_sub,
                   fill=(190, 200, 210, 255))

    def _panel(self, d, x, y, lane_id, k) -> float:
        """Marcador de un sentido; devuelve su alto."""
        f_tit, f_sub = fuente(max(9, int(24 * k)), True), fuente(max(8, int(18 * k)))
        f_total, f_fila = fuente(max(14, int(54 * k)), True), fuente(max(8, int(20 * k)))
        filas = self._filas(lane_id)
        w, h = 380 * k, (132 + 29 * len(filas)) * k
        d.rounded_rectangle((x, y, x + w, y + h), radius=max(1, int(14 * k)), fill=(14, 18, 24, 190))
        d.text((x + 20 * k, y + 14 * k), self.titulos[lane_id], font=f_tit, fill=(255, 255, 255, 255))
        conteo = self.conteo[lane_id]
        total = str(sum(conteo.values()))
        d.text((x + 20 * k, y + 44 * k), total, font=f_total, fill=(255, 255, 255, 255))
        d.text((x + 24 * k + d.textlength(total, font=f_total), y + 74 * k), "vehículos",
               font=f_sub, fill=(170, 180, 190, 255))
        yy = y + 118 * k
        for clave, nombre, color in filas:
            n = conteo.get(clave, 0)
            brillo = 255 if n else 110
            if self.recien[lane_id].get(clave, 0) > 0:
                d.rounded_rectangle((x + 10 * k, yy - 3 * k, x + w - 10 * k, yy + 25 * k),
                                    radius=max(1, int(6 * k)), fill=color + (80,))
            d.rounded_rectangle((x + 20 * k, yy + 3 * k, x + 36 * k, yy + 19 * k),
                                radius=max(1, int(4 * k)), fill=color + ((255,) if n else (90,)))
            d.text((x + 48 * k, yy), nombre, font=f_fila, fill=(brillo, brillo, brillo, 255))
            txt = str(n)
            d.text((x + w - 22 * k - d.textlength(txt, font=f_fila), yy), txt, font=f_fila,
                   fill=(brillo, brillo, brillo, 255))
            yy += 29 * k
        return h


def lugar_del_proyecto(proyecto: Dict) -> str:
    """Lo que va junto a la hora en el encabezado: la dirección del proyecto,
    o su nombre si no la tiene."""
    return (proyecto.get("address") or proyecto.get("name") or "").strip()


def generar_video(job: Dict, detector, config: Dict, salida: str, ancho: int = 1920,
                  desde: float = 0.0, segundos: Optional[float] = None,
                  clasificadores: Tuple = (None, None), lugar: Optional[str] = None,
                  detener=None, progreso=None) -> Dict[int, Counter]:
    """Video con el aforo dibujado (H.264, listo para el navegador), SIN
    escribir en la base: detecta, rastrea y cuenta por el mismo camino que
    VideoJobProcessor._process_job y solo dibuja. Sirve para darle su video
    con detecciones a un video ya contado sin recontarlo —recontar borra sus
    cruces y con ellos la revisión de los pesados— y para los clips de
    presentación.

    Cuenta desde unos segundos antes de `desde` para que el rastreador llegue
    siguiendo a los vehículos; lo que cruza en ese previo no entra al
    marcador. Devuelve el conteo por línea y clase, para compararlo con lo
    guardado.
    """
    import subprocess
    import imageio_ffmpeg
    from src.detector import VehicleDetector
    from src.engine import perfil_deteccion
    from src.engine.lanes import build_lane_counters
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
    if not contadores:
        cap.release()
        raise RuntimeError("El proyecto no tiene líneas de conteo que dibujar")
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
    pesados, livianos = clasificadores
    umbral, perfil_carril = escala_por_carril(job.get("project_id"))
    inicio = (datetime.fromisoformat(job["video_start_time"])
              if job.get("video_start_time") else None)
    marcador = Marcador(meta, fps, umbral, perfil_carril,
                        horas_subtipo=perfil.get("horas_subtipo", (7, 19)), inicio=inicio,
                        lugar=lugar if lugar is not None else lugar_del_proyecto(proyecto),
                        tapar=perfil.get("tapar_leyenda"))

    # Para mirarlo o presentarlo: a 1920 si la cámara da para ello y a 1280
    # si no (desde un video de 640, a la mitad el marcador no se lee).
    if not ancho:
        ancho = 1920 if W >= 1920 else 1280
    alto = int(round(H * ancho / W)) // 2 * 2
    ancho = ancho // 2 * 2
    ff = subprocess.Popen(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{ancho}x{alto}", "-r", f"{fps}",
         "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", salida],
        stdin=subprocess.PIPE)
    quitar_nacidos = bool(perfil.get("quitar_nacidos_en_pesado"))
    vistos_ids, nacidos = set(), set()
    cuadro0 = int(max(0.0, desde - 3.0) * fps)
    cuadro_ini = int(desde * fps)
    cuadro_fin = int((desde + segundos) * fps) if segundos else None
    n = 0
    try:
        while cuadro_fin is None or n < cuadro_fin:
            if detener is not None and detener():
                raise InterruptedError("Se detuvo el servicio")
            ok, frame = cap.read()
            if not ok:
                break
            if n < cuadro0:
                n += 1
                continue
            dets = detector.detect(frame)[0]
            dets = perfil_deteccion.filtrar_por_clase(dets, perfil, general)
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
                vistos = [tr for tr in tracks
                          if not (zona and zonas) or zone_for_bbox(zonas, tr["bbox"]) == zona]
                cruces = cont.update(vistos)
                for c in cruces["in"] + cruces["out"]:
                    tr = next((x for x in vistos if x["id"] == c["track_id"]), None)
                    if tr is None or n < cuadro_ini or c["track_id"] in nacidos:
                        continue
                    cm = pm = sub = ps = None
                    if pesados is not None:
                        r = pesados.clasificar(frame, tr["bbox"])
                        if r:
                            cm, pm = r
                    if livianos is not None:
                        r = livianos.clasificar(frame, tr["bbox"])
                        if r:
                            sub, ps = r
                    marcador.registrar(lid, tr["id"], marcador.clase(lid, tr, n, cm, pm, sub, ps))
            if n >= cuadro_ini:
                ff.stdin.write(marcador.dibujar(frame, tracks, n, ancho, alto).tobytes())
                marcador.avanzar()
            n += 1
            if progreso is not None and n % 20 == 0:
                fin = cuadro_fin or total
                if fin:
                    progreso(min(1.0, max(0.0, (n - cuadro_ini) / max(1, fin - cuadro_ini))))
    finally:
        cap.release()
        ff.stdin.close()
        ff.wait()
    return marcador.conteo
