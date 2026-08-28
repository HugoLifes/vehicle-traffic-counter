# Guía de Calibración de Cámara

Esta guía explica cómo calibrar el sistema para diferentes perspectivas de cámara y obtener conteos precisos.

## Tabla de Contenidos

1. [Tipos de Perspectiva](#tipos-de-perspectiva)
2. [Calibración Básica](#calibración-básica)
3. [Transformación de Perspectiva](#transformación-de-perspectiva)
4. [Estimación de Velocidad](#estimación-de-velocidad)
5. [Mejores Prácticas](#mejores-prácticas)

---

## 1. Tipos de Perspectiva

### 1.1 Vista Cenital (Top-Down)

**Características:**
- Cámara perpendicular al suelo
- Sin distorsión de perspectiva
- Ideal para conteo preciso
- Fácil medición de distancias

**Configuración:**

```yaml
perspective:
  type: "top_down"
  
counter:
  line_type: "horizontal"  # O vertical
  line_position: 540  # Centro del frame
```

**Ventajas:**
✅ Máxima precisión  
✅ Sin corrección de perspectiva necesaria  
✅ Fácil calibración

**Desventajas:**
❌ Requiere instalación específica  
❌ Costosa de implementar  
❌ Campo de visión limitado

### 1.2 Vista Frontal

**Características:**
- Cámara a nivel del tráfico
- Distorsión de perspectiva moderada
- Más común en instalaciones reales

**Configuración:**

```yaml
perspective:
  type: "frontal"
  correction:
    enabled: true
    angle_compensation: 15  # grados
```

**Consideraciones:**
- Vehículos lejanos aparecen más pequeños
- Necesita línea de conteo en punto de referencia
- Posible oclusión entre vehículos

### 1.3 Vista Angular

**Características:**
- Cámara en ángulo respecto al tráfico
- Mayor distorsión de perspectiva
- Requiere calibración avanzada

**Configuración:**

```yaml
perspective:
  type: "angular"
  correction:
    enabled: true
  calibration:
    enabled: true
    matrix_file: "configs/camera_matrix.yaml"
```

---

## 2. Calibración Básica

### 2.1 Posicionamiento de Línea de Conteo

#### Método Visual

1. Ejecutar el sistema con un video de prueba
2. Pausar en un frame representativo
3. Identificar punto de conteo óptimo

```python
python main.py --video input/test.mp4 --display
# Pausar y observar
```

4. Medir coordenadas Y (horizontal) o X (vertical)

```python
# Obtener coordenadas de mouse
import cv2

def mouse_callback(event, x, y, flags, param):
    if event == cv2.EVENT_LBUTTONDOWN:
        print(f"Coordenadas: x={x}, y={y}")

cv2.setMouseCallback('window', mouse_callback)
```

5. Configurar en el sistema:

```bash
python main.py --video input/test.mp4 --line-y 450
```

#### Método Automático

El sistema puede calcular automáticamente:

```python
# En el código
counter.set_counting_line(
    line_type='horizontal',
    y=frame_height // 2,  # Centro automático
    frame_shape=(frame_height, frame_width)
)
```

### 2.2 Tolerancia de Cruce

Ajustar la tolerancia según:
- Velocidad de vehículos
- FPS del video
- Calidad de tracking

**Cálculo de tolerancia:**

```
Tolerancia (pixels) = Velocidad_promedio (pixels/frame) * Factor_seguridad
```

**Ejemplo:**
```python
# Vehículos a ~50 km/h, 30 FPS
# Movimiento: ~15 pixels/frame
crossing_tolerance = 15 * 1.5  # = 22 pixels
```

**Configuración:**

```yaml
counter:
  crossing_tolerance: 22
```

---

## 3. Transformación de Perspectiva

### 3.1 ¿Cuándo Usar?

Usar transformación de perspectiva cuando:
- Vista angular significativa
- Necesitas mediciones precisas
- Estimación de velocidad requerida

### 3.2 Calibración de Matriz

#### Paso 1: Identificar Puntos de Referencia

Necesitas 4 puntos que formen un rectángulo en el mundo real:

```python
# Ejemplo: área rectangular en el suelo
source_points = [
    [120, 200],   # Esquina superior izquierda
    [1800, 150],  # Esquina superior derecha
    [1900, 900],  # Esquina inferior derecha
    [20, 950]     # Esquina inferior izquierda
]
```

#### Paso 2: Definir Puntos Objetivo

Proyección deseada (vista "cenital"):

```python
target_points = [
    [0, 0],
    [1920, 0],
    [1920, 1080],
    [0, 1080]
]
```

#### Paso 3: Calcular Matriz de Transformación

```python
import cv2
import numpy as np

# Calcular matriz de perspectiva
src = np.float32(source_points)
dst = np.float32(target_points)
M = cv2.getPerspectiveTransform(src, dst)

# Guardar matriz
np.save('configs/perspective_matrix.npy', M)
```

#### Paso 4: Aplicar Transformación

```python
# En el procesamiento
warped = cv2.warpPerspective(frame, M, (width, height))

# Procesar frame transformado
detections = detector.detect(warped)
```

### 3.3 Script de Calibración

Crear `calibrate_camera.py`:

```python
#!/usr/bin/env python3
import cv2
import numpy as np

def calibrate_perspective():
    # Cargar frame de referencia
    video = cv2.VideoCapture('input/video.mp4')
    ret, frame = video.read()
    
    points = []
    
    def mouse_callback(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            points.append([x, y])
            cv2.circle(frame, (x, y), 5, (0, 255, 0), -1)
            cv2.imshow('Calibration', frame)
    
    cv2.namedWindow('Calibration')
    cv2.setMouseCallback('Calibration', mouse_callback)
    
    print("Selecciona 4 puntos que formen un rectángulo:")
    print("1. Superior izquierdo")
    print("2. Superior derecho")
    print("3. Inferior derecho")
    print("4. Inferior izquierdo")
    
    cv2.imshow('Calibration', frame)
    cv2.waitKey(0)
    
    if len(points) == 4:
        # Calcular matriz
        src = np.float32(points)
        dst = np.float32([
            [0, 0],
            [1920, 0],
            [1920, 1080],
            [0, 1080]
        ])
        
        M = cv2.getPerspectiveTransform(src, dst)
        np.save('configs/perspective_matrix.npy', M)
        
        print("Matriz guardada exitosamente!")
        print(f"Puntos: {points}")
    
    cv2.destroyAllWindows()

if __name__ == '__main__':
    calibrate_perspective()
```

---

## 4. Estimación de Velocidad

### 4.1 Calibración de Escala

Para estimar velocidad real, necesitas calibrar pixels → metros.

#### Método 1: Objeto de Referencia

1. Medir longitud conocida en el video (ej: línea vial = 3m)
2. Contar pixels correspondientes

```python
# Ejemplo: 3 metros = 150 pixels
pixels_per_meter = 150 / 3  # = 50 pixels/metro
```

#### Método 2: Análisis de Múltiples Puntos

```python
def calibrate_scale():
    measurements = [
        (120, 3.0),  # 120 pixels = 3 metros
        (200, 5.0),  # 200 pixels = 5 metros
        (160, 4.0),  # 160 pixels = 4 metros
    ]
    
    # Promedio
    ratios = [pixels / meters for pixels, meters in measurements]
    pixels_per_meter = sum(ratios) / len(ratios)
    
    return pixels_per_meter
```

### 4.2 Cálculo de Velocidad

```python
def calculate_speed(trajectory, fps, pixels_per_meter):
    """
    Calcular velocidad promedio en km/h
    
    Args:
        trajectory: Lista de puntos (x, y)
        fps: Frames por segundo del video
        pixels_per_meter: Factor de calibración
    """
    if len(trajectory) < 2:
        return 0.0
    
    # Distancia total en pixels
    total_distance_pixels = 0
    for i in range(1, len(trajectory)):
        p1 = trajectory[i-1]
        p2 = trajectory[i]
        dist = np.sqrt((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)
        total_distance_pixels += dist
    
    # Convertir a metros
    total_distance_meters = total_distance_pixels / pixels_per_meter
    
    # Tiempo en segundos
    time_seconds = len(trajectory) / fps
    
    # Velocidad en m/s
    speed_ms = total_distance_meters / time_seconds
    
    # Convertir a km/h
    speed_kmh = speed_ms * 3.6
    
    return speed_kmh
```

### 4.3 Configuración

```yaml
advanced:
  speed_estimation:
    enabled: true
    pixels_per_meter: 50.0
    fps: 30
```

---

## 5. Mejores Prácticas

### 5.1 Posicionamiento de Cámara

✅ **Hacer:**
- Instalar cámara estable (sin vibración)
- Cubrir área de interés completa
- Evitar contra-luz
- Altura suficiente para ver todo el tráfico

❌ **Evitar:**
- Ángulos extremos (>45°)
- Obstrucciones en el campo de visión
- Cambios de iluminación bruscos
- Sombras proyectadas sobre línea de conteo

### 5.2 Configuración de Línea

✅ **Hacer:**
- Colocar línea perpendicular al flujo
- Usar punto con buena visibilidad
- Verificar con video de prueba
- Ajustar tolerancia según velocidad

❌ **Evitar:**
- Líneas en zonas con oclusión
- Líneas muy cerca del borde del frame
- Múltiples líneas muy juntas
- Líneas en áreas de sombra variable

### 5.3 Validación

#### Test de Conteo Manual

```python
# Contar manualmente 100 vehículos en el video
# Comparar con sistema

manual_count = 100
system_count = counter.get_counts()['total']

accuracy = (system_count / manual_count) * 100
print(f"Precisión: {accuracy:.1f}%")
```

**Precisión esperada:**
- Vista cenital: 95-99%
- Vista frontal: 90-95%
- Vista angular: 85-92%

#### Validación Continua

```python
# Verificar en diferentes condiciones:
# - Diferentes horas del día
# - Diferentes densidades de tráfico
# - Diferentes condiciones climáticas
```

### 5.4 Mantenimiento

**Revisión Periódica:**
1. Verificar posición de cámara (cada semana)
2. Limpiar lente (cada mes)
3. Recalibrar si es necesario (cada 3 meses)
4. Actualizar modelos (cada 6 meses)

---

## Troubleshooting

### Problema: Conteos muy bajos

**Posibles causas:**
- Umbral de confianza muy alto
- Línea mal posicionada
- Tracking perdiendo vehículos

**Solución:**
```bash
# Reducir umbral de confianza
python main.py --confidence 0.3

# Ajustar línea
python main.py --line-y <nueva_posicion>

# Aumentar max_age del tracker
# (editar config)
```

### Problema: Conteos duplicados

**Posibles causas:**
- Tolerancia de cruce muy alta
- Tracks fragmentados
- Línea en zona inestable

**Solución:**
```yaml
counter:
  crossing_tolerance: 10  # Reducir
  min_trajectory_points: 5  # Aumentar

tracker:
  min_hits: 4  # Aumentar para confirmar tracks
```

### Problema: No detecta vehículos pequeños/lejanos

**Posibles causas:**
- Resolución muy baja
- Modelo muy pequeño
- Perspectiva extrema

**Solución:**
```bash
# Usar modelo más grande
python main.py --model models/yolov8m.pt

# Mayor resolución de entrada
python main.py --input-size 1280

# Aplicar transformación de perspectiva
# (ver sección 3)
```

---

## Scripts de Utilidad

### calibrate_camera.py

```bash
python calibrate_camera.py --video input/video.mp4
```

### test_line_position.py

```bash
python test_line_position.py --video input/video.mp4 --line-y 500
```

### validate_accuracy.py

```bash
python validate_accuracy.py \
    --video input/video.mp4 \
    --ground-truth ground_truth.json
```

---

## Referencias Adicionales

1. [OpenCV Camera Calibration](https://docs.opencv.org/4.x/dc/dbb/tutorial_py_calibration.html)
2. [Perspective Transform Tutorial](https://docs.opencv.org/4.x/da/d6e/tutorial_py_geometric_transformations.html)
3. [Traffic Camera Best Practices (ITE)](https://www.ite.org/)

---

**Nota**: Para asistencia adicional con calibración, consultar `docs/SUPPORT.md` o abrir un issue en GitHub.
