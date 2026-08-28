# Sistema de Aforo Vehicular Bidireccional con YOLO

Sistema completo de detección, rastreo y conteo de vehículos en ambas direcciones optimizado para NVIDIA Jetson Nano.

## 🚀 Características

- ✅ Detección de vehículos con YOLOv8 (optimizado para Jetson Nano)
- ✅ Tracking robusto con DeepSORT
- ✅ Conteo bidireccional (entrada/salida)
- ✅ Soporte para múltiples perspectivas de cámara
- ✅ Análisis de videos grabados y cámaras en vivo (webcam / RTSP)
- ✅ Exportación de datos y reportes
- ✅ Visualización en tiempo real
- ✅ Optimización para hardware embebido

## 📋 Requisitos

### Hardware
- NVIDIA Jetson Nano (4GB recomendado)
- Cámara IP (RTSP) recomendada para instalación en poste/exterior, o webcam USB
- MicroSD 32GB+ (clase 10)

### Software
- **Jetson Nano:** JetPack 4.6.x (tope de este hardware) + Docker — ver
  sección de instalación. El sistema operativo (Ubuntu 18.04 + drivers
  NVIDIA/CUDA) ya viene incluido al flashear JetPack, no se instala aparte.
- **PC de desarrollo:** Python 3.8+, CUDA opcional (funciona en CPU)

## 🔧 Instalación

### En tu PC (desarrollo y validación)

```bash
cd vehicle-traffic-counter

python -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate

pip install --upgrade pip
pip install -r requirements.txt

python download_model.py
python test_system.py   # debe dar 6/6 tests pasados
```

### En Jetson Nano (JetPack 4.6.x) — ruta recomendada: Docker

⚠️ **Importante:** el Jetson Nano original está topado en JetPack 4.6.x, que
trae **Python 3.6** de sistema. El paquete `ultralytics` (YOLOv8+) requiere
Python ≥3.8, así que `pip install -r requirements.txt` **no funciona
directo en el Nano**. La forma soportada y confiable es usar Docker con la
imagen oficial de Ultralytics para JetPack 4, que ya trae todo compilado
para este hardware.

```bash
git clone <repository-url>
cd vehicle-traffic-counter

# Construye la imagen, ajusta el rendimiento del sistema y descarga el modelo
bash setup_jetson.sh
```

Esto usa [Dockerfile.jetson](Dockerfile.jetson). Si necesitas instalación
nativa sin Docker (no recomendado, experimental), revisa
[setup_jetson_native.sh](setup_jetson_native.sh).

## 🎯 Uso Rápido

`--source` acepta tres tipos de entrada: archivo de video, índice de webcam,
o URL de cámara IP (RTSP/HTTP). `--video` se mantiene como alias por
compatibilidad.

### Video grabado

```bash
python main.py --source input/traffic_video.mp4 --output results/
```

### Cámara en vivo (webcam USB, índice 0)

```bash
python main.py --source 0 --config configs/jetson_optimized.yaml \
    --save-video --display --report-interval 1000
```

### Cámara IP en vivo (RTSP) — recomendado para instalación en poste/exterior

```bash
python main.py --source "rtsp://usuario:pass@192.168.1.50:554/stream1" \
    --config configs/jetson_optimized.yaml --save-video --report-interval 1000
```

`--report-interval N` regenera los reportes cada N frames en fuentes en
vivo, para no perder datos si el proceso corre por horas. En fuentes en
vivo, si la cámara se desconecta el sistema reintenta reconectar
automáticamente.

### Con líneas de conteo personalizadas

```bash
python main.py \
    --source input/traffic_video.mp4 \
    --line-y 400 \
    --direction horizontal \
    --output results/
```

### En el Jetson, vía Docker

```bash
docker run --rm -it --runtime nvidia --device /dev/video0 \
    -v $(pwd)/models:/app/models -v $(pwd)/results:/app/results \
    vehicle-traffic-counter:jetson \
    --source 0 --config configs/jetson_optimized.yaml --save-video --report-interval 1000
```

## 📐 Configuración de Líneas de Conteo

El sistema soporta múltiples configuraciones de perspectiva:

### 1. Vista Cenital (Top-Down)
```yaml
perspective: "top_down"
counting_line:
  type: "horizontal"
  y: 400
```

### 2. Vista Frontal
```yaml
perspective: "frontal"
counting_line:
  type: "horizontal"
  y: 300
  angle_correction: true
```

### 3. Vista Angular
```yaml
perspective: "angular"
counting_line:
  type: "polygon"
  points: [[100, 200], [500, 250], [500, 350], [100, 400]]
```

## 📊 Estructura de Resultados

```
results/
├── video_output.mp4          # Video con detecciones
├── counts.json               # Conteos detallados
├── trajectory_data.json      # Trayectorias completas
├── statistics.csv            # Estadísticas agregadas
└── heatmap.png              # Mapa de calor de tráfico
```

## 🎨 Configuración Personalizada

Edita `configs/default_config.yaml` para ajustar:

- Clases de vehículos a detectar
- Umbrales de confianza
- Parámetros de tracking
- Líneas de conteo
- Zonas de interés (ROI)
- Configuración de perspectiva

## 📈 Optimización para Jetson Nano

El sistema incluye optimizaciones específicas:

1. **Modelo TensorRT**: Conversión automática a TensorRT para +3x velocidad
2. **Resolución adaptativa**: Reduce resolución para mantener FPS
3. **Batch processing**: Procesa frames en lotes
4. **Memoria optimizada**: Limpieza automática de memoria

```bash
# Convertir modelo a TensorRT (recomendado)
python optimize_model.py --model models/yolov8n.pt --output models/yolov8n_trt.engine
```

## 🔍 Algoritmos Implementados

### Detección
- **YOLOv8**: Balance entre velocidad y precisión
- **Clases soportadas**: autos, buses, camiones, motocicletas

### Tracking
- **DeepSORT**: Tracking robusto con características de apariencia
- **Kalman Filter**: Predicción de trayectorias
- **Hungarian Algorithm**: Asociación óptima de detecciones

### Conteo
- **Cruce de línea**: Detección precisa de cruces bidireccionales
- **Filtrado de duplicados**: Evita conteos múltiples
- **Análisis de dirección**: Vectores de movimiento para determinar dirección

## 📚 Ejemplos

Ver carpeta `examples/` para scripts de ejemplo:

- `example_highway.py`: Conteo en autopista
- `example_intersection.py`: Intersección con 4 direcciones
- `example_parking.py`: Entrada/salida de estacionamiento
- `example_multiple_cameras.py`: Sistema multi-cámara

## 🛠️ Calibración de Cámara

Para mejor precisión con perspectivas angulares:

```bash
python calibrate_camera.py --video input/calibration_video.mp4
```

Esto genera una matriz de transformación de perspectiva guardada en `configs/camera_matrix.yaml`.

## 🐛 Troubleshooting

### `pip install ultralytics` falla en el Jetson Nano
Es esperado: Python 3.6 de JetPack 4.6 no es compatible con `ultralytics`
(requiere ≥3.8). Usa `setup_jetson.sh` (Docker) en vez de instalar nativo.

### Bajo FPS en Jetson Nano
- Usar modelo YOLOv8n (nano) en lugar de versiones más grandes
- Usar `configs/jetson_optimized.yaml` (input_size 416, skip_frames, TensorRT)
- Convertir a TensorRT: `python optimize_model.py --model models/yolov8n.pt --jetson`
- Habilitar modo de máximo rendimiento: `sudo bash configure_jetson_performance.sh`

### Cámara IP se desconecta durante el monitoreo
El sistema reintenta reconectar automáticamente (hasta 10 intentos, cada
2s). Si sigue fallando, revisa la URL RTSP, la red, y que la cámara no
tenga un límite de streams simultáneos.

### Conteos inexactos
- Ajustar posición de línea de conteo
- Aumentar umbral de confianza
- Calibrar perspectiva de cámara
- Ajustar parámetros de tracking

### Error de memoria
- Reducir buffer de frames: `--buffer-size 30`
- Usar modelo más pequeño
- Procesar video en segmentos

## 📖 Documentación Técnica

Ver `docs/` para documentación detallada:

- `ARCHITECTURE.md`: Arquitectura del sistema
- `ALGORITHMS.md`: Detalles de algoritmos
- `API.md`: Referencia de API
- `CALIBRATION.md`: Guía de calibración

## 🤝 Contribuciones

Las contribuciones son bienvenidas. Por favor:

1. Fork el proyecto
2. Crea una rama para tu feature
3. Commit tus cambios
4. Push a la rama
5. Abre un Pull Request

## 📄 Licencia

MIT License - Ver `LICENSE` para más detalles

## 👥 Autores

- Sistema desarrollado para análisis de tráfico vehicular

## 🙏 Agradecimientos

- Ultralytics (YOLOv8)
- DeepSORT
- OpenCV
- PyTorch

## 📞 Soporte

Para preguntas y soporte:
- Abrir un issue en GitHub
- Revisar documentación en `docs/`
- Consultar ejemplos en `examples/`

---

**Versión**: 1.0.0  
**Última actualización**: Febrero 2026  
**Estado**: Producción
