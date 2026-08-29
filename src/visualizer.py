"""
Módulo de visualización para detecciones, tracking y conteo
"""

import cv2
import numpy as np
import logging
from typing import List, Dict, Optional, Tuple


class Visualizer:
    """
    Visualizador para el sistema de aforo vehicular
    
    Características:
    - Dibuja bounding boxes con IDs
    - Visualiza trayectorias
    - Muestra línea de conteo
    - Display de estadísticas en tiempo real
    - Mapas de calor de tráfico
    """
    
    # Colores por clase de vehículo (BGR)
    COLORS = {
        'car': (0, 255, 0),      # Verde
        'motorcycle': (255, 0, 0),  # Azul
        'bus': (0, 165, 255),    # Naranja
        'truck': (0, 0, 255)     # Rojo
    }
    
    # Color por defecto
    DEFAULT_COLOR = (255, 255, 255)  # Blanco
    
    # Colores para direcciones
    DIRECTION_COLORS = {
        'in': (0, 255, 0),   # Verde
        'out': (0, 0, 255),  # Rojo
        'unknown': (128, 128, 128)  # Gris
    }
    
    def __init__(
        self,
        show_labels: bool = True,
        show_trajectories: bool = True,
        show_ids: bool = True,
        config: Optional[Dict] = None
    ):
        """
        Inicializar visualizador
        
        Args:
            show_labels: Mostrar etiquetas de clase
            show_trajectories: Mostrar trayectorias
            show_ids: Mostrar IDs de tracks
            config: Configuración adicional
        """
        self.show_labels = show_labels
        self.show_trajectories = show_trajectories
        self.show_ids = show_ids
        self.config = config or {}
        
        # Configuraciones visuales
        self.bbox_thickness = self.config.get('bbox_thickness', 2)
        self.font_scale = self.config.get('font_scale', 0.6)
        self.font_thickness = self.config.get('font_thickness', 2)
        self.trajectory_thickness = self.config.get('trajectory_thickness', 2)
        self.trajectory_max_length = self.config.get('trajectory_max_length', 50)
        
        logging.info("Visualizador inicializado")
    
    def draw_detections(
        self,
        frame: np.ndarray,
        detections: List[Dict]
    ) -> np.ndarray:
        """
        Dibujar detecciones en el frame
        
        Args:
            frame: Frame de entrada
            detections: Lista de detecciones
            
        Returns:
            Frame con detecciones dibujadas
        """
        output_frame = frame.copy()
        
        for detection in detections:
            bbox = detection['bbox']
            class_name = detection['class_name']
            confidence = detection['confidence']
            
            # Obtener color
            color = self.COLORS.get(class_name, self.DEFAULT_COLOR)
            
            # Dibujar bounding box
            x1, y1, x2, y2 = map(int, bbox)
            cv2.rectangle(
                output_frame,
                (x1, y1),
                (x2, y2),
                color,
                self.bbox_thickness
            )
            
            # Dibujar etiqueta si está habilitado
            if self.show_labels:
                label = f"{class_name} {confidence:.2f}"
                label_size, _ = cv2.getTextSize(
                    label,
                    cv2.FONT_HERSHEY_SIMPLEX,
                    self.font_scale,
                    self.font_thickness
                )
                
                # Fondo para el texto
                cv2.rectangle(
                    output_frame,
                    (x1, y1 - label_size[1] - 10),
                    (x1 + label_size[0], y1),
                    color,
                    -1
                )
                
                # Texto
                cv2.putText(
                    output_frame,
                    label,
                    (x1, y1 - 5),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    self.font_scale,
                    (0, 0, 0),
                    self.font_thickness
                )
        
        return output_frame
    
    def draw_tracks(
        self,
        frame: np.ndarray,
        tracks: List[Dict]
    ) -> np.ndarray:
        """
        Dibujar tracks en el frame
        
        Args:
            frame: Frame de entrada
            tracks: Lista de tracks
            
        Returns:
            Frame con tracks dibujados
        """
        output_frame = frame.copy()
        
        for track in tracks:
            track_id = track['id']
            bbox = track['bbox']
            class_name = track['class_name']
            confidence = track['confidence']
            trajectory = track.get('trajectory', [])
            
            # Obtener color
            color = self.COLORS.get(class_name, self.DEFAULT_COLOR)
            
            # Dibujar bounding box
            x1, y1, x2, y2 = map(int, bbox)
            cv2.rectangle(
                output_frame,
                (x1, y1),
                (x2, y2),
                color,
                self.bbox_thickness
            )
            
            # Dibujar ID y etiqueta
            if self.show_ids or self.show_labels:
                if self.show_ids and self.show_labels:
                    label = f"ID:{track_id} {class_name} {confidence:.2f}"
                elif self.show_ids:
                    label = f"ID:{track_id}"
                else:
                    label = f"{class_name} {confidence:.2f}"
                
                label_size, _ = cv2.getTextSize(
                    label,
                    cv2.FONT_HERSHEY_SIMPLEX,
                    self.font_scale,
                    self.font_thickness
                )
                
                # Fondo para el texto
                cv2.rectangle(
                    output_frame,
                    (x1, y1 - label_size[1] - 10),
                    (x1 + label_size[0], y1),
                    color,
                    -1
                )
                
                # Texto
                cv2.putText(
                    output_frame,
                    label,
                    (x1, y1 - 5),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    self.font_scale,
                    (255, 255, 255),
                    self.font_thickness
                )
            
            # Dibujar trayectoria
            if self.show_trajectories and len(trajectory) > 1:
                points = [
                    (int(x), int(y))
                    for x, y in trajectory[-self.trajectory_max_length:]
                ]
                
                # Dibujar líneas entre puntos
                for i in range(1, len(points)):
                    cv2.line(
                        output_frame,
                        points[i-1],
                        points[i],
                        color,
                        self.trajectory_thickness
                    )
                
                # Dibujar punto final (posición actual)
                if points:
                    cv2.circle(
                        output_frame,
                        points[-1],
                        5,
                        color,
                        -1
                    )
        
        return output_frame
    
    def draw_counting_line(
        self,
        frame: np.ndarray,
        line_coordinates: Optional[List[Tuple[int, int]]] = None,
        line_color: Tuple[int, int, int] = (255, 255, 0),  # Cian
        line_thickness: int = 3
    ) -> np.ndarray:
        """
        Dibujar línea de conteo
        
        Args:
            frame: Frame de entrada
            line_coordinates: Lista de puntos [(x1, y1), (x2, y2), ...]
            line_color: Color de la línea (BGR)
            line_thickness: Grosor de la línea
            
        Returns:
            Frame con línea dibujada
        """
        if line_coordinates is None or len(line_coordinates) < 2:
            return frame
        
        output_frame = frame.copy()
        
        # Dibujar línea
        points = [tuple(map(int, p)) for p in line_coordinates]
        
        for i in range(len(points) - 1):
            cv2.line(
                output_frame,
                points[i],
                points[i + 1],
                line_color,
                line_thickness
            )
        
        # Dibujar puntos extremos
        for point in points:
            cv2.circle(
                output_frame,
                point,
                5,
                line_color,
                -1
            )
        
        return output_frame
    
    def draw_statistics(
        self,
        frame: np.ndarray,
        counts: Dict,
        detailed_counts: Optional[Dict] = None,
        position: Tuple[int, int] = (20, 40),
        background_alpha: float = 0.7,
        title: str = "AFORO VEHICULAR"
    ) -> np.ndarray:
        """
        Dibujar estadísticas en el frame

        Args:
            frame: Frame de entrada
            counts: Conteos generales
            detailed_counts: Conteos detallados por tipo
            position: Posición del panel (x, y)
            background_alpha: Transparencia del fondo
            title: Título del panel (ej. nombre del carril, útil cuando
                hay varios carriles en el mismo video)

        Returns:
            Frame con estadísticas
        """
        output_frame = frame.copy()
        x, y = position
        line_height = 30
        padding = 15

        # Preparar texto
        lines = [
            f"=== {title} ===",
            f"Entrada: {counts['in']}",
            f"Salida: {counts['out']}",
            f"Total: {counts['total']}",
            f"Flujo Neto: {counts['net_flow']}"
        ]
        
        # Agregar conteos por tipo si están disponibles
        if detailed_counts:
            lines.append("--- Por Tipo ---")
            for vehicle_type, type_counts in detailed_counts.items():
                lines.append(
                    f"{vehicle_type.upper()}: "
                    f"E:{type_counts['in']} S:{type_counts['out']}"
                )
        
        # Calcular tamaño del panel
        max_width = max([
            cv2.getTextSize(
                line,
                cv2.FONT_HERSHEY_SIMPLEX,
                self.font_scale,
                self.font_thickness
            )[0][0]
            for line in lines
        ])
        
        panel_width = max_width + 2 * padding
        panel_height = len(lines) * line_height + padding
        
        # Crear overlay para transparencia
        overlay = output_frame.copy()
        
        # Dibujar fondo del panel
        cv2.rectangle(
            overlay,
            (x - padding, y - line_height),
            (x + panel_width, y + panel_height),
            (0, 0, 0),
            -1
        )
        
        # Aplicar transparencia
        cv2.addWeighted(
            overlay,
            background_alpha,
            output_frame,
            1 - background_alpha,
            0,
            output_frame
        )
        
        # Dibujar texto
        for i, line in enumerate(lines):
            y_pos = y + i * line_height
            
            # Color según la línea
            if "Entrada" in line:
                text_color = self.DIRECTION_COLORS['in']
            elif "Salida" in line:
                text_color = self.DIRECTION_COLORS['out']
            else:
                text_color = (255, 255, 255)
            
            cv2.putText(
                output_frame,
                line,
                (x, y_pos),
                cv2.FONT_HERSHEY_SIMPLEX,
                self.font_scale,
                text_color,
                self.font_thickness
            )
        
        return output_frame
    
    def create_visualization(
        self,
        frame: np.ndarray,
        tracks: List[Dict],
        counting_line: Optional[List[Tuple[int, int]]],
        counts: Dict,
        detailed_counts: Optional[Dict] = None,
        frame_number: Optional[int] = None
    ) -> np.ndarray:
        """
        Crear visualización completa
        
        Args:
            frame: Frame de entrada
            tracks: Lista de tracks
            counting_line: Coordenadas de la línea de conteo
            counts: Conteos generales
            detailed_counts: Conteos detallados
            frame_number: Número de frame (opcional)
            
        Returns:
            Frame completamente visualizado
        """
        # Dibujar tracks
        output_frame = self.draw_tracks(frame, tracks)
        
        # Dibujar línea de conteo
        output_frame = self.draw_counting_line(output_frame, counting_line)
        
        # Dibujar estadísticas
        output_frame = self.draw_statistics(
            output_frame,
            counts,
            detailed_counts
        )
        
        # Dibujar número de frame si está disponible
        if frame_number is not None:
            cv2.putText(
                output_frame,
                f"Frame: {frame_number}",
                (output_frame.shape[1] - 200, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2
            )
        
        return output_frame
    
    @staticmethod
    def create_heatmap(
        frame_shape: Tuple[int, int],
        trajectories: Dict[int, List[Tuple[float, float]]],
        colormap: int = cv2.COLORMAP_JET
    ) -> np.ndarray:
        """
        Crear mapa de calor de tráfico
        
        Args:
            frame_shape: Forma del frame (height, width)
            trajectories: Diccionario de trayectorias
            colormap: Mapa de colores de OpenCV
            
        Returns:
            Mapa de calor
        """
        height, width = frame_shape[:2]
        heatmap = np.zeros((height, width), dtype=np.float32)
        
        # Acumular densidad de puntos
        for trajectory in trajectories.values():
            for x, y in trajectory:
                x_int = int(np.clip(x, 0, width - 1))
                y_int = int(np.clip(y, 0, height - 1))
                
                # Agregar gaussiana alrededor del punto
                for dy in range(-5, 6):
                    for dx in range(-5, 6):
                        nx = x_int + dx
                        ny = y_int + dy
                        
                        if 0 <= nx < width and 0 <= ny < height:
                            distance = np.sqrt(dx**2 + dy**2)
                            weight = np.exp(-distance / 3.0)
                            heatmap[ny, nx] += weight
        
        # Normalizar
        if heatmap.max() > 0:
            heatmap = (heatmap / heatmap.max() * 255).astype(np.uint8)
        
        # Aplicar colormap
        heatmap_color = cv2.applyColorMap(heatmap, colormap)
        
        return heatmap_color

    def draw_lane_summary(
        self,
        frame: np.ndarray,
        lanes: List[Tuple[str, Dict, Tuple[int, int, int]]],
        position: Tuple[int, int] = (10, 10),
        background_alpha: float = 0.55
    ) -> np.ndarray:
        """
        Panel compacto: una línea por carril, en vez de un bloque de cinco
        líneas por cada uno.

        El panel anterior ocupaba ~150 px de alto por carril; con dos
        carriles tapaba un tercio de un cuadro de 360 px de alto, justo la
        zona por donde entran los vehículos. Aquí cada carril cabe en una
        línea con su color, y el panel completo mide unos 50 px.

        lanes: lista de (nombre, counts, color_bgr)
        """
        out = frame.copy()
        x, y = position
        fs = 0.42          # fuente chica: el panel informa, no protagoniza
        th = 1
        line_h = 17
        pad = 7

        filas = [
            (nombre, f"{c['in']}>  {c['out']}<  ={c['total']}", color)
            for nombre, c, color in lanes
        ]
        if not filas:
            return out

        ancho_nombre = max(
            cv2.getTextSize(n, cv2.FONT_HERSHEY_SIMPLEX, fs, th)[0][0] for n, _, _ in filas
        )
        ancho_cifras = max(
            cv2.getTextSize(v, cv2.FONT_HERSHEY_SIMPLEX, fs, th)[0][0] for _, v, _ in filas
        )
        w = ancho_nombre + ancho_cifras + 3 * pad + 10
        h = len(filas) * line_h + pad

        overlay = out.copy()
        cv2.rectangle(overlay, (x, y), (x + w, y + h), (0, 0, 0), -1)
        cv2.addWeighted(overlay, background_alpha, out, 1 - background_alpha, 0, out)

        for i, (nombre, cifras, color) in enumerate(filas):
            yy = y + pad + i * line_h + 8
            # Marca del color del carril, para saber a qué línea del video
            # corresponde cada fila sin leer el nombre.
            cv2.rectangle(out, (x + 4, yy - 6), (x + 9, yy - 1), color, -1)
            cv2.putText(out, nombre, (x + 14, yy), cv2.FONT_HERSHEY_SIMPLEX, fs,
                        (255, 255, 255), th, cv2.LINE_AA)
            cv2.putText(out, cifras, (x + 14 + ancho_nombre + pad, yy),
                        cv2.FONT_HERSHEY_SIMPLEX, fs, (200, 255, 200), th, cv2.LINE_AA)

        return out
