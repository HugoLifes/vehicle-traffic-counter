"""
Motor de conteo en segundo plano.

Corre YOLO + tracker + N contadores (uno por carril/línea configurada)
de forma continua sobre una fuente de video en vivo, y publica cada
cruce a traffic_db. No escribe video ni imágenes a disco: solo
mantiene el último frame en memoria (para la API de calibración y,
más adelante, la IA visual).
"""

import logging
import threading
import time
from typing import Dict, Optional

import numpy as np

from src.detector import VehicleDetector
from src.tracker import VehicleTracker
from src.counter import BidirectionalCounter
from src.video_processor import open_video_source, read_with_reconnect
from src.storage import traffic_db
from src.engine.lanes import build_lane_counters


class CountingService:
    """Motor de conteo multi-carril para una única fuente de video."""

    def __init__(
        self,
        camera_source,
        model_path: str = 'models/yolov8n.pt',
        confidence_threshold: float = 0.4,
        device: str = 'auto',
        config: Optional[Dict] = None
    ):
        self.camera_source = str(camera_source)
        self.model_path = model_path
        self.confidence_threshold = confidence_threshold
        self.device = device
        self.config = config or {}

        self.detector: Optional[VehicleDetector] = None
        self.tracker: Optional[VehicleTracker] = None
        self.lane_counters: Dict[int, BidirectionalCounter] = {}
        self.lane_meta: Dict[int, Dict] = {}

        self._latest_frame: Optional[np.ndarray] = None
        self._frame_lock = threading.Lock()
        self._lanes_lock = threading.Lock()
        self._reload_lanes_flag = threading.Event()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self.status = "stopped"  # stopped | starting | running | error
        self.last_error: Optional[str] = None
        self.frame_width = 0
        self.frame_height = 0
        self.fps_estimate = 0.0

    # --- Ciclo de vida -------------------------------------------------

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    # --- Acceso externo (API, IA visual) --------------------------------

    def get_latest_frame(self) -> Optional[np.ndarray]:
        with self._frame_lock:
            return None if self._latest_frame is None else self._latest_frame.copy()

    def get_frame_shape(self):
        return self.frame_height, self.frame_width

    def reload_lanes(self):
        """
        Pide al hilo del motor que vuelva a leer los carriles desde la
        base de datos (se llama tras editarlos en la UI de calibración).
        Se aplica en el propio hilo del motor para no tocar los contadores
        desde otro hilo mientras están en uso.
        """
        self._reload_lanes_flag.set()

    # --- Internos --------------------------------------------------------

    def _load_lanes(self):
        # auto_create_default=True: la cámara en vivo arranca sola, sin un
        # humano que calibre primero. Se puede recalibrar en caliente desde
        # la UI (reload_lanes) sin reiniciar el servicio.
        new_counters, new_meta = build_lane_counters(
            self.camera_source, self.frame_height, self.frame_width,
            auto_create_default=True
        )
        with self._lanes_lock:
            self.lane_counters = new_counters
            self.lane_meta = new_meta

    def _run(self):
        self.status = "starting"
        cap = None
        try:
            self.detector = VehicleDetector(
                model_path=self.model_path,
                confidence_threshold=self.confidence_threshold,
                device=self.device,
                config=self.config.get('detector', {})
            )
            self.tracker = VehicleTracker(
                max_age=self.config.get('tracker', {}).get('max_age', 30),
                min_hits=self.config.get('tracker', {}).get('min_hits', 3),
                iou_threshold=self.config.get('tracker', {}).get('iou_threshold', 0.3),
                config=self.config.get('tracker', {})
            )

            cap, is_live = open_video_source(self.camera_source)
            if not cap.isOpened():
                raise RuntimeError(f"No se pudo abrir la fuente de video: {self.camera_source}")

            self.frame_width = int(cap.get(3)) or 640
            self.frame_height = int(cap.get(4)) or 480
            self._load_lanes()

            self.status = "running"
            frame_times = []

            while not self._stop_event.is_set():
                if self._reload_lanes_flag.is_set():
                    self._reload_lanes_flag.clear()
                    self._load_lanes()

                if is_live:
                    ret, frame, cap = read_with_reconnect(cap, self.camera_source, is_live)
                else:
                    ret, frame = cap.read()

                if not ret:
                    if is_live:
                        logging.error("Fuente en vivo perdida definitivamente")
                        self.status = "error"
                        self.last_error = "Fuente de video desconectada"
                    break

                t0 = time.time()

                detections, _ = self.detector.detect(frame)
                tracks = self.tracker.update(detections)

                with self._lanes_lock:
                    counters = list(self.lane_counters.items())

                for lane_id, counter in counters:
                    crossings = counter.update(tracks)
                    for crossing in crossings['in'] + crossings['out']:
                        track = next(
                            (t for t in tracks if t['id'] == crossing['track_id']),
                            None
                        )
                        # Alto de la caja en píxeles: la medida de si el
                        # detector tiene con qué trabajar en este material.
                        alto_caja = (
                            int(track['bbox'][3] - track['bbox'][1]) if track else None
                        )
                        traffic_db.record_crossing(
                            lane_id=lane_id,
                            track_id=crossing['track_id'],
                            direction=crossing['direction'],
                            vehicle_type=crossing['vehicle_type'],
                            confidence=track['confidence'] if track else None,
                            bbox_height=alto_caja
                        )

                with self._frame_lock:
                    self._latest_frame = frame

                frame_times.append(time.time() - t0)
                if len(frame_times) > 30:
                    frame_times.pop(0)
                avg = sum(frame_times) / len(frame_times)
                self.fps_estimate = 1.0 / avg if avg > 0 else 0.0

            if self.status != "error":
                self.status = "stopped"

        except Exception as e:
            logging.exception("Error en el motor de conteo")
            self.status = "error"
            self.last_error = str(e)
        finally:
            if cap is not None:
                cap.release()


# Instancia única del motor para toda la app (se crea en api/app.py al arrancar)
_service: Optional[CountingService] = None


def get_service() -> Optional[CountingService]:
    return _service


def set_service(service: CountingService):
    global _service
    _service = service
