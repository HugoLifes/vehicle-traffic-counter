"""
Módulo de tracking de vehículos usando DeepSORT
Implementa tracking robusto con Kalman Filter y Hungarian Algorithm
"""

import numpy as np
import logging
from typing import List, Dict, Optional, Tuple
from collections import deque, defaultdict
from scipy.optimize import linear_sum_assignment
from filterpy.kalman import KalmanFilter


class Track:
    """
    Representa un vehículo rastreado
    
    Mantiene:
    - Estado actual (posición, velocidad)
    - Historial de trayectoria
    - Información de clase y confianza
    """
    
    # Contador global para IDs únicos
    _id_counter = 0
    
    def __init__(
        self,
        bbox: List[float],
        class_id: int,
        class_name: str,
        confidence: float,
        buffer_size: int = 60
    ):
        """
        Inicializar track
        
        Args:
            bbox: Bounding box [x1, y1, x2, y2]
            class_id: ID de clase
            class_name: Nombre de clase
            confidence: Confianza de detección
            buffer_size: Tamaño del buffer de trayectoria
        """
        # ID único
        self.id = Track._id_counter
        Track._id_counter += 1
        
        # Información de detección
        self.bbox = bbox
        self.class_id = class_id
        self.class_name = class_name
        self.confidence = confidence

        # La clase se decide por VOTO de todas las detecciones del rastro,
        # pesado por confianza, no por la primera.
        #
        # Antes quedaba fija en la del primer cuadro y no se tocaba nunca.
        # Un vehículo que entra al cuadro como una rebanada se detecta un
        # instante como 'motorcycle', y así se reportaba aunque después el
        # detector dijera 'car' con 0.90 durante cien cuadros. Medido en la
        # cámara frontal de Cd. Juárez: 113 de 709 cruces de una calzada
        # salieron como motocicleta, y al mirarlos eran minivans, sedanes,
        # un tractocamión y una pipa.
        self.votos_clase = {class_name: (confidence, class_id)}
        
        # Estado
        self.age = 0  # Frames desde creación
        self.hits = 1  # Detecciones exitosas
        self.miss_streak = 0  # Frames consecutivos sin detección
        self.is_confirmed = False  # Track confirmado
        self.is_deleted = False  # Track eliminado
        
        # Trayectoria
        self.trajectory = deque(maxlen=buffer_size)
        self.trajectory.append(self._bbox_center(bbox))
        
        # Filtro de Kalman para predicción
        self.kf = self._init_kalman_filter(bbox)
        
        # Metadata
        self.metadata = {
            'creation_frame': 0,
            'last_seen_frame': 0,
            'total_frames_tracked': 0,
            'average_confidence': confidence
        }
    
    @staticmethod
    def _bbox_center(bbox: List[float]) -> Tuple[float, float]:
        """Calcular centro del bbox"""
        x1, y1, x2, y2 = bbox
        return ((x1 + x2) / 2, (y1 + y2) / 2)
    
    def _init_kalman_filter(self, bbox: List[float]) -> KalmanFilter:
        """
        Inicializar Filtro de Kalman
        
        Estado: [x, y, w, h, vx, vy, vw, vh]
        - (x, y): centro del bbox
        - (w, h): ancho y alto
        - (vx, vy, vw, vh): velocidades
        """
        kf = KalmanFilter(dim_x=8, dim_z=4)
        
        # Matriz de transición de estado (F)
        kf.F = np.array([
            [1, 0, 0, 0, 1, 0, 0, 0],  # x = x + vx
            [0, 1, 0, 0, 0, 1, 0, 0],  # y = y + vy
            [0, 0, 1, 0, 0, 0, 1, 0],  # w = w + vw
            [0, 0, 0, 1, 0, 0, 0, 1],  # h = h + vh
            [0, 0, 0, 0, 1, 0, 0, 0],  # vx = vx
            [0, 0, 0, 0, 0, 1, 0, 0],  # vy = vy
            [0, 0, 0, 0, 0, 0, 1, 0],  # vw = vw
            [0, 0, 0, 0, 0, 0, 0, 1]   # vh = vh
        ])
        
        # Matriz de medición (H)
        kf.H = np.array([
            [1, 0, 0, 0, 0, 0, 0, 0],  # medimos x
            [0, 1, 0, 0, 0, 0, 0, 0],  # medimos y
            [0, 0, 1, 0, 0, 0, 0, 0],  # medimos w
            [0, 0, 0, 1, 0, 0, 0, 0]   # medimos h
        ])
        
        # Covarianza del ruido del proceso (Q)
        kf.Q *= 0.01
        
        # Covarianza del ruido de medición (R)
        kf.R *= 1.0
        
        # Covarianza del estado inicial (P)
        kf.P *= 10.0
        
        # Estado inicial
        x1, y1, x2, y2 = bbox
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        w = x2 - x1
        h = y2 - y1
        
        kf.x = np.array([cx, cy, w, h, 0, 0, 0, 0])
        
        return kf
    
    def predict(self) -> np.ndarray:
        """
        Avanza el filtro de Kalman UN cuadro y devuelve la caja predicha.

        Se llama una sola vez por cuadro (VehicleTracker.update). Antes se
        llamaba dentro del doble ciclo detección × rastro: con D vehículos
        en pantalla el filtro avanzaba D pasos por cuadro y además sumaba D
        a miss_streak. Medido con cajas sintéticas que el detector pierde 5
        cuadros: con 1 vehículo en pantalla no se partía ningún rastro; con
        8, se partían los 8. El rastro se borraba por "viejo" en 30/D
        cuadros en vez de 30, justo cuando la vía está llena.
        """
        self.kf.predict()

        # Convertir estado predicho a bbox
        x, y, w, h = self.kf.x[:4]
        predicted_bbox = [
            x - w/2,
            y - h/2,
            x + w/2,
            y + h/2
        ]
        
        return np.array(predicted_bbox)
    
    def update(
        self,
        bbox: List[float],
        confidence: float,
        frame_number: int,
        class_name: str = None,
        class_id: int = None
    ):
        """Actualizar track con nueva detección.

        `class_name` entra al voto de clase del rastro; sin él la clase se
        queda como estaba (así siguen funcionando las llamadas viejas).
        """
        # Actualizar Kalman Filter
        x1, y1, x2, y2 = bbox
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        w = x2 - x1
        h = y2 - y1
        
        measurement = np.array([cx, cy, w, h])
        self.kf.update(measurement)
        
        # Actualizar información
        self.bbox = bbox
        self.confidence = confidence
        if class_name is not None:
            peso, _ = self.votos_clase.get(class_name, (0.0, class_id))
            self.votos_clase[class_name] = (peso + confidence, class_id)
            ganadora, (_, id_ganadora) = max(self.votos_clase.items(),
                                             key=lambda kv: kv[1][0])
            self.class_name, self.class_id = ganadora, id_ganadora
        self.hits += 1
        self.age += 1
        self.miss_streak = 0
        
        # Actualizar trayectoria
        center = self._bbox_center(bbox)
        self.trajectory.append(center)
        
        # Actualizar metadata
        self.metadata['last_seen_frame'] = frame_number
        self.metadata['total_frames_tracked'] += 1
        
        # Actualizar confianza promedio
        total_conf = (
            self.metadata['average_confidence'] * (self.hits - 1) + confidence
        )
        self.metadata['average_confidence'] = total_conf / self.hits
    
    def mark_missed(self):
        """Marcar como no detectado en el frame actual"""
        self.miss_streak += 1
        self.age += 1
    
    def get_state(self) -> Dict:
        """Obtener estado actual del track"""
        return {
            'id': self.id,
            'bbox': self.bbox,
            'class_id': self.class_id,
            'class_name': self.class_name,
            'confidence': self.confidence,
            'age': self.age,
            'hits': self.hits,
            'trajectory': list(self.trajectory),
            'is_confirmed': self.is_confirmed,
            'velocity': self.get_velocity(),
            'metadata': self.metadata
        }
    
    def get_velocity(self) -> Optional[Tuple[float, float]]:
        """Calcular velocidad actual (pixels/frame)"""
        if len(self.trajectory) < 2:
            return None
        
        # Usar últimas dos posiciones
        p1 = self.trajectory[-2]
        p2 = self.trajectory[-1]
        
        vx = p2[0] - p1[0]
        vy = p2[1] - p1[1]
        
        return (vx, vy)
    
    def get_direction_angle(self) -> Optional[float]:
        """Calcular ángulo de dirección en grados"""
        velocity = self.get_velocity()
        if velocity is None:
            return None
        
        vx, vy = velocity
        angle = np.degrees(np.arctan2(vy, vx))
        return angle


class VehicleTracker:
    """
    Tracker de vehículos con algoritmo tipo DeepSORT
    
    Características:
    - Tracking multi-objeto
    - Predicción con Kalman Filter
    - Asociación con Hungarian Algorithm
    - Manejo de oclusiones
    """
    
    def __init__(
        self,
        max_age: int = 30,
        min_hits: int = 3,
        iou_threshold: float = 0.3,
        buffer_size: int = 60,
        config: Optional[Dict] = None
    ):
        """
        Inicializar tracker
        
        Args:
            max_age: Máximo de frames sin detección antes de eliminar
            min_hits: Mínimo de hits para confirmar track
            iou_threshold: Umbral IoU para asociación
            buffer_size: Tamaño del buffer de trayectorias
            config: Configuración adicional
        """
        self.max_age = max_age
        self.min_hits = min_hits
        self.iou_threshold = iou_threshold
        self.buffer_size = buffer_size
        self.config = config or {}
        
        # Tracks activos
        self.tracks: List[Track] = []
        
        # Historial de tracks eliminados
        self.deleted_tracks: List[Track] = []
        
        # Estadísticas
        self.frame_count = 0
        self.total_tracks_created = 0
        
        logging.info(
            f"Tracker inicializado: max_age={max_age}, "
            f"min_hits={min_hits}, iou={iou_threshold}"
        )
    
    @staticmethod
    def calculate_iou(bbox1: List[float], bbox2: List[float]) -> float:
        """Calcular Intersection over Union (IoU) entre dos bboxes"""
        x1_1, y1_1, x2_1, y2_1 = bbox1
        x1_2, y1_2, x2_2, y2_2 = bbox2
        
        # Coordenadas de intersección
        xi1 = max(x1_1, x1_2)
        yi1 = max(y1_1, y1_2)
        xi2 = min(x2_1, x2_2)
        yi2 = min(y2_1, y2_2)
        
        # Área de intersección
        inter_width = max(0, xi2 - xi1)
        inter_height = max(0, yi2 - yi1)
        inter_area = inter_width * inter_height
        
        # Áreas de los bboxes
        bbox1_area = (x2_1 - x1_1) * (y2_1 - y1_1)
        bbox2_area = (x2_2 - x1_2) * (y2_2 - y1_2)
        
        # Unión
        union_area = bbox1_area + bbox2_area - inter_area
        
        # IoU
        iou = inter_area / union_area if union_area > 0 else 0
        
        return iou
    
    def _associate_detections_to_tracks(
        self,
        detections: List[Dict],
        tracks: List[Track],
        predichos: Optional[List[np.ndarray]] = None
    ) -> Tuple[List[Tuple[int, int]], List[int], List[int]]:
        """
        Asociar detecciones con tracks usando Hungarian Algorithm
        
        Returns:
            matches: Lista de tuplas (detection_idx, track_idx)
            unmatched_detections: Índices de detecciones sin match
            unmatched_tracks: Índices de tracks sin match
        """
        if len(tracks) == 0:
            return [], list(range(len(detections))), []
        
        if len(detections) == 0:
            return [], [], list(range(len(tracks)))
        
        # Construir matriz de costos (basada en IoU)
        cost_matrix = np.zeros((len(detections), len(tracks)))
        if predichos is None:
            predichos = [track.predict() for track in tracks]

        for d, detection in enumerate(detections):
            for t, track in enumerate(tracks):
                # Caja predicha UNA vez por cuadro (ver Track.predict)
                predicted_bbox = predichos[t]

                # Calcular IoU
                iou = self.calculate_iou(detection['bbox'], predicted_bbox)
                
                # Costo = 1 - IoU (queremos minimizar)
                cost_matrix[d, t] = 1 - iou
        
        # Resolver asignación usando Hungarian Algorithm
        detection_indices, track_indices = linear_sum_assignment(cost_matrix)
        
        # Filtrar matches con IoU bajo
        matches = []
        unmatched_detections = []
        unmatched_tracks = list(range(len(tracks)))
        
        for d, t in zip(detection_indices, track_indices):
            iou = 1 - cost_matrix[d, t]
            if iou >= self.iou_threshold:
                matches.append((d, t))
                if t in unmatched_tracks:
                    unmatched_tracks.remove(t)
            # Una detección cuyo mejor emparejamiento quedó por debajo del
            # umbral NO se agrega aquí: ya la recoge la diferencia de
            # conjuntos de abajo. Agregarla en los dos lados la metía DOS
            # veces en la lista y creaba dos rastros del mismo vehículo, que
            # al cruzar la línea se contaban dos veces. Visto en la cámara
            # nueva de Cd. Juárez: una pickup contada como rastros 5802 y
            # 5814 en el mismo segundo.

        # Agregar detecciones no asignadas
        all_detection_indices = set(range(len(detections)))
        matched_detection_indices = set([m[0] for m in matches])
        unmatched_detections.extend(
            list(all_detection_indices - matched_detection_indices)
        )
        
        return matches, unmatched_detections, unmatched_tracks
    
    def update(self, detections: List[Dict]) -> List[Dict]:
        """
        Actualizar tracker con nuevas detecciones
        
        Args:
            detections: Lista de detecciones del detector
            
        Returns:
            Lista de tracks confirmados con su estado actual
        """
        self.frame_count += 1

        # 0. Todos los rastros avanzan un cuadro, haya o no detecciones: un
        # vehículo tapado sigue moviéndose y su predicción tiene que seguirlo.
        predichos = [track.predict() for track in self.tracks]

        # 1. Asociar detecciones con tracks existentes
        matches, unmatched_detections, unmatched_tracks = \
            self._associate_detections_to_tracks(detections, self.tracks, predichos)
        
        # 2. Actualizar tracks con matches
        for detection_idx, track_idx in matches:
            detection = detections[detection_idx]
            track = self.tracks[track_idx]
            
            track.update(
                bbox=detection['bbox'],
                confidence=detection['confidence'],
                frame_number=self.frame_count,
                class_name=detection.get('class_name'),
                class_id=detection.get('class_id')
            )
        
        # 3. Marcar tracks sin match como missed
        for track_idx in unmatched_tracks:
            self.tracks[track_idx].mark_missed()
        
        # 4. Crear nuevos tracks para detecciones sin match
        for detection_idx in unmatched_detections:
            detection = detections[detection_idx]
            new_track = Track(
                bbox=detection['bbox'],
                class_id=detection['class_id'],
                class_name=detection['class_name'],
                confidence=detection['confidence'],
                buffer_size=self.buffer_size
            )
            new_track.metadata['creation_frame'] = self.frame_count
            new_track.metadata['last_seen_frame'] = self.frame_count
            self.tracks.append(new_track)
            self.total_tracks_created += 1
        
        # 5. Confirmar tracks con suficientes hits
        for track in self.tracks:
            if not track.is_confirmed and track.hits >= self.min_hits:
                track.is_confirmed = True
                logging.debug(f"Track {track.id} confirmado")
        
        # 6. Eliminar tracks viejos o fuera de frame
        tracks_to_delete = []
        for i, track in enumerate(self.tracks):
            if track.miss_streak > self.max_age:
                tracks_to_delete.append(i)
                track.is_deleted = True
                self.deleted_tracks.append(track)
        
        # Eliminar en orden inverso para mantener índices
        for i in sorted(tracks_to_delete, reverse=True):
            del self.tracks[i]
        
        # 7. Devolver solo tracks confirmados
        confirmed_tracks = [
            track.get_state()
            for track in self.tracks
            if track.is_confirmed
        ]
        
        return confirmed_tracks
    
    def get_all_trajectories(self) -> Dict[int, List[Tuple[float, float]]]:
        """Obtener todas las trayectorias (activas y eliminadas)"""
        trajectories = {}
        
        # Tracks activos
        for track in self.tracks:
            if track.is_confirmed:
                trajectories[track.id] = list(track.trajectory)
        
        # Tracks eliminados
        for track in self.deleted_tracks:
            if track.is_confirmed:
                trajectories[track.id] = list(track.trajectory)
        
        return trajectories
    
    def get_statistics(self) -> Dict:
        """Obtener estadísticas del tracker"""
        return {
            'active_tracks': len(self.tracks),
            'confirmed_tracks': sum(1 for t in self.tracks if t.is_confirmed),
            'total_tracks_created': self.total_tracks_created,
            'deleted_tracks': len(self.deleted_tracks),
            'frames_processed': self.frame_count
        }
    
    def reset(self):
        """Reiniciar tracker"""
        self.tracks = []
        self.deleted_tracks = []
        self.frame_count = 0
        Track._id_counter = 0
