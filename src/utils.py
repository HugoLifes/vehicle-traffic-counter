"""
Utilidades y funciones auxiliares
"""

import logging
import sys
import torch
import cv2
import numpy as np
from typing import Dict, Optional
from pathlib import Path


def setup_logger(
    log_file: Optional[str] = None,
    level: int = logging.INFO
) -> logging.Logger:
    """
    Configurar sistema de logging
    
    Args:
        log_file: Ruta al archivo de log (opcional)
        level: Nivel de logging
        
    Returns:
        Logger configurado
    """
    # Formato del log
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'
    
    # Configurar handler de consola
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_formatter = logging.Formatter(log_format, date_format)
    console_handler.setFormatter(console_formatter)
    
    # Configurar logger raíz
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(console_handler)
    
    # Agregar handler de archivo si se especifica
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(level)
        file_formatter = logging.Formatter(log_format, date_format)
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
    
    return root_logger


def check_cuda() -> bool:
    """Verificar si CUDA está disponible"""
    return torch.cuda.is_available()


def get_device_info() -> Dict:
    """
    Obtener información del dispositivo de procesamiento
    
    Returns:
        Diccionario con información del dispositivo
    """
    info = {
        'cuda_available': torch.cuda.is_available(),
        'cuda_version': torch.version.cuda if torch.cuda.is_available() else None,
        'pytorch_version': torch.__version__,
        'device_count': torch.cuda.device_count() if torch.cuda.is_available() else 0,
    }
    
    if info['cuda_available']:
        info['gpu_name'] = torch.cuda.get_device_name(0)
        info['gpu_memory'] = f"{torch.cuda.get_device_properties(0).total_memory / 1e9:.2f} GB"
        info['name'] = f"CUDA ({info['gpu_name']})"
    else:
        info['gpu_name'] = None
        info['gpu_memory'] = None
        info['name'] = "CPU"
    
    return info


def calculate_fps(
    start_time: float,
    end_time: float,
    frame_count: int
) -> float:
    """
    Calcular FPS
    
    Args:
        start_time: Tiempo de inicio
        end_time: Tiempo de fin
        frame_count: Número de frames procesados
        
    Returns:
        FPS
    """
    elapsed_time = end_time - start_time
    if elapsed_time > 0:
        return frame_count / elapsed_time
    return 0.0


def resize_frame(
    frame: np.ndarray,
    target_width: Optional[int] = None,
    target_height: Optional[int] = None,
    maintain_aspect: bool = True
) -> np.ndarray:
    """
    Redimensionar frame
    
    Args:
        frame: Frame de entrada
        target_width: Ancho objetivo
        target_height: Alto objetivo
        maintain_aspect: Mantener relación de aspecto
        
    Returns:
        Frame redimensionado
    """
    height, width = frame.shape[:2]
    
    if target_width is None and target_height is None:
        return frame
    
    if maintain_aspect:
        if target_width is not None:
            scale = target_width / width
            new_width = target_width
            new_height = int(height * scale)
        elif target_height is not None:
            scale = target_height / height
            new_height = target_height
            new_width = int(width * scale)
    else:
        new_width = target_width or width
        new_height = target_height or height
    
    resized_frame = cv2.resize(
        frame,
        (new_width, new_height),
        interpolation=cv2.INTER_LINEAR
    )
    
    return resized_frame


def draw_text_with_background(
    frame: np.ndarray,
    text: str,
    position: tuple,
    font_scale: float = 0.6,
    font_thickness: int = 2,
    text_color: tuple = (255, 255, 255),
    bg_color: tuple = (0, 0, 0),
    padding: int = 5
) -> np.ndarray:
    """
    Dibujar texto con fondo
    
    Args:
        frame: Frame de entrada
        text: Texto a dibujar
        position: Posición (x, y)
        font_scale: Escala de fuente
        font_thickness: Grosor de fuente
        text_color: Color del texto (BGR)
        bg_color: Color del fondo (BGR)
        padding: Padding alrededor del texto
        
    Returns:
        Frame con texto
    """
    x, y = position
    
    # Obtener tamaño del texto
    (text_width, text_height), baseline = cv2.getTextSize(
        text,
        cv2.FONT_HERSHEY_SIMPLEX,
        font_scale,
        font_thickness
    )
    
    # Dibujar fondo
    cv2.rectangle(
        frame,
        (x - padding, y - text_height - padding),
        (x + text_width + padding, y + baseline + padding),
        bg_color,
        -1
    )
    
    # Dibujar texto
    cv2.putText(
        frame,
        text,
        (x, y),
        cv2.FONT_HERSHEY_SIMPLEX,
        font_scale,
        text_color,
        font_thickness
    )
    
    return frame


def create_video_writer(
    output_path: str,
    fps: int,
    frame_size: tuple,
    codec: str = 'mp4v'
) -> cv2.VideoWriter:
    """
    Crear escritor de video
    
    Args:
        output_path: Ruta de salida
        fps: Frames por segundo
        frame_size: Tamaño de frame (width, height)
        codec: Codec de video
        
    Returns:
        VideoWriter
    """
    fourcc = cv2.VideoWriter_fourcc(*codec)
    writer = cv2.VideoWriter(
        output_path,
        fourcc,
        fps,
        frame_size
    )
    
    if not writer.isOpened():
        raise RuntimeError(f"No se pudo crear video writer: {output_path}")
    
    return writer


def get_video_info(video_path: str) -> Dict:
    """
    Obtener información de un video
    
    Args:
        video_path: Ruta al video
        
    Returns:
        Diccionario con información del video
    """
    cap = cv2.VideoCapture(video_path)
    
    if not cap.isOpened():
        raise ValueError(f"No se pudo abrir el video: {video_path}")
    
    info = {
        'width': int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        'height': int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        'fps': int(cap.get(cv2.CAP_PROP_FPS)),
        'frame_count': int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        'codec': int(cap.get(cv2.CAP_PROP_FOURCC)),
        'duration_seconds': None
    }
    
    if info['fps'] > 0:
        info['duration_seconds'] = info['frame_count'] / info['fps']
    
    cap.release()
    
    return info


def ensure_dir(directory: str):
    """Asegurar que un directorio existe"""
    Path(directory).mkdir(parents=True, exist_ok=True)


def format_time(seconds: float) -> str:
    """
    Formatear segundos a formato legible
    
    Args:
        seconds: Tiempo en segundos
        
    Returns:
        String formateado (HH:MM:SS)
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def calculate_distance(
    point1: tuple,
    point2: tuple
) -> float:
    """Calcular distancia euclidiana entre dos puntos"""
    return np.sqrt(
        (point1[0] - point2[0])**2 +
        (point1[1] - point2[1])**2
    )


def calculate_angle(
    point1: tuple,
    point2: tuple
) -> float:
    """Calcular ángulo entre dos puntos en grados"""
    dx = point2[0] - point1[0]
    dy = point2[1] - point1[1]
    angle = np.degrees(np.arctan2(dy, dx))
    return angle


def interpolate_trajectory(
    trajectory: list,
    num_points: int
) -> list:
    """
    Interpolar trayectoria para tener un número fijo de puntos
    
    Args:
        trajectory: Lista de puntos (x, y)
        num_points: Número de puntos deseado
        
    Returns:
        Trayectoria interpolada
    """
    if len(trajectory) < 2:
        return trajectory
    
    # Convertir a array numpy
    trajectory = np.array(trajectory)
    
    # Crear índices para interpolación
    original_indices = np.linspace(0, len(trajectory) - 1, len(trajectory))
    target_indices = np.linspace(0, len(trajectory) - 1, num_points)
    
    # Interpolar x e y por separado
    x_interp = np.interp(target_indices, original_indices, trajectory[:, 0])
    y_interp = np.interp(target_indices, original_indices, trajectory[:, 1])
    
    # Combinar
    interpolated = np.column_stack([x_interp, y_interp])
    
    return interpolated.tolist()
