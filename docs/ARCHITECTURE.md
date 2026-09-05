# Arquitectura del Sistema

Este documento describe la arquitectura completa del sistema de aforo vehicular bidireccional.

## Vista General

```
┌─────────────────────────────────────────────────────────────┐
│                    VIDEO DE ENTRADA                          │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                  DETECTOR (YOLO)                             │
│  • Detección de vehículos frame por frame                   │
│  • Bounding boxes + clases + confianza                      │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                  TRACKER (DeepSORT)                          │
│  • Asociación de detecciones a tracks                       │
│  • Filtro de Kalman para predicción                         │
│  • Hungarian Algorithm para matching                        │
│  • Gestión de ciclo de vida de tracks                       │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│              CONTADOR BIDIRECCIONAL                          │
│  • Detección de cruce de línea                              │
│  • Análisis de dirección de movimiento                      │
│  • Conteo por tipo de vehículo                              │
│  • Prevención de duplicados                                 │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                  VISUALIZADOR                                │
│  • Dibuja detecciones y tracks                              │
│  • Muestra línea de conteo                                  │
│  • Panel de estadísticas                                    │
│  • Trayectorias de vehículos                                │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                  REPORTER                                    │
│  • Exportación de datos (JSON, CSV)                         │
│  • Generación de gráficas                                   │
│  • Reportes estadísticos                                    │
│  • Mapas de calor                                           │
└─────────────────────────────────────────────────────────────┘
```

## Componentes Principales

### 1. VehicleDetector

**Ubicación:** `src/detector.py`

**Responsabilidades:**
- Cargar modelo YOLO
- Detectar vehículos en frames
- Filtrar por clases vehiculares
- Aplicar NMS para eliminar duplicados
- Soporte para TensorRT y FP16

**Entrada:**
- Frame BGR (numpy array)

**Salida:**
```python
[
    {
        'bbox': [x1, y1, x2, y2],
        'confidence': 0.85,
        'class_id': 2,
        'class_name': 'car'
    },
    ...
]
```

**Configuración:**
```yaml
detector:
  model_path: "models/yolov8s.pt"
  confidence_threshold: 0.4
  iou_threshold: 0.5
  input_size: 640
```

### 2. VehicleTracker

**Ubicación:** `src/tracker.py`

**Responsabilidades:**
- Mantener identidad de vehículos entre frames
- Predecir posiciones futuras (Kalman Filter)
- Asociar detecciones con tracks existentes
- Gestionar trayectorias
- Eliminar tracks perdidos

**Algoritmos:**
- Filtro de Kalman (8D state: x, y, w, h, vx, vy, vw, vh)
- Hungarian Algorithm para asociación
- IoU para similaridad

**Estado de Track:**
```python
{
    'id': 42,
    'bbox': [x1, y1, x2, y2],
    'class_name': 'car',
    'confidence': 0.87,
    'trajectory': [(x1,y1), (x2,y2), ...],
    'velocity': (vx, vy),
    'age': 25,
    'hits': 18
}
```

**Ciclo de Vida:**
1. **Creación**: Nueva detección sin match
2. **Tentativo**: hits < min_hits
3. **Confirmado**: hits >= min_hits
4. **Eliminado**: miss_streak > max_age

### 3. BidirectionalCounter

**Ubicación:** `src/counter.py`

**Responsabilidades:**
- Definir línea de conteo
- Detectar cruces de línea
- Determinar dirección de cruce
- Prevenir conteos duplicados
- Estadísticas por tipo de vehículo

**Tipos de Línea:**
- Horizontal: y = constante
- Vertical: x = constante
- Diagonal: 2 puntos
- Polígono: N puntos

**Detección de Cruce:**
```python
# Para línea horizontal
if prev_y < line_y and curr_y >= line_y:
    direction = "ENTERING"
elif prev_y > line_y and curr_y <= line_y:
    direction = "EXITING"
```

**Salida:**
```python
{
    'in': 125,
    'out': 118,
    'total': 243,
    'net_flow': 7
}
```

### 4. Visualizer

**Ubicación:** `src/visualizer.py`

**Responsabilidades:**
- Dibujar bounding boxes
- Mostrar IDs de tracks
- Visualizar trayectorias
- Dibujar línea de conteo
- Panel de estadísticas
- Mapas de calor

**Paleta de Colores:**
- Car: Verde
- Motorcycle: Azul
- Bus: Naranja
- Truck: Rojo

### 5. VideoProcessor

**Ubicación:** `src/video_processor.py`

**Responsabilidades:**
- Orquestar pipeline completo
- Gestionar skip_frames
- Coordinar componentes
- Recopilar datos por frame

**Pipeline por Frame:**
```
Frame → Detect → Track → Count → Visualize → Output
```

### 6. Reporter

**Ubicación:** `src/reporter.py`

**Responsabilidades:**
- Exportar conteos (JSON, CSV)
- Guardar trayectorias
- Generar gráficas (matplotlib)
- Crear reportes de texto
- Mapas de calor de tráfico

**Archivos Generados:**
- `counts.json`: Conteos detallados
- `trajectory_data.json`: Trayectorias completas
- `statistics.csv`: Estadísticas agregadas
- `counts_by_type.png`: Gráfica de barras
- `direction_distribution.png`: Gráfica de pie
- `summary_report.txt`: Reporte de texto

## Flujo de Datos

### Procesamiento de un Frame

```python
# 1. Leer frame
frame = video.read()

# 2. Detectar vehículos
detections = detector.detect(frame)
# [{bbox, class, conf}, ...]

# 3. Actualizar tracker
tracks = tracker.update(detections)
# [{id, bbox, trajectory, ...}, ...]

# 4. Detectar cruces
crossings = counter.update(tracks)
# {'in': [...], 'out': [...]}

# 5. Visualizar
output = visualizer.create_visualization(
    frame, tracks, counting_line, counts
)

# 6. Guardar/Mostrar
video_writer.write(output)
cv2.imshow('Result', output)
```

### Estado Global

```python
System State:
├── detector
│   ├── model (YOLO)
│   └── statistics
│       ├── total_detections
│       └── frames_processed
├── tracker
│   ├── active_tracks: List[Track]
│   ├── deleted_tracks: List[Track]
│   └── track_id_counter
├── counter
│   ├── count_in
│   ├── count_out
│   ├── counts_by_type
│   ├── counted_ids: Set[int]
│   └── crossing_history
└── visualizer
    └── configuration
```

## Optimizaciones

### Para Jetson Nano

1. **TensorRT**
   - Conversión de modelo PyTorch → TensorRT
   - FP16 precision
   - ~3x speedup

2. **Skip Frames**
   - Procesar 1 de cada N frames
   - Usar predicción de Kalman entre frames
   - 2-3x speedup con mínima pérdida de precisión

3. **Reducción de Resolución**
   - 1920x1080 → 960x540
   - ~4x speedup
   - Aceptable para vehículos medianos/grandes

4. **Batch Processing**
   - Acumular frames y procesar en batch
   - Mejor utilización de GPU
   - Trade-off con latencia

### Gestión de Memoria

```python
# Limpieza periódica
if frame_count % 100 == 0:
    torch.cuda.empty_cache()
    gc.collect()

# Limitar buffer de trayectorias
trajectory = deque(maxlen=60)

# Eliminar tracks viejos
if track.miss_streak > max_age:
    delete_track(track)
```

## Configuración

### Estructura de Config

```yaml
detector:
  # Configuración de detección
  
tracker:
  # Configuración de tracking
  
counter:
  # Configuración de conteo
  
visualizer:
  # Configuración de visualización
  
jetson_nano:
  # Optimizaciones específicas
```

### Perfiles de Configuración

1. **default_config.yaml**
   - Balance entre precisión y velocidad
   - Para PC con GPU

2. **jetson_optimized.yaml**
   - Máximo rendimiento en Jetson Nano
   - FP16, skip_frames, resolución reducida

## Extensibilidad

### Agregar Nuevas Clases

```python
# En detector.py
VEHICLE_CLASSES = {
    2: 'car',
    3: 'motorcycle',
    5: 'bus',
    7: 'truck',
    # Agregar más clases COCO aquí
}
```

### Nuevos Tipos de Línea

```python
# En counter.py
class LineType(Enum):
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"
    DIAGONAL = "diagonal"
    POLYGON = "polygon"
    # Agregar nuevo tipo aquí
```

### Análisis Personalizado

```python
# Heredar de Reporter
class CustomReporter(Reporter):
    def generate_custom_analysis(self, data):
        # Análisis personalizado
        pass
```

## Testing

### Unit Tests

```bash
# Detector
pytest tests/test_detector.py

# Tracker
pytest tests/test_tracker.py

# Counter
pytest tests/test_counter.py
```

### Integration Test

```bash
# Sistema completo
python test_system.py
```

## Deployment

### Jetson Nano

```bash
# 1. Configurar Jetson
sudo nvpmodel -m 0
sudo jetson_clocks

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Optimizar modelo
python optimize_model.py --model models/yolov8s.pt --jetson

# 4. Ejecutar con config optimizada
python main.py \
    --video input/video.mp4 \
    --config configs/jetson_optimized.yaml \
    --use-tensorrt
```

### PC con GPU

```bash
# Ejecutar con configuración por defecto
python main.py \
    --video input/video.mp4 \
    --save-video \
    --display
```

## Monitoreo

### Métricas de Rendimiento

```python
# En tiempo real
stats = {
    'fps': calculate_fps(),
    'active_tracks': len(tracker.tracks),
    'gpu_memory': get_gpu_memory_usage(),
    'processing_time': time.time() - start_time
}
```

### Logging

```python
# Niveles de log
logging.DEBUG    # Información detallada
logging.INFO     # Información general
logging.WARNING  # Advertencias
logging.ERROR    # Errores
```

## Troubleshooting

### Problema: Bajo FPS

**Diagnóstico:**
```python
# Medir tiempo por componente
t1 = time.time()
detections = detector.detect(frame)
t_detect = time.time() - t1

t2 = time.time()
tracks = tracker.update(detections)
t_track = time.time() - t2
```

**Soluciones:**
- Reducir input_size
- Habilitar skip_frames
- Usar TensorRT
- Reducir resolución de video

### Problema: Precisión Baja

**Diagnóstico:**
- Comparar con conteo manual
- Revisar logs de cruces

**Soluciones:**
- Reducir confidence_threshold
- Ajustar posición de línea
- Aumentar min_hits del tracker
- Ajustar crossing_tolerance

## Referencias

- [YOLOv8 Documentation](https://docs.ultralytics.com/)
- [DeepSORT Paper](https://arxiv.org/abs/1703.07402)
- [Kalman Filter Tutorial](https://www.kalmanfilter.net/)
- [TensorRT Documentation](https://docs.nvidia.com/deeplearning/tensorrt/)

---

**Última actualización:** Febrero 2026  
**Versión:** 1.0.0
