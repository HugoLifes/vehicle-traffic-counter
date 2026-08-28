"""
Módulo de conteo bidireccional de vehículos
Implementa detección de cruces de línea y análisis de dirección
"""

import numpy as np
import logging
from typing import List, Dict, Optional, Tuple, Set
from collections import defaultdict
from enum import Enum


class Direction(Enum):
    """Direcciones de cruce"""
    ENTERING = "in"
    EXITING = "out"
    UNKNOWN = "unknown"


class LineType(Enum):
    """Tipos de línea de conteo"""
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"
    DIAGONAL = "diagonal"
    POLYGON = "polygon"


class BidirectionalCounter:
    """
    Contador bidireccional de vehículos
    
    Características:
    - Detección de cruce de línea en ambas direcciones
    - Soporte para múltiples tipos de líneas (horizontal, vertical, diagonal, polígono)
    - Filtrado de conteos duplicados
    - Análisis de vectores de movimiento
    - Estadísticas detalladas por tipo de vehículo
    """
    
    def __init__(
        self,
        line_position: Optional[int] = None,
        line_type: str = "horizontal",
        config: Optional[Dict] = None
    ):
        """
        Inicializar contador
        
        Args:
            line_position: Posición de la línea (Y para horizontal, X para vertical)
            line_type: Tipo de línea ('horizontal', 'vertical', 'diagonal', 'polygon')
            config: Configuración adicional
        """
        self.line_position = line_position
        self.line_type = LineType(line_type)
        self.config = config or {}
        
        # Línea de conteo (se configurará con set_counting_line)
        self.counting_line = None
        
        # Contadores principales
        self.count_in = 0
        self.count_out = 0
        
        # Contadores por tipo de vehículo
        self.counts_by_type = defaultdict(lambda: {'in': 0, 'out': 0, 'total': 0})
        
        # Historial de IDs contados para evitar duplicados
        self.counted_ids: Set[int] = set()
        
        # Estado de tracks (para detectar cruces)
        self.track_states = {}  # {track_id: {'last_position': (x,y), 'crossed': bool}}
        
        # Configuraciones
        self.crossing_tolerance = self.config.get('crossing_tolerance', 10)
        self.min_trajectory_points = self.config.get('min_trajectory_points', 3)
        
        # Historial de cruces (para análisis)
        self.crossing_history = []
        
        logging.info(f"Contador inicializado: tipo={line_type}")
    
    def set_counting_line(
        self,
        line_type: str,
        y: Optional[int] = None,
        x: Optional[int] = None,
        points: Optional[List[Tuple[int, int]]] = None,
        frame_shape: Optional[Tuple[int, int]] = None
    ):
        """
        Configurar línea de conteo
        
        Args:
            line_type: 'horizontal', 'vertical', 'diagonal', 'polygon'
            y: Posición Y (para líneas horizontales)
            x: Posición X (para líneas verticales)
            points: Lista de puntos para líneas diagonales o polígonos
            frame_shape: Forma del frame (height, width) para calcular extremos
        """
        self.line_type = LineType(line_type)
        
        if self.line_type == LineType.HORIZONTAL:
            if y is None:
                raise ValueError("Se requiere 'y' para línea horizontal")
            
            # Línea horizontal de izquierda a derecha
            width = frame_shape[1] if frame_shape else 1920
            self.counting_line = {
                'type': 'horizontal',
                'y': y,
                'x1': 0,
                'x2': width,
                'points': [(0, y), (width, y)]
            }
            
        elif self.line_type == LineType.VERTICAL:
            if x is None:
                raise ValueError("Se requiere 'x' para línea vertical")
            
            # Línea vertical de arriba a abajo
            height = frame_shape[0] if frame_shape else 1080
            self.counting_line = {
                'type': 'vertical',
                'x': x,
                'y1': 0,
                'y2': height,
                'points': [(x, 0), (x, height)]
            }
            
        elif self.line_type == LineType.DIAGONAL:
            if points is None or len(points) < 2:
                raise ValueError("Se requieren al menos 2 puntos para línea diagonal")
            
            self.counting_line = {
                'type': 'diagonal',
                'points': points
            }
            
        elif self.line_type == LineType.POLYGON:
            if points is None or len(points) < 3:
                raise ValueError("Se requieren al menos 3 puntos para polígono")
            
            self.counting_line = {
                'type': 'polygon',
                'points': points
            }
        
        logging.info(f"Línea de conteo configurada: {self.counting_line}")
    
    def _check_line_crossing(
        self,
        prev_position: Tuple[float, float],
        curr_position: Tuple[float, float]
    ) -> Optional[Direction]:
        """
        Verificar si una trayectoria cruza la línea de conteo
        
        Args:
            prev_position: Posición previa (x, y)
            curr_position: Posición actual (x, y)
            
        Returns:
            Direction o None si no hubo cruce
        """
        if self.counting_line is None:
            return None
        
        px, py = prev_position
        cx, cy = curr_position
        
        if self.line_type == LineType.HORIZONTAL:
            line_y = self.counting_line['y']
            
            # Verificar cruce de línea horizontal
            if abs(py - line_y) <= self.crossing_tolerance or \
               abs(cy - line_y) <= self.crossing_tolerance:
                # Determinar dirección
                if py < line_y and cy >= line_y:
                    return Direction.ENTERING  # De arriba hacia abajo
                elif py > line_y and cy <= line_y:
                    return Direction.EXITING  # De abajo hacia arriba
            
        elif self.line_type == LineType.VERTICAL:
            line_x = self.counting_line['x']
            
            # Verificar cruce de línea vertical
            if abs(px - line_x) <= self.crossing_tolerance or \
               abs(cx - line_x) <= self.crossing_tolerance:
                # Determinar dirección
                if px < line_x and cx >= line_x:
                    return Direction.ENTERING  # De izquierda a derecha
                elif px > line_x and cx <= line_x:
                    return Direction.EXITING  # De derecha a izquierda
        
        elif self.line_type in [LineType.DIAGONAL, LineType.POLYGON]:
            # Para líneas diagonales, usar producto cruzado
            # Implementación simplificada para líneas de 2 puntos
            if len(self.counting_line['points']) == 2:
                p1, p2 = self.counting_line['points']
                
                # Verificar si el segmento (prev_pos, curr_pos) cruza (p1, p2)
                if self._segments_intersect(
                    (px, py), (cx, cy),
                    p1, p2
                ):
                    # Determinar dirección usando producto cruzado
                    direction_vector = self._calculate_crossing_direction(
                        (px, py), (cx, cy), p1, p2
                    )
                    return direction_vector
        
        return None
    
    def _segments_intersect(
        self,
        a1: Tuple[float, float],
        a2: Tuple[float, float],
        b1: Tuple[float, float],
        b2: Tuple[float, float]
    ) -> bool:
        """Verificar si dos segmentos se intersectan"""
        def ccw(A, B, C):
            return (C[1] - A[1]) * (B[0] - A[0]) > (B[1] - A[1]) * (C[0] - A[0])
        
        return ccw(a1, b1, b2) != ccw(a2, b1, b2) and \
               ccw(a1, a2, b1) != ccw(a1, a2, b2)
    
    def _calculate_crossing_direction(
        self,
        prev_pos: Tuple[float, float],
        curr_pos: Tuple[float, float],
        line_p1: Tuple[float, float],
        line_p2: Tuple[float, float]
    ) -> Direction:
        """Calcular dirección de cruce usando producto cruzado"""
        # Vector de movimiento
        dx = curr_pos[0] - prev_pos[0]
        dy = curr_pos[1] - prev_pos[1]
        
        # Vector de la línea
        lx = line_p2[0] - line_p1[0]
        ly = line_p2[1] - line_p1[1]
        
        # Producto cruzado
        cross = dx * ly - dy * lx
        
        # Dirección basada en el signo del producto cruzado
        if cross > 0:
            return Direction.ENTERING
        elif cross < 0:
            return Direction.EXITING
        else:
            return Direction.UNKNOWN
    
    def update(self, tracks: List[Dict]) -> Dict:
        """
        Actualizar contador con tracks actuales
        
        Args:
            tracks: Lista de tracks del tracker
            
        Returns:
            Información de cruces en este frame
        """
        frame_crossings = {
            'in': [],
            'out': [],
            'count': 0
        }
        
        for track in tracks:
            track_id = track['id']
            
            # Obtener posición actual (centro del bbox)
            x1, y1, x2, y2 = track['bbox']
            curr_position = ((x1 + x2) / 2, (y1 + y2) / 2)
            
            # Verificar si ya tenemos estado previo de este track
            if track_id in self.track_states:
                prev_position = self.track_states[track_id]['last_position']
                already_crossed = self.track_states[track_id]['crossed']
                
                # Solo verificar si no ha cruzado antes
                if not already_crossed:
                    # Verificar si hubo suficiente trayectoria
                    if len(track.get('trajectory', [])) >= self.min_trajectory_points:
                        # Verificar cruce
                        direction = self._check_line_crossing(
                            prev_position,
                            curr_position
                        )
                        
                        if direction is not None and direction != Direction.UNKNOWN:
                            # Verificar que no se haya contado antes
                            if track_id not in self.counted_ids:
                                # Registrar cruce
                                self._register_crossing(
                                    track_id=track_id,
                                    direction=direction,
                                    vehicle_type=track['class_name'],
                                    position=curr_position,
                                    confidence=track['confidence']
                                )
                                
                                # Agregar a lista de cruces del frame
                                crossing_info = {
                                    'track_id': track_id,
                                    'direction': direction.value,
                                    'vehicle_type': track['class_name'],
                                    'position': curr_position
                                }
                                
                                if direction == Direction.ENTERING:
                                    frame_crossings['in'].append(crossing_info)
                                else:
                                    frame_crossings['out'].append(crossing_info)
                                
                                frame_crossings['count'] += 1
                                
                                # Marcar como cruzado
                                self.track_states[track_id]['crossed'] = True
                                self.counted_ids.add(track_id)
            
            # Actualizar estado del track
            self.track_states[track_id] = {
                'last_position': curr_position,
                'crossed': self.track_states.get(track_id, {}).get('crossed', False)
            }
        
        return frame_crossings
    
    def _register_crossing(
        self,
        track_id: int,
        direction: Direction,
        vehicle_type: str,
        position: Tuple[float, float],
        confidence: float
    ):
        """Registrar un cruce de vehículo"""
        # Actualizar contadores principales
        if direction == Direction.ENTERING:
            self.count_in += 1
        elif direction == Direction.EXITING:
            self.count_out += 1
        
        # Actualizar contadores por tipo
        if direction == Direction.ENTERING:
            self.counts_by_type[vehicle_type]['in'] += 1
        elif direction == Direction.EXITING:
            self.counts_by_type[vehicle_type]['out'] += 1
        
        self.counts_by_type[vehicle_type]['total'] = (
            self.counts_by_type[vehicle_type]['in'] +
            self.counts_by_type[vehicle_type]['out']
        )
        
        # Registrar en historial
        crossing_event = {
            'track_id': track_id,
            'direction': direction.value,
            'vehicle_type': vehicle_type,
            'position': position,
            'confidence': confidence,
            'timestamp': None  # Se puede agregar timestamp real
        }
        self.crossing_history.append(crossing_event)
        
        logging.info(
            f"Cruce detectado: Track {track_id} ({vehicle_type}) - "
            f"Dirección: {direction.value}"
        )
    
    def get_counts(self) -> Dict:
        """Obtener conteos actuales"""
        return {
            'in': self.count_in,
            'out': self.count_out,
            'total': self.count_in + self.count_out,
            'net_flow': self.count_in - self.count_out
        }
    
    def get_detailed_counts(self) -> Dict:
        """Obtener conteos detallados por tipo de vehículo"""
        return dict(self.counts_by_type)
    
    def get_crossing_history(self) -> List[Dict]:
        """Obtener historial completo de cruces"""
        return self.crossing_history
    
    def get_line_coordinates(self) -> Optional[List[Tuple[int, int]]]:
        """Obtener coordenadas de la línea de conteo para visualización"""
        if self.counting_line is None:
            return None
        
        return self.counting_line.get('points', [])
    
    def reset(self):
        """Reiniciar contadores"""
        self.count_in = 0
        self.count_out = 0
        self.counts_by_type.clear()
        self.counted_ids.clear()
        self.track_states.clear()
        self.crossing_history.clear()
        
        logging.info("Contadores reiniciados")
    
    def get_statistics(self) -> Dict:
        """Obtener estadísticas del contador"""
        total_crossings = len(self.crossing_history)
        
        stats = {
            'total_crossings': total_crossings,
            'count_in': self.count_in,
            'count_out': self.count_out,
            'net_flow': self.count_in - self.count_out,
            'by_vehicle_type': dict(self.counts_by_type),
            'line_type': self.line_type.value,
            'unique_vehicles': len(self.counted_ids)
        }
        
        return stats
