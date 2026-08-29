"""
Procesador de videos subidos por el usuario (modo por lote, distinto
del motor en vivo). Corre en su propio hilo y procesa la cola de
forma SECUENCIAL — un video a la vez — para no competir por GPU/CPU
con la cámara en vivo ni entre sí en un Jetson.

Produce cruces estructurados en la tabla `crossings`, y además guarda
una copia anotada del video (cajas, IDs, línea de conteo por carril)
para que el usuario pueda ver qué detectó la IA — el archivo original
ya lo subió él mismo, esto no es "grabar" una cámara en vivo, es dejar
ver el resultado de procesar algo que ya era suyo.
"""

import logging
import queue
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import cv2
import imageio_ffmpeg

from src.detector import VehicleDetector
from src.tracker import VehicleTracker
from src.storage import traffic_db
from src.engine.lanes import build_lane_counters
from src.visualizer import Visualizer


def _transcode_to_h264(raw_path: Path, final_path: Path):
    """
    cv2.VideoWriter con el códec 'mp4v' escribe un archivo .mp4 válido,
    pero casi ningún navegador sabe decodificarlo en un <video> (Chrome
    lo rechaza con DEMUXER_ERROR_NO_SUPPORTED_STREAMS — confirmado
    probándolo). H.264 sí lo reproduce cualquier navegador, así que se
    transcodea con el ffmpeg que ya trae imageio_ffmpeg. `+faststart`
    mueve los metadatos al inicio del archivo para que el navegador
    pueda empezar a reproducir sin descargarlo completo.
    """
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg_exe, "-y", "-i", str(raw_path),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(final_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg falló transcodificando a H.264: {result.stderr[-500:]}")

# Paleta de colores por carril (BGR) — misma paleta hexadecimal que
# usa calibrar.js, para que el color de una línea signifique lo mismo
# en la UI de calibración y en el video anotado.
LANE_COLORS_BGR = [
    (112, 84, 255),   # #ff5470
    (255, 212, 45),   # #2dd4ff
    (63, 210, 255),   # #ffd23f
    (107, 255, 124),  # #7cff6b
    (255, 125, 199),  # #c77dff
    (69, 159, 255),   # #ff9f45
]

OUTPUT_DIR = Path("data/uploads/processed")


class VideoJobProcessor:
    def __init__(
        self,
        model_path: str = 'models/yolov8n.pt',
        confidence_threshold: float = 0.4,
        device: str = 'auto',
        config: Optional[dict] = None
    ):
        self.model_path = model_path
        self.confidence_threshold = confidence_threshold
        self.device = device
        self.config = config or {}

        # Último cuadro anotado del video que se está procesando ahora
        # mismo, para poder mirar en vivo lo que la IA está detectando en
        # vez de esperar a que termine todo el archivo.
        self._live_frame = None
        self._live_job_id = None
        self._live_lock = threading.Lock()

        self._queue = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._detector: Optional[VehicleDetector] = None

    # --- Ciclo de vida ---------------------------------------------

    def start(self):
        # Recuperar trabajos que quedaron a medias (ej. si el servicio
        # se reinició mientras procesaba uno)
        for job in traffic_db.get_queued_video_jobs():
            if job['status'] == 'processing':
                traffic_db.update_video_job(job['id'], status='queued', processed_frames=0)
            self._queue.put(job['id'])

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        self._queue.put(None)
        if self._thread:
            self._thread.join(timeout=5)

    def get_live_frame(self):
        """Último cuadro anotado del video en proceso, o None si no hay
        ninguno corriendo. Devuelve (frame, job_id)."""
        with self._live_lock:
            if self._live_frame is None:
                return None, None
            return self._live_frame.copy(), self._live_job_id

    def enqueue(self, job_id: int):
        self._queue.put(job_id)

    # --- Internos --------------------------------------------------

    def _get_detector(self) -> VehicleDetector:
        # Un único modelo cargado, reusado entre videos de la cola
        if self._detector is None:
            self._detector = VehicleDetector(
                model_path=self.model_path,
                confidence_threshold=self.confidence_threshold,
                device=self.device,
                config=self.config.get('detector', {})
            )
        return self._detector

    def _run(self):
        while not self._stop_event.is_set():
            try:
                job_id = self._queue.get(timeout=1)
            except queue.Empty:
                continue
            if job_id is None:
                continue
            self._process_job(job_id)

    def _process_job(self, job_id: int):
        job = traffic_db.get_video_job(job_id)
        if job is None or job['status'] == 'done':
            return

        # Un video puede reprocesarse tras recalibrar los carriles. Si no se
        # borran sus cruces anteriores, los nuevos se SUMAN a los viejos y el
        # aforo sale al doble.
        borrados = traffic_db.delete_crossings_for_job(job_id)
        if borrados:
            logging.info(f"Reproceso: se descartaron {borrados} cruces previos del video {job_id}")

        traffic_db.mark_video_job_started(job_id)
        path = job['stored_path']
        logging.info(f"Procesando video subido: {job['original_name']} ({path})")

        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            traffic_db.update_video_job(
                job_id, status='error',
                error='No se pudo abrir el archivo (formato no soportado o corrupto)'
            )
            return

        writer = None
        try:
            detector = self._get_detector()
            tracker = VehicleTracker(
                max_age=self.config.get('tracker', {}).get('max_age', 30),
                min_hits=self.config.get('tracker', {}).get('min_hits', 3),
                iou_threshold=self.config.get('tracker', {}).get('iou_threshold', 0.3),
                config=self.config.get('tracker', {})
            )

            frame_width = int(cap.get(3)) or 640
            frame_height = int(cap.get(4)) or 480
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or None
            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0

            source_label = job.get('source_label') or 'sin-nombre'
            # Sin auto_create_default: los carriles ya los definió el usuario
            # antes de mandar a contar (ver routes_projects.start_counting).
            lane_counters, lane_meta = build_lane_counters(
                source_label, frame_height, frame_width,
                project_id=job.get('project_id')
            )
            if not lane_counters:
                raise RuntimeError(
                    "El proyecto no tiene carriles definidos — calibra las líneas "
                    "de conteo antes de procesar este video."
                )

            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            # cv2.VideoWriter con mp4v SIEMPRE funciona para escribir, pero
            # casi ningún navegador puede reproducir ese códec en un <video>
            # (probado: Chrome lo rechaza con DEMUXER_ERROR_NO_SUPPORTED_
            # STREAMS). Se escribe a un archivo intermedio y se transcodea a
            # H.264 con ffmpeg al terminar — eso sí lo reproduce cualquier
            # navegador.
            raw_path = OUTPUT_DIR / f"{job_id}_raw.mp4"
            final_path = OUTPUT_DIR / f"{job_id}_annotated.mp4"
            writer = cv2.VideoWriter(
                str(raw_path),
                cv2.VideoWriter_fourcc(*'mp4v'),
                fps,
                (frame_width, frame_height)
            )
            visualizer = Visualizer(config=self.config.get('visualizer', {}))

            traffic_db.update_video_job(job_id, total_frames=total_frames, fps=fps)

            video_start_time = None
            if job.get('video_start_time'):
                video_start_time = datetime.fromisoformat(job['video_start_time'])

            frame_count = 0
            last_progress_update = time.time()

            while not self._stop_event.is_set():
                ret, frame = cap.read()
                if not ret:
                    break

                detections, _ = detector.detect(frame)
                tracks = tracker.update(detections)

                # Hora real de este frame dentro del video (no la hora en
                # que se está procesando el archivo) — es lo que permite
                # que el reporte por intervalos (8:00-8:15, 8:15-8:30...)
                # salga correcto sin importar cuándo se subió/procesó.
                crossing_timestamp = None
                if video_start_time is not None:
                    crossing_timestamp = (
                        video_start_time + timedelta(seconds=frame_count / fps)
                    ).strftime("%Y-%m-%d %H:%M:%S")

                annotated = visualizer.draw_tracks(frame, tracks)

                stats_y = 30
                for idx, (lane_id, counter) in enumerate(lane_counters.items()):
                    crossings = counter.update(tracks)
                    for crossing in crossings['in'] + crossings['out']:
                        confidence = next(
                            (t['confidence'] for t in tracks if t['id'] == crossing['track_id']),
                            None
                        )
                        traffic_db.record_crossing(
                            lane_id=lane_id,
                            track_id=crossing['track_id'],
                            direction=crossing['direction'],
                            vehicle_type=crossing['vehicle_type'],
                            confidence=confidence,
                            timestamp=crossing_timestamp,
                            job_id=job_id
                        )

                    color = LANE_COLORS_BGR[idx % len(LANE_COLORS_BGR)]
                    line_coords = lane_meta[lane_id]["points"]
                    annotated = visualizer.draw_counting_line(annotated, line_coords, line_color=color)

                    lane_counts = counter.get_counts()
                    lane_name = lane_meta[lane_id]["name"]
                    annotated = visualizer.draw_statistics(
                        annotated,
                        lane_counts,
                        position=(20, stats_y + 30),
                        background_alpha=0.6,
                        title=lane_name
                    )
                    stats_y += 30 * 5 + 15  # misma fórmula de altura que draw_statistics

                writer.write(annotated)

                # Publicar el cuadro para el visor en vivo. Solo se guarda
                # en memoria (una referencia), no se escribe a disco: el
                # costo por cuadro es despreciable frente a la inferencia.
                with self._live_lock:
                    self._live_frame = annotated
                    self._live_job_id = job_id
                frame_count += 1
                if time.time() - last_progress_update > 1.0:
                    traffic_db.update_video_job(job_id, processed_frames=frame_count)
                    last_progress_update = time.time()

            traffic_db.update_video_job(job_id, processed_frames=frame_count)

            writer.release()
            writer = None  # ya liberado, que el finally no lo vuelva a tocar

            if self._stop_event.is_set():
                # Se detuvo el servicio (ej. reinicio), no es un error
                # del video — vuelve a la cola para reintentarse.
                traffic_db.update_video_job(job_id, status='queued')
                raw_path.unlink(missing_ok=True)
            else:
                _transcode_to_h264(raw_path, final_path)
                raw_path.unlink(missing_ok=True)
                # El total declarado en la metadata del contenedor no siempre
                # coincide con los cuadros realmente decodificables (en los
                # .mkv de prueba decía 9001 y solo había 6059). Al terminar se
                # corrige con el conteo real, si no la barra de progreso se
                # queda clavada y parece que el proceso quedó a medias.
                traffic_db.update_video_job(
                    job_id, output_video_path=str(final_path), total_frames=frame_count
                )
                traffic_db.mark_video_job_finished(job_id)
                logging.info(f"Video procesado: {job['original_name']} ({frame_count} frames)")

            # Ya no hay nada corriendo: limpiar el cuadro en vivo para que el
            # visor no siga mostrando el último cuadro de un video terminado.
            with self._live_lock:
                self._live_frame = None
                self._live_job_id = None

        except Exception as e:
            logging.exception(f"Error procesando video {job['original_name']}")
            traffic_db.update_video_job(job_id, status='error', error=str(e))
            with self._live_lock:
                self._live_frame = None
                self._live_job_id = None
        finally:
            cap.release()
            if writer is not None:
                writer.release()


_processor: Optional[VideoJobProcessor] = None


def get_processor() -> Optional[VideoJobProcessor]:
    return _processor


def set_processor(processor: VideoJobProcessor):
    global _processor
    _processor = processor
