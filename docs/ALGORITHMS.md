# Algoritmos y Matemáticas del Sistema

Este documento explica en detalle los algoritmos y cálculos matemáticos implementados en el sistema de aforo vehicular.

## Tabla de Contenidos

1. [Detección de Objetos](#detección-de-objetos)
2. [Tracking Multi-Objeto](#tracking-multi-objeto)
3. [Detección de Cruces](#detección-de-cruces)
4. [Análisis de Dirección](#análisis-de-dirección)
5. [Optimizaciones](#optimizaciones)

---

## 1. Detección de Objetos

### YOLOv8 (You Only Look Once v8)

El sistema utiliza YOLOv8 para la detección de vehículos en tiempo real.

#### Arquitectura

YOLOv8 divide la imagen en una cuadrícula y predice:
- **Bounding boxes**: Coordenadas (x, y, w, h)
- **Confianza**: Probabilidad de que sea un objeto
- **Clases**: Probabilidad de cada clase

#### Función de Pérdida

La función de pérdida combina tres componentes:

```
L_total = λ_box * L_box + λ_obj * L_obj + λ_cls * L_cls
```

Donde:
- **L_box**: Pérdida de localización (IoU loss)
- **L_obj**: Pérdida de objetividad (confidence)
- **L_cls**: Pérdida de clasificación (cross-entropy)

#### Non-Maximum Suppression (NMS)

Para eliminar detecciones duplicadas:

1. Ordenar detecciones por confianza (descendente)
2. Seleccionar la detección con mayor confianza
3. Eliminar detecciones con IoU > umbral
4. Repetir con las detecciones restantes

**IoU (Intersection over Union):**

```
IoU(A, B) = Área(A ∩ B) / Área(A ∪ B)
```

```python
def calculate_iou(box1, box2):
    # Intersección
    xi1 = max(box1[0], box2[0])
    yi1 = max(box1[1], box2[1])
    xi2 = min(box1[2], box2[2])
    yi2 = min(box1[3], box2[3])
    
    inter_area = max(0, xi2 - xi1) * max(0, yi2 - yi1)
    
    # Unión
    box1_area = (box1[2] - box1[0]) * (box1[3] - box1[1])
    box2_area = (box2[2] - box2[0]) * (box2[3] - box2[1])
    union_area = box1_area + box2_area - inter_area
    
    return inter_area / union_area if union_area > 0 else 0
```

---

## 2. Tracking Multi-Objeto

### Algoritmo DeepSORT

El sistema implementa un algoritmo tipo DeepSORT (Deep Simple Online Realtime Tracking).

#### Componentes Principales

1. **Filtro de Kalman** para predicción de estado
2. **Hungarian Algorithm** para asociación de datos
3. **Gestión del ciclo de vida** de tracks

### 2.1 Filtro de Kalman

#### Vector de Estado

El estado de un track se representa como un vector de 8 dimensiones:

```
x = [cx, cy, w, h, vx, vy, vw, vh]ᵀ
```

Donde:
- (cx, cy): Centro del bounding box
- (w, h): Ancho y alto
- (vx, vy, vw, vh): Velocidades correspondientes

#### Ecuaciones del Filtro

**1. Predicción:**

```
x̂_k|k-1 = F * x_k-1|k-1
P_k|k-1 = F * P_k-1|k-1 * Fᵀ + Q
```

**2. Actualización:**

```
K_k = P_k|k-1 * Hᵀ * (H * P_k|k-1 * Hᵀ + R)⁻¹
x_k|k = x̂_k|k-1 + K_k * (z_k - H * x̂_k|k-1)
P_k|k = (I - K_k * H) * P_k|k-1
```

Donde:
- **F**: Matriz de transición de estado
- **H**: Matriz de medición
- **Q**: Covarianza del ruido del proceso
- **R**: Covarianza del ruido de medición
- **K**: Ganancia de Kalman

#### Matriz de Transición (F)

```
F = [
    [1, 0, 0, 0, 1, 0, 0, 0],   # cx_k = cx_k-1 + vx
    [0, 1, 0, 0, 0, 1, 0, 0],   # cy_k = cy_k-1 + vy
    [0, 0, 1, 0, 0, 0, 1, 0],   # w_k = w_k-1 + vw
    [0, 0, 0, 1, 0, 0, 0, 1],   # h_k = h_k-1 + vh
    [0, 0, 0, 0, 1, 0, 0, 0],   # vx_k = vx_k-1
    [0, 0, 0, 0, 0, 1, 0, 0],   # vy_k = vy_k-1
    [0, 0, 0, 0, 0, 0, 1, 0],   # vw_k = vw_k-1
    [0, 0, 0, 0, 0, 0, 0, 1]    # vh_k = vh_k-1
]
```

#### Matriz de Medición (H)

```
H = [
    [1, 0, 0, 0, 0, 0, 0, 0],   # medimos cx
    [0, 1, 0, 0, 0, 0, 0, 0],   # medimos cy
    [0, 0, 1, 0, 0, 0, 0, 0],   # medimos w
    [0, 0, 0, 1, 0, 0, 0, 0]    # medimos h
]
```

### 2.2 Hungarian Algorithm

Para asociar detecciones con tracks existentes:

#### Matriz de Costos

```
C[i,j] = 1 - IoU(detection_i, track_j_predicted)
```

#### Algoritmo

1. Construir matriz de costos (detecciones × tracks)
2. Resolver problema de asignación óptima
3. Asignar matches con IoU > umbral
4. Marcar detecciones y tracks no asignados

**Complejidad:** O(n³) donde n = max(num_detections, num_tracks)

La implementación usa `scipy.optimize.linear_sum_assignment` que implementa el algoritmo de Munkres.

### 2.3 Gestión del Ciclo de Vida

#### Estados de un Track

1. **Tentativo**: Track recién creado (hits < min_hits)
2. **Confirmado**: Track con suficientes detecciones
3. **Eliminado**: Track perdido (miss_streak > max_age)

#### Transiciones de Estado

```
[Creación] → [Tentativo] → [Confirmado] → [Eliminado]
                ↑______________|
                    (miss)
```

---

## 3. Detección de Cruces

### 3.1 Cruce de Línea Horizontal

Para detectar si un vehículo cruzó una línea horizontal en y = L:

```python
def check_horizontal_crossing(prev_y, curr_y, line_y, tolerance):
    # Cruce de arriba hacia abajo (ENTRADA)
    if prev_y < line_y and curr_y >= line_y:
        if abs(curr_y - line_y) <= tolerance:
            return "ENTERING"
    
    # Cruce de abajo hacia arriba (SALIDA)
    if prev_y > line_y and curr_y <= line_y:
        if abs(curr_y - line_y) <= tolerance:
            return "EXITING"
    
    return None
```

### 3.2 Cruce de Línea Vertical

Similar, pero evaluando coordenadas x:

```python
def check_vertical_crossing(prev_x, curr_x, line_x, tolerance):
    # Cruce de izquierda a derecha (ENTRADA)
    if prev_x < line_x and curr_x >= line_x:
        if abs(curr_x - line_x) <= tolerance:
            return "ENTERING"
    
    # Cruce de derecha a izquierda (SALIDA)
    if prev_x > line_x and curr_x <= line_x:
        if abs(curr_x - line_x) <= tolerance:
            return "EXITING"
    
    return None
```

### 3.3 Cruce de Línea Diagonal/Arbitraria

#### Intersección de Segmentos

Para detectar si dos segmentos se intersectan:

```python
def segments_intersect(p1, p2, p3, p4):
    """
    Verifica si el segmento (p1, p2) intersecta con (p3, p4)
    Usando orientación relativa de puntos
    """
    def ccw(A, B, C):
        # Producto cruzado para determinar orientación
        return (C[1] - A[1]) * (B[0] - A[0]) > (B[1] - A[1]) * (C[0] - A[0])
    
    return ccw(p1, p3, p4) != ccw(p2, p3, p4) and \
           ccw(p1, p2, p3) != ccw(p1, p2, p4)
```

#### Dirección de Cruce

Usando el producto cruzado:

```
cross = (curr - prev) × (line_end - line_start)
```

```python
def calculate_crossing_direction(prev_pos, curr_pos, line_p1, line_p2):
    # Vector de movimiento
    dx = curr_pos[0] - prev_pos[0]
    dy = curr_pos[1] - prev_pos[1]
    
    # Vector de la línea
    lx = line_p2[0] - line_p1[0]
    ly = line_p2[1] - line_p1[1]
    
    # Producto cruzado
    cross = dx * ly - dy * lx
    
    if cross > 0:
        return "ENTERING"
    elif cross < 0:
        return "EXITING"
    else:
        return "UNKNOWN"
```

**Interpretación Geométrica:**

- cross > 0: Movimiento en sentido antihorario respecto a la línea
- cross < 0: Movimiento en sentido horario
- cross = 0: Movimiento paralelo a la línea

---

## 4. Análisis de Dirección

### 4.1 Cálculo de Velocidad

Velocidad instantánea (pixels/frame):

```python
def calculate_velocity(trajectory):
    if len(trajectory) < 2:
        return None
    
    p1 = trajectory[-2]
    p2 = trajectory[-1]
    
    vx = p2[0] - p1[0]
    vy = p2[1] - p1[1]
    
    speed = sqrt(vx² + vy²)
    
    return (vx, vy, speed)
```

### 4.2 Ángulo de Dirección

```python
def calculate_direction_angle(velocity):
    vx, vy = velocity
    angle = arctan2(vy, vx) * 180 / π
    return angle
```

Rangos de ángulos:
- 0°: Derecha
- 90°: Abajo
- 180° / -180°: Izquierda
- -90°: Arriba

### 4.3 Suavizado de Trayectoria

Para reducir ruido en las trayectorias, se puede aplicar un filtro de media móvil:

```python
def smooth_trajectory(trajectory, window_size=5):
    if len(trajectory) < window_size:
        return trajectory
    
    smoothed = []
    for i in range(len(trajectory)):
        start = max(0, i - window_size // 2)
        end = min(len(trajectory), i + window_size // 2 + 1)
        
        window = trajectory[start:end]
        avg_x = sum(p[0] for p in window) / len(window)
        avg_y = sum(p[1] for p in window) / len(window)
        
        smoothed.append((avg_x, avg_y))
    
    return smoothed
```

---

## 5. Optimizaciones

### 5.1 TensorRT

TensorRT optimiza modelos de deep learning para inferencia:

1. **Fusion de capas**: Combina operaciones consecutivas
2. **Reducción de precisión**: FP32 → FP16 o INT8
3. **Optimización de kernels**: Kernels CUDA especializados

**Ganancia esperada:** 2-4x en Jetson Nano

### 5.2 Half Precision (FP16)

Reduce uso de memoria y aumenta velocidad:

- Memoria: 50% menos
- Velocidad: ~2x en GPUs con Tensor Cores
- Precisión: Suficiente para detección de objetos

### 5.3 Skip Frames

Procesar solo 1 de cada N frames:

```python
if frame_count % (skip_frames + 1) == 0:
    detections = detector.detect(frame)
else:
    # Usar predicción del Kalman Filter
    detections = []
```

**Trade-off:**
- skip_frames = 0: Máxima precisión, menor FPS
- skip_frames = 2: ~3x FPS, buena precisión con Kalman Filter

### 5.4 Reducción de Resolución

Redimensionar entrada antes de detección:

```python
# Original: 1920x1080
# Reducido: 960x540 (4x menos pixels)

scale = target_width / original_width
resized = cv2.resize(frame, (target_width, target_height))
```

**Impacto:**
- Velocidad: ~4x más rápido
- Precisión: -5-10% en objetos pequeños

### 5.5 Optimización de Memoria

```python
# Liberar memoria GPU periódicamente
if frame_count % 100 == 0:
    torch.cuda.empty_cache()
    gc.collect()
```

---

## Complejidad Computacional

### Por Frame

| Componente | Complejidad | Tiempo (ms) @ 640x640 |
|------------|-------------|----------------------|
| Detección (YOLOv8n) | O(1) | ~30-50 |
| Tracking (Hungarian) | O(n³) | ~1-5 |
| Conteo | O(n) | <1 |
| Visualización | O(n) | ~5-10 |

Donde n = número de tracks activos (típicamente 5-20)

**FPS esperado:**
- PC con GPU: 25-40 FPS
- Jetson Nano (optimizado): 10-15 FPS
- CPU only: 2-5 FPS

---

## Referencias

1. **YOLOv8**: Ultralytics YOLOv8 Documentation
2. **DeepSORT**: "Simple Online and Realtime Tracking with a Deep Association Metric"
3. **Kalman Filter**: Welch & Bishop, "An Introduction to the Kalman Filter"
4. **Hungarian Algorithm**: Kuhn, "The Hungarian Method for Assignment Problems"
5. **TensorRT**: NVIDIA TensorRT Documentation

---

**Nota**: Este documento describe los algoritmos implementados en el sistema. Para detalles de implementación, consultar el código fuente en `src/`.
