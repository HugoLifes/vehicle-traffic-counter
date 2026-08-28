# Análisis de Múltiples Perspectivas de Cámara

Este documento explica cómo manejar diferentes perspectivas de cámara y los desafíos matemáticos asociados.

## Tabla de Contenidos

1. [Tipos de Perspectiva](#tipos-de-perspectiva)
2. [Matemáticas de Transformación](#matemáticas-de-transformación)
3. [Calibración Avanzada](#calibración-avanzada)
4. [Casos de Uso](#casos-de-uso)
5. [Implementación](#implementación)

---

## 1. Tipos de Perspectiva

### 1.1 Vista Cenital (Bird's Eye View)

**Características:**
- Cámara perpendicular al suelo (90°)
- Sin distorsión de perspectiva
- Objetos mantienen su tamaño relativo

**Ventajas:**
- ✅ Mediciones directas y precisas
- ✅ Velocidad real calculable fácilmente
- ✅ Sin oclusiones
- ✅ Tracking más robusto

**Desventajas:**
- ❌ Instalación costosa (drones, postes altos)
- ❌ Campo de visión limitado
- ❌ Requiere altura considerable

**Ecuaciones:**

Para vista cenital pura:
```
x_real = x_pixel / scale_x
y_real = y_pixel / scale_y

donde scale_x, scale_y = pixels_per_meter
```

**Configuración:**
```yaml
perspective:
  type: "top_down"
  scale:
    x: 50.0  # pixels por metro
    y: 50.0
```

### 1.2 Vista Frontal (Frontal View)

**Características:**
- Cámara al nivel del tráfico
- Ángulo de elevación: 0° - 30°
- Distorsión de perspectiva moderada

**Ventajas:**
- ✅ Instalación más simple
- ✅ Costos menores
- ✅ Buena identificación de vehículos

**Desventajas:**
- ❌ Objetos lejanos más pequeños
- ❌ Posible oclusión
- ❌ Velocidad difícil de estimar

**Geometría:**

```
Distancia aparente ≠ Distancia real

d_aparente = d_real * cos(θ)

donde θ = ángulo con respecto a la cámara
```

**Compensación de Perspectiva:**

```python
def compensate_frontal_perspective(bbox, y_position, frame_height):
    """
    Compensar tamaño de bbox según distancia
    
    Objetos más lejanos (y menor) aparecen más pequeños
    """
    # Factor de escala basado en posición vertical
    scale_factor = 1.0 + (frame_height - y_position) / frame_height
    
    # Ajustar dimensiones
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    w_compensated = w * scale_factor
    h_compensated = h * scale_factor
    
    return w_compensated, h_compensated
```

### 1.3 Vista Angular (Angled View)

**Características:**
- Ángulo de inclinación: 30° - 60°
- Ángulo lateral variable
- Distorsión significativa

**Ventajas:**
- ✅ Mayor cobertura de área
- ✅ Múltiples carriles visibles
- ✅ Instalación flexible

**Desventajas:**
- ❌ Requiere corrección de perspectiva
- ❌ Mediciones complejas
- ❌ Tracking más difícil

**Transformación de Perspectiva:**

Para corregir vista angular, usamos transformación homográfica.

```
[x']     [h11  h12  h13]   [x]
[y'] =   [h21  h22  h23] × [y]
[1 ]     [h31  h32  1  ]   [1]

x' = (h11*x + h12*y + h13) / (h31*x + h32*y + 1)
y' = (h21*x + h22*y + h23) / (h31*x + h32*y + 1)
```

La matriz H (3×3) se calcula con puntos de correspondencia conocidos.

### 1.4 Vista Lateral (Side View)

**Características:**
- Cámara perpendicular al flujo de tráfico
- Buena para medir longitud de vehículos
- Difícil para conteo bidireccional

**Ventajas:**
- ✅ Perfil completo de vehículos
- ✅ Clasificación más precisa
- ✅ Medición de longitud

**Desventajas:**
- ❌ Solo un carril por cámara
- ❌ Velocidad difícil de medir
- ❌ Requiere múltiples cámaras

---

## 2. Matemáticas de Transformación

### 2.1 Transformación Homográfica

La homografía es una transformación que mapea un plano a otro.

#### Calcular Matriz de Homografía

Dados 4 pares de puntos correspondientes:

```python
import cv2
import numpy as np

# Puntos en imagen original (perspectiva)
src_points = np.float32([
    [x1, y1],  # Punto 1
    [x2, y2],  # Punto 2
    [x3, y3],  # Punto 3
    [x4, y4]   # Punto 4
])

# Puntos en imagen destino (cenital)
dst_points = np.float32([
    [0, 0],
    [width, 0],
    [width, height],
    [0, height]
])

# Calcular homografía
H = cv2.getPerspectiveTransform(src_points, dst_points)
```

#### Aplicar Transformación

```python
# Transformar frame completo
warped = cv2.warpPerspective(frame, H, (width, height))

# Transformar punto individual
point = np.array([[x, y]], dtype='float32')
point_reshaped = point.reshape(-1, 1, 2)
transformed = cv2.perspectiveTransform(point_reshaped, H)
x_new, y_new = transformed[0][0]
```

### 2.2 Corrección de Distorsión de Lente

Las cámaras reales tienen distorsión de lente (especialmente gran angular).

#### Modelo de Distorsión

```
x_distorted = x * (1 + k1*r² + k2*r⁴ + k3*r⁶)
y_distorted = y * (1 + k1*r² + k2*r⁴ + k3*r⁶)

donde:
- k1, k2, k3 = coeficientes de distorsión radial
- r² = x² + y²
```

#### Calibración de Cámara

```python
import cv2
import numpy as np

def calibrate_camera(images, pattern_size):
    """
    Calibrar cámara usando patrón de tablero de ajedrez
    
    Args:
        images: Lista de imágenes del patrón
        pattern_size: Tamaño del patrón (filas, columnas)
    
    Returns:
        camera_matrix, dist_coeffs
    """
    # Preparar puntos del patrón
    objp = np.zeros((pattern_size[0] * pattern_size[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:pattern_size[0], 0:pattern_size[1]].T.reshape(-1, 2)
    
    objpoints = []  # Puntos 3D
    imgpoints = []  # Puntos 2D
    
    for img in images:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Encontrar esquinas
        ret, corners = cv2.findChessboardCorners(gray, pattern_size, None)
        
        if ret:
            objpoints.append(objp)
            imgpoints.append(corners)
    
    # Calibrar
    ret, camera_matrix, dist_coeffs, rvecs, tvecs = cv2.calibrateCamera(
        objpoints, imgpoints, gray.shape[::-1], None, None
    )
    
    return camera_matrix, dist_coeffs

# Usar calibración para corregir distorsión
undistorted = cv2.undistort(frame, camera_matrix, dist_coeffs)
```

### 2.3 Estimación de Pose de Cámara

Para conocer la posición y orientación exacta de la cámara:

```python
def estimate_camera_pose(image_points, world_points, camera_matrix, dist_coeffs):
    """
    Estimar pose de cámara (posición y rotación)
    
    Args:
        image_points: Puntos en la imagen
        world_points: Puntos correspondientes en mundo real
        camera_matrix: Matriz intrínseca de cámara
        dist_coeffs: Coeficientes de distorsión
    
    Returns:
        rvec: Vector de rotación
        tvec: Vector de traslación
    """
    success, rvec, tvec = cv2.solvePnP(
        world_points,
        image_points,
        camera_matrix,
        dist_coeffs
    )
    
    # Convertir rotación a matriz
    rotation_matrix, _ = cv2.Rodrigues(rvec)
    
    return rotation_matrix, tvec
```

---

## 3. Calibración Avanzada

### 3.1 Calibración Semi-Automática

```python
class PerspectiveCalibrator:
    """
    Calibrador interactivo de perspectiva
    """
    
    def __init__(self, frame):
        self.frame = frame.copy()
        self.points = []
        
    def select_points(self):
        """Seleccionar 4 puntos interactivamente"""
        cv2.namedWindow('Calibration')
        cv2.setMouseCallback('Calibration', self._mouse_callback)
        
        while len(self.points) < 4:
            img_display = self.frame.copy()
            
            # Dibujar puntos seleccionados
            for i, pt in enumerate(self.points):
                cv2.circle(img_display, tuple(pt), 5, (0, 255, 0), -1)
                cv2.putText(img_display, str(i+1), tuple(pt), 
                           cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
            
            cv2.imshow('Calibration', img_display)
            cv2.waitKey(1)
        
        cv2.destroyAllWindows()
        return self.points
    
    def _mouse_callback(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            if len(self.points) < 4:
                self.points.append([x, y])
    
    def compute_homography(self, real_width, real_height):
        """
        Calcular homografía dado dimensiones reales
        
        Args:
            real_width: Ancho real del área (metros)
            real_height: Alto real del área (metros)
        """
        src = np.float32(self.points)
        dst = np.float32([
            [0, 0],
            [real_width * 100, 0],  # Convertir a pixels (escala 100:1)
            [real_width * 100, real_height * 100],
            [0, real_height * 100]
        ])
        
        H = cv2.getPerspectiveTransform(src, dst)
        return H, (real_width * 100, real_height * 100)

# Uso
calibrator = PerspectiveCalibrator(first_frame)
points = calibrator.select_points()
H, size = calibrator.compute_homography(real_width=10, real_height=20)
```

### 3.2 Calibración con Puntos de Referencia

```python
def calibrate_with_known_distance(frame, known_distance_meters):
    """
    Calibrar escala usando distancia conocida
    
    Args:
        frame: Frame de referencia
        known_distance_meters: Distancia real en metros
    
    Returns:
        pixels_per_meter: Factor de conversión
    """
    print("Selecciona dos puntos con distancia conocida:")
    print(f"Distancia real: {known_distance_meters}m")
    
    points = []
    
    def mouse_callback(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and len(points) < 2:
            points.append([x, y])
    
    cv2.namedWindow('Calibration')
    cv2.setMouseCallback('Calibration', mouse_callback)
    
    while len(points) < 2:
        img = frame.copy()
        for pt in points:
            cv2.circle(img, tuple(pt), 5, (0, 255, 0), -1)
        if len(points) == 2:
            cv2.line(img, tuple(points[0]), tuple(points[1]), (0, 255, 0), 2)
        cv2.imshow('Calibration', img)
        cv2.waitKey(1)
    
    cv2.destroyAllWindows()
    
    # Calcular distancia en pixels
    p1, p2 = points
    pixel_distance = np.sqrt((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)
    
    # Calcular escala
    pixels_per_meter = pixel_distance / known_distance_meters
    
    print(f"Calibración completada:")
    print(f"  Distancia en pixels: {pixel_distance:.2f}")
    print(f"  Pixels por metro: {pixels_per_meter:.2f}")
    
    return pixels_per_meter
```

---

## 4. Casos de Uso

### Caso 1: Autopista con Vista Frontal

**Desafío:** Vehículos a diferentes distancias tienen tamaños muy diferentes.

**Solución:**

```python
class HighwayPerspectiveHandler:
    def __init__(self, frame_height):
        self.frame_height = frame_height
        self.horizon_y = frame_height * 0.3  # Línea de horizonte
    
    def normalize_bbox_size(self, bbox, confidence_boost=True):
        """
        Normalizar tamaño de bbox según distancia
        """
        x1, y1, x2, y2 = bbox
        center_y = (y1 + y2) / 2
        
        # Calcular factor de escala (más lejano = más pequeño)
        # y cercano a horizon_y → muy lejos
        # y cercano a frame_height → muy cerca
        distance_factor = (center_y - self.horizon_y) / \
                         (self.frame_height - self.horizon_y)
        distance_factor = np.clip(distance_factor, 0.1, 1.0)
        
        # Tamaño normalizado
        w = (x2 - x1) / distance_factor
        h = (y2 - y1) / distance_factor
        
        # Boost de confianza para objetos lejanos
        if confidence_boost:
            confidence_multiplier = 1.0 + (1.0 - distance_factor) * 0.3
        else:
            confidence_multiplier = 1.0
        
        return {
            'normalized_size': (w, h),
            'distance_factor': distance_factor,
            'confidence_multiplier': confidence_multiplier
        }
```

### Caso 2: Intersección con Vista Angular

**Desafío:** Diferentes carriles tienen diferentes escalas y ángulos.

**Solución:**

```python
class IntersectionMultiZoneHandler:
    def __init__(self):
        self.zones = {}
    
    def add_zone(self, name, polygon, homography):
        """
        Agregar zona con su propia transformación
        
        Args:
            name: Nombre de la zona (ej: "carril_norte")
            polygon: Polígono que define la zona
            homography: Matriz de homografía para esta zona
        """
        self.zones[name] = {
            'polygon': polygon,
            'homography': homography,
            'counter': BidirectionalCounter()
        }
    
    def process_tracks(self, tracks):
        """
        Procesar tracks según la zona donde se encuentran
        """
        results = {}
        
        for track in tracks:
            bbox = track['bbox']
            center = self._bbox_center(bbox)
            
            # Determinar zona
            zone_name = self._point_in_zone(center)
            
            if zone_name:
                zone = self.zones[zone_name]
                
                # Transformar coordenadas a espacio de la zona
                H = zone['homography']
                center_transformed = cv2.perspectiveTransform(
                    np.array([[center]], dtype='float32'), H
                )[0][0]
                
                # Actualizar track con coordenadas transformadas
                track_transformed = track.copy()
                track_transformed['center'] = center_transformed
                
                # Procesar en zona
                zone['counter'].update([track_transformed])
        
        # Recopilar resultados
        for name, zone in self.zones.items():
            results[name] = zone['counter'].get_counts()
        
        return results
```

### Caso 3: Estacionamiento con Vista Cenital Parcial

**Desafío:** Transición entre vista angular y cenital.

**Solución:** Usar transformación por zonas con interpolación suave.

```python
def create_blended_homography(H1, H2, blend_zone, point):
    """
    Interpolar entre dos homografías en zona de transición
    
    Args:
        H1, H2: Matrices de homografía
        blend_zone: (y_start, y_end) zona de mezcla
        point: Punto a transformar
    
    Returns:
        Punto transformado con mezcla
    """
    y_start, y_end = blend_zone
    y = point[1]
    
    if y < y_start:
        # Usar H1 completamente
        alpha = 0.0
    elif y > y_end:
        # Usar H2 completamente
        alpha = 1.0
    else:
        # Mezclar
        alpha = (y - y_start) / (y_end - y_start)
    
    # Transformar con ambas matrices
    pt1 = cv2.perspectiveTransform(
        np.array([[point]], dtype='float32'), H1
    )[0][0]
    
    pt2 = cv2.perspectiveTransform(
        np.array([[point]], dtype='float32'), H2
    )[0][0]
    
    # Interpolar
    blended = (1 - alpha) * pt1 + alpha * pt2
    
    return blended
```

---

## 5. Implementación

### Integración en el Sistema

```python
# En main.py

# Cargar configuración de perspectiva
if config.get('perspective', {}).get('correction', {}).get('enabled'):
    H = np.load(config['perspective']['calibration']['matrix_file'])
    
    # Aplicar transformación antes de procesamiento
    def preprocess_frame(frame):
        return cv2.warpPerspective(frame, H, (width, height))
else:
    def preprocess_frame(frame):
        return frame

# En el loop principal
while True:
    ret, frame = video.read()
    
    # Transformar perspectiva si es necesario
    frame_processed = preprocess_frame(frame)
    
    # Continuar con pipeline normal
    detections = detector.detect(frame_processed)
    ...
```

### Script de Calibración Completo

Ver `calibrate_camera.py` para implementación completa.

---

## Referencias

1. [Multiple View Geometry - Hartley & Zisserman](http://www.robots.ox.ac.uk/~vgg/hzbook/)
2. [OpenCV Camera Calibration Tutorial](https://docs.opencv.org/4.x/dc/dbb/tutorial_py_calibration.html)
3. [Homography Estimation](https://docs.opencv.org/4.x/d9/dab/tutorial_homography.html)

---

**Nota:** Para calibración asistida, ejecutar:
```bash
python calibrate_camera.py --video input/video.mp4 --interactive
```
