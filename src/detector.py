"""
Módulo de detección de vehículos usando YOLO
Optimizado para NVIDIA Jetson Nano
"""

import cv2
import numpy as np
import torch
import logging
import math
from pathlib import Path
from typing import List, Dict, Tuple, Optional

try:
    from ultralytics import YOLO
except ImportError:
    logging.error("ultralytics no está instalado. Ejecuta: pip install ultralytics")
    raise


class VehicleDetector:
    """
    Detector de vehículos usando YOLOv8
    
    Soporta:
    - Detección de múltiples clases de vehículos
    - Optimización TensorRT para Jetson Nano
    - Precisión FP16 para mejor rendimiento
    - Filtrado por confianza y clases
    """
    
    # Clases COCO relacionadas con vehículos
    VEHICLE_CLASSES = {
        2: 'car',
        3: 'motorcycle',
        5: 'bus',
        7: 'truck'
    }
    
    def __init__(
        self,
        model_path: str = 'yolov8n.pt',
        confidence_threshold: float = 0.4,
        iou_threshold: float = 0.5,
        input_size: int = 640,
        device: str = 'auto',
        use_tensorrt: bool = False,
        half_precision: bool = False,
        config: Optional[Dict] = None
    ):
        """
        Inicializar detector de vehículos
        
        Args:
            model_path: Ruta al modelo YOLO (.pt, .engine, .onnx)
            confidence_threshold: Umbral de confianza (0-1)
            iou_threshold: Umbral IoU para NMS
            input_size: Tamaño de entrada (320, 640, 1280)
            device: Dispositivo ('auto', 'cpu', 'cuda', '0')
            use_tensorrt: Usar TensorRT si está disponible
            half_precision: Usar FP16 para inferencia
            config: Configuración adicional
        """
        self.model_path = model_path
        self.confidence_threshold = confidence_threshold
        self.iou_threshold = iou_threshold
        # El filtro de cajas repetidas (NMS) de YOLO compara SOLO dentro de
        # cada clase. Un mismo vehículo detectado a la vez como 'car' y como
        # 'truck' deja dos cajas con IoU de 0.97, el rastreador hace dos
        # rastros y la línea lo cuenta dos veces. Medido en la cámara nueva
        # de Cd. Juárez. Comparar entre clases lo elimina; el valor se lee de
        # configs/platform.yaml.
        self.nms_agnostico = (config or {}).get('nms_agnostico', False)
        self.input_size = input_size
        self.use_tensorrt = use_tensorrt
        self.half_precision = half_precision
        self.config = config or {}

        # Banda horizontal (y0, y1) sobre la que se detecta. None = cuadro
        # completo. La fija quien conoce la geometría de los carriles; ver
        # set_detection_band().
        self._band: Optional[Tuple[int, int]] = None
        
        # Determinar dispositivo
        self.device = self._determine_device(device)
        logging.info(f"Usando dispositivo: {self.device}")
        
        # Cargar modelo
        self.model = self._load_model()
        
        # Configurar clases de vehículos
        self.vehicle_classes = self.config.get(
            'vehicle_classes',
            self.VEHICLE_CLASSES
        )
        
        # Estadísticas
        self.total_detections = 0
        self.frame_count = 0
        
        logging.info(
            f"Detector inicializado: {model_path} "
            f"(conf={confidence_threshold}, iou={iou_threshold})"
        )
    
    def _determine_device(self, device: str) -> str:
        """Determinar el dispositivo de procesamiento"""
        if device == 'auto':
            if torch.cuda.is_available():
                return 'cuda:0'
            else:
                logging.warning("CUDA no disponible, usando CPU")
                return 'cpu'
        return device
    
    def _load_model(self) -> YOLO:
        """Cargar modelo YOLO"""
        try:
            # Si el archivo no está, se deja que ultralytics descargue ESE
            # modelo por su nombre. Antes se cambiaba a yolov8n sin más: en
            # un equipo recién instalado eso hacía que el sistema contara
            # con el modelo malo (75 cruces en vez de 107) sin que nada
            # avisara de que no se estaba usando el modelo configurado.
            if not Path(self.model_path).exists():
                nombre = Path(self.model_path).name
                logging.warning(
                    f"Modelo {self.model_path} no encontrado en disco. "
                    f"Se descargará {nombre} desde ultralytics."
                )
                self.model_path = nombre
            
            # Cargar modelo
            model = YOLO(self.model_path)
            
            # Mover a dispositivo
            model.to(self.device)
            
            # Configurar FP16 si está habilitado
            if self.half_precision and self.device != 'cpu':
                logging.info("Habilitando precisión FP16")
                model.half()
            
            # TensorRT NO se exporta aquí. Antes se exportaba al cargar, dentro
            # del hilo de la cola: 9 minutos de GPU en el Orin con el primer
            # video esperando, y el modelo exportado ni siquiera se usaba. Los
            # motores se hacen aparte, uno por tamaño de entrada
            # (tools/exportar_tensorrt.py), y `_modelo_para` los toma si existen.
            self._motores: Dict[Tuple[int, int], YOLO] = {}
            self._sin_motor = set()
            logging.info(f"Modelo cargado: {self.model_path}")
            return model
            
        except Exception as e:
            logging.error(f"Error cargando modelo: {e}")
            raise
    
    def forma_de_entrada(self, alto: int, ancho: int) -> Tuple[int, int]:
        """El tamaño que recibe la red para una imagen de alto x ancho: la
        letterbox rectangular de ultralytics a imgsz (lado mayor = imgsz, el
        otro redondeado y llevado al múltiplo de 32 de arriba)."""
        r = self.input_size / max(alto, ancho)
        return (int(math.ceil(round(alto * r) / 32) * 32),
                int(math.ceil(round(ancho * r) / 32) * 32))

    def ruta_motor(self, forma: Tuple[int, int]) -> Path:
        p = Path(self.model_path)
        return p.with_name(f"{p.stem}_{forma[0]}x{forma[1]}_fp16.engine")

    def _modelo_para(self, entrada: np.ndarray):
        """(modelo, imgsz) para esta entrada. Con `use_tensorrt`, el motor
        TensorRT FP16 de ese tamaño exacto si ya existe; si no, el .pt.

        Medido en el Orin sobre la franja del proyecto 7 (448x1280), 300
        cuadros de día y 300 de noche: 1 944 y 298 detecciones con los dos,
        99.6 % y 100 % emparejadas con la misma clase, confianza movida 0.001
        de mediana, y 63 -> 30 ms por cuadro (6-oct-2026)."""
        if not self.use_tensorrt or not torch.cuda.is_available():
            return self.model, self.input_size
        forma = self.forma_de_entrada(*entrada.shape[:2])
        motor = self._motores.get(forma)
        if motor is None:
            # Sin guardar el "no hay": un motor exportado con la plataforma
            # encendida se toma en el siguiente cuadro, sin reiniciar. Mirar
            # si existe el archivo cuesta microsegundos.
            ruta = self.ruta_motor(forma)
            if ruta.exists():
                logging.info(f"Detector con TensorRT FP16: {ruta}")
                motor = self._motores[forma] = YOLO(str(ruta), task="detect")
            elif forma not in self._sin_motor:
                self._sin_motor.add(forma)
                logging.info(f"Sin motor TensorRT para {forma[0]}x{forma[1]} ({ruta.name}); "
                             f"se usa {self.model_path}. Se crea con tools/exportar_tensorrt.py")
        return (motor, forma) if motor is not None else (self.model, self.input_size)

    def _opciones_precision(self) -> Dict:
        """
        `half` solo se pasa a predict() cuando FP16 está activado.

        En ultralytics 8.4 el argumento está obsoleto y avisa en CADA
        llamada aunque valga False: un aviso por cuadro, que en un aforo de
        24 h son más de un millón de líneas en el log del contenedor. False
        ya es el valor por omisión, así que omitirlo no cambia la detección.
        """
        return {'half': True} if self.half_precision else {}

    def set_detection_band(self, band: Optional[Tuple[int, int]]):
        """
        Limitar la detección a una franja horizontal (y0, y1) del cuadro.

        Sirve cuando la vía ocupa una fracción pequeña del encuadre y el
        resto es terreno sin tránsito: al inferir solo sobre la franja, el
        vehículo llega al modelo con muchos más píxeles y deja de perderse.
        Las cajas se devuelven siempre en coordenadas del cuadro completo,
        así que para el tracker y los contadores es transparente.

        band=None vuelve al cuadro completo.
        """
        self._band = tuple(int(v) for v in band) if band else None
        if self._band:
            logging.info(f"Detectando solo en la franja y={self._band[0]}..{self._band[1]}")

    @staticmethod
    def band_from_lanes(
        lane_points,
        frame_height: int,
        margin_ratio: float = 0.15
    ) -> Optional[Tuple[int, int]]:
        """
        Deriva la franja de detección de los carriles ya calibrados.

        El margen se toma como fracción del alto del cuadro y no como un
        número fijo de píxeles, para que la franja siga siendo razonable
        en cámaras de otra resolución. Tiene que ser generoso: un tráiler
        cerca de la cámara es mucho más alto que la línea de conteo, y si
        se recorta a ras de la línea se pierde justo el vehículo grande.
        """
        ys = [p[1] for pts in lane_points for p in pts]
        if not ys:
            return None
        margen = max(20, int(frame_height * margin_ratio))
        y0 = max(0, int(min(ys)) - margen)
        y1 = min(frame_height, int(max(ys)) + margen)
        if y1 - y0 >= frame_height * 0.9:
            return None      # cubre casi todo: no vale la pena recortar
        return (y0, y1)

    def detect(
        self,
        frame: np.ndarray,
        return_annotated: bool = False
    ) -> Tuple[List[Dict], Optional[np.ndarray]]:
        """
        Detectar vehículos en un frame
        
        Args:
            frame: Frame de entrada (BGR)
            return_annotated: Si devolver frame anotado
            
        Returns:
            detections: Lista de detecciones con formato:
                {
                    'bbox': [x1, y1, x2, y2],
                    'confidence': float,
                    'class_id': int,
                    'class_name': str
                }
            annotated_frame: Frame anotado (opcional)
        """
        self.frame_count += 1

        try:
            # Si hay una banda de detección, se infiere SOLO sobre esa franja.
            # No es un ahorro de cómputo: es lo contrario. Al recortar, imgsz
            # se reparte entre muchos menos píxeles verticales, así que el
            # vehículo llega al modelo mucho más grande. Medido sobre el
            # footage real: 75 -> 112 cruces en 2 min, al mismo costo por
            # cuadro que el cuadro completo a imgsz 640.
            entrada = frame
            offset_y = 0
            if self._band is not None:
                y0, y1 = self._band
                y0 = max(0, min(y0, frame.shape[0] - 1))
                y1 = max(y0 + 1, min(y1, frame.shape[0]))
                entrada = frame[y0:y1]
                offset_y = y0

            # Realizar detección
            modelo, imgsz = self._modelo_para(entrada)
            results = modelo.predict(
                entrada,
                conf=self.confidence_threshold,
                iou=self.iou_threshold,
                imgsz=imgsz,
                agnostic_nms=self.nms_agnostico,
                verbose=False,
                device=self.device,
                **self._opciones_precision()
            )
            
            # Procesar resultados
            detections = []
            
            if len(results) > 0:
                result = results[0]
                
                # Obtener detecciones
                boxes = result.boxes
                
                for box in boxes:
                    # Obtener datos
                    xyxy = box.xyxy[0].cpu().numpy()
                    conf = float(box.conf[0].cpu().numpy())
                    cls = int(box.cls[0].cpu().numpy())
                    
                    # Filtrar solo vehículos
                    if cls in self.vehicle_classes:
                        detection = {
                            # Las cajas salen en coordenadas del recorte;
                            # se devuelven a las del cuadro completo para que
                            # el tracker, los carriles y el video anotado
                            # sigan trabajando en un solo sistema.
                            'bbox': [
                                float(xyxy[0]),
                                float(xyxy[1]) + offset_y,
                                float(xyxy[2]),
                                float(xyxy[3]) + offset_y
                            ],
                            'confidence': conf,
                            'class_id': cls,
                            'class_name': self.vehicle_classes[cls]
                        }
                        detections.append(detection)
                        self.total_detections += 1

            # Frame anotado si se solicita
            annotated_frame = None
            if return_annotated and len(results) > 0:
                annotated_frame = results[0].plot()
            
            return detections, annotated_frame
            
        except Exception as e:
            logging.error(f"Error en detección: {e}")
            return [], None
    
    def detect_batch(
        self,
        frames: List[np.ndarray]
    ) -> List[List[Dict]]:
        """
        Detectar vehículos en múltiples frames (batch processing)
        
        Args:
            frames: Lista de frames
            
        Returns:
            Lista de detecciones por frame
        """
        try:
            results = self.model.predict(
                frames,
                conf=self.confidence_threshold,
                iou=self.iou_threshold,
                imgsz=self.input_size,
                agnostic_nms=self.nms_agnostico,
                verbose=False,
                device=self.device,
                **self._opciones_precision()
            )
            
            all_detections = []
            
            for result in results:
                detections = []
                boxes = result.boxes
                
                for box in boxes:
                    xyxy = box.xyxy[0].cpu().numpy()
                    conf = float(box.conf[0].cpu().numpy())
                    cls = int(box.cls[0].cpu().numpy())
                    
                    if cls in self.vehicle_classes:
                        detection = {
                            'bbox': [
                                float(xyxy[0]),
                                float(xyxy[1]),
                                float(xyxy[2]),
                                float(xyxy[3])
                            ],
                            'confidence': conf,
                            'class_id': cls,
                            'class_name': self.vehicle_classes[cls]
                        }
                        detections.append(detection)
                
                all_detections.append(detections)
                self.frame_count += 1
            
            return all_detections
            
        except Exception as e:
            logging.error(f"Error en detección batch: {e}")
            return [[] for _ in frames]
    
    def get_statistics(self) -> Dict:
        """Obtener estadísticas del detector"""
        return {
            'total_detections': self.total_detections,
            'frames_processed': self.frame_count,
            'avg_detections_per_frame': (
                self.total_detections / max(1, self.frame_count)
            ),
            'model': self.model_path,
            'device': self.device,
            'confidence_threshold': self.confidence_threshold
        }
    
    def reset_statistics(self):
        """Reiniciar estadísticas"""
        self.total_detections = 0
        self.frame_count = 0
    
    @staticmethod
    def bbox_to_center(bbox: List[float]) -> Tuple[float, float]:
        """Convertir bbox a coordenadas del centro"""
        x1, y1, x2, y2 = bbox
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        return cx, cy
    
    @staticmethod
    def bbox_to_xywh(bbox: List[float]) -> List[float]:
        """Convertir bbox de xyxy a xywh"""
        x1, y1, x2, y2 = bbox
        w = x2 - x1
        h = y2 - y1
        return [x1, y1, w, h]
    
    @staticmethod
    def calculate_area(bbox: List[float]) -> float:
        """Calcular área de bbox"""
        x1, y1, x2, y2 = bbox
        return (x2 - x1) * (y2 - y1)
