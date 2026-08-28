"""
Módulo de procesamiento de video
Orquesta detector, tracker, counter y visualizer
"""

import cv2
import numpy as np
import logging
import time
from typing import List, Dict, Optional, Tuple, Union


def open_video_source(source: Union[str, int]) -> Tuple[cv2.VideoCapture, bool]:
    """
    Abrir una fuente de video: archivo, índice de webcam o stream de
    cámara IP (RTSP/HTTP).

    Args:
        source: Ruta a archivo de video, índice de webcam (ej. "0"),
            o URL de stream (rtsp://..., http://...)

    Returns:
        cap: cv2.VideoCapture abierto
        is_live: True si es una fuente en vivo (webcam o stream de red),
            False si es un archivo de video con longitud conocida
    """
    is_live = False

    # Índice de webcam: "0", "1", etc.
    if isinstance(source, str) and source.isdigit():
        cap = cv2.VideoCapture(int(source))
        is_live = True
    elif isinstance(source, int):
        cap = cv2.VideoCapture(source)
        is_live = True
    elif isinstance(source, str) and source.lower().startswith(
        ('rtsp://', 'rtsp2://', 'http://', 'https://')
    ):
        # FFMPEG maneja mejor RTSP/HTTP que el backend por defecto
        cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
        # Buffer mínimo para reducir latencia en streams en vivo
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        is_live = True
    else:
        # Archivo de video local
        cap = cv2.VideoCapture(source)
        is_live = False

    return cap, is_live


def read_with_reconnect(
    cap: cv2.VideoCapture,
    source: Union[str, int],
    is_live: bool,
    max_retries: int = 10,
    retry_delay: float = 2.0
) -> Tuple[bool, Optional[np.ndarray], cv2.VideoCapture]:
    """
    Leer un frame, reintentando reconexión si es una fuente en vivo
    (cámara IP) que se desconectó momentáneamente.

    Args:
        cap: VideoCapture actual
        source: Fuente original (para reconectar)
        is_live: Si es una fuente en vivo
        max_retries: Intentos de reconexión antes de rendirse
        retry_delay: Segundos de espera entre reintentos

    Returns:
        ret: Si se leyó un frame válido
        frame: Frame leído (o None)
        cap: VideoCapture (puede ser uno nuevo si se reconectó)
    """
    ret, frame = cap.read()

    if ret or not is_live:
        return ret, frame, cap

    # Fuente en vivo desconectada: intentar reconectar
    logging.warning("Stream desconectado, intentando reconectar...")
    cap.release()

    for attempt in range(1, max_retries + 1):
        time.sleep(retry_delay)
        cap, _ = open_video_source(source)
        if cap.isOpened():
            ret, frame = cap.read()
            if ret:
                logging.info(f"Reconectado exitosamente (intento {attempt})")
                return ret, frame, cap
        logging.warning(f"Reintento {attempt}/{max_retries} fallido")

    logging.error("No se pudo reconectar al stream tras varios intentos")
    return False, None, cap


class VideoProcessor:
    """
    Procesador de video que coordina todos los componentes
    
    Pipeline:
    1. Detectar vehículos en frame
    2. Actualizar tracker con detecciones
    3. Actualizar contador con tracks
    4. Visualizar resultados
    """
    
    def __init__(
        self,
        detector,
        tracker,
        counter,
        visualizer,
        skip_frames: int = 0,
        config: Optional[Dict] = None
    ):
        """
        Inicializar procesador de video
        
        Args:
            detector: Instancia de VehicleDetector
            tracker: Instancia de VehicleTracker
            counter: Instancia de BidirectionalCounter
            visualizer: Instancia de Visualizer
            skip_frames: Número de frames a saltar entre detecciones
            config: Configuración adicional
        """
        self.detector = detector
        self.tracker = tracker
        self.counter = counter
        self.visualizer = visualizer
        self.skip_frames = skip_frames
        self.config = config or {}
        
        # Estado interno
        self.frame_count = 0
        self.detection_count = 0
        
        logging.info(
            f"VideoProcessor inicializado (skip_frames={skip_frames})"
        )
    
    def process_frame(
        self,
        frame: np.ndarray,
        frame_number: int
    ) -> Tuple[np.ndarray, Dict]:
        """
        Procesar un frame completo
        
        Args:
            frame: Frame de entrada
            frame_number: Número de frame
            
        Returns:
            processed_frame: Frame procesado con visualizaciones
            frame_data: Datos del frame (detecciones, tracks, cruces)
        """
        self.frame_count += 1
        
        # 1. Detectar vehículos (con skip_frames para optimización)
        if self.frame_count % (self.skip_frames + 1) == 0:
            detections, _ = self.detector.detect(frame)
            self.detection_count += 1
        else:
            detections = []
        
        # 2. Actualizar tracker
        tracks = self.tracker.update(detections)
        
        # 3. Actualizar contador
        crossings = self.counter.update(tracks)
        
        # 4. Obtener datos para visualización
        counts = self.counter.get_counts()
        detailed_counts = self.counter.get_detailed_counts()
        counting_line = self.counter.get_line_coordinates()
        
        # 5. Crear visualización
        processed_frame = self.visualizer.create_visualization(
            frame=frame,
            tracks=tracks,
            counting_line=counting_line,
            counts=counts,
            detailed_counts=detailed_counts,
            frame_number=frame_number
        )
        
        # 6. Preparar datos del frame
        frame_data = {
            'frame_number': frame_number,
            'detections': detections,
            'tracks': tracks,
            'crossings': crossings,
            'counts': counts,
            'detailed_counts': detailed_counts
        }
        
        return processed_frame, frame_data
    
    def get_statistics(self) -> Dict:
        """Obtener estadísticas del procesador"""
        return {
            'frames_processed': self.frame_count,
            'detections_run': self.detection_count,
            'detector_stats': self.detector.get_statistics(),
            'tracker_stats': self.tracker.get_statistics(),
            'counter_stats': self.counter.get_statistics()
        }
