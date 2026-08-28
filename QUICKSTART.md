# 🚀 Inicio Rápido

Guía rápida para empezar a usar el sistema de aforo vehicular en menos de 5 minutos.

## Paso 1: Instalación (2 minutos)

```bash
# 1. Clonar o descargar el repositorio
cd vehicle-traffic-counter

# 2. Crear entorno virtual (recomendado)
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate

# 3. Instalar dependencias
pip install -r requirements.txt
```

## Paso 2: Descargar Modelo (1 minuto)

```bash
python download_model.py
```

El script descargará automáticamente el modelo YOLOv8n (~6MB).

## Paso 3: Preparar Video

Coloca tu video en la carpeta `input/`:

```
vehicle-traffic-counter/
├── input/
│   └── tu_video.mp4  ← Coloca tu video aquí
```

## Paso 4: Ejecutar (1 minuto)

```bash
python main.py --source input/tu_video.mp4 --save-video --display
```

¡Listo! El sistema procesará el video y guardará los resultados en `results/`.

---

## Opciones Comunes

### Cambiar posición de línea de conteo

```bash
python main.py --video input/video.mp4 --line-y 450
```

### Ajustar umbral de confianza

```bash
python main.py --video input/video.mp4 --confidence 0.5
```

### Usar configuración optimizada para Jetson Nano

```bash
python main.py \
    --video input/video.mp4 \
    --config configs/jetson_optimized.yaml
```

### Contar desde una cámara en vivo (webcam o RTSP)

```bash
# Webcam USB (índice 0)
python main.py --source 0 --config configs/jetson_optimized.yaml --report-interval 1000

# Cámara IP por RTSP
python main.py --source "rtsp://usuario:pass@192.168.1.50:554/stream1" \
    --config configs/jetson_optimized.yaml --report-interval 1000
```

`--report-interval N` guarda/actualiza los reportes cada N frames — útil en
fuentes en vivo que corren por horas, para no perder datos si se corta la luz.

### Solo guardar estadísticas (sin video de salida)

```bash
python main.py --video input/video.mp4
```

---

## Verificar Instalación

```bash
python test_system.py
```

Este script verifica que todo esté instalado correctamente.

---

## Resultados

Los resultados se guardan en `results/`:

```
results/
├── output_video.mp4          # Video procesado
├── counts.json               # Conteos detallados
├── trajectory_data.json      # Trayectorias
├── statistics.csv            # Estadísticas
├── counts_by_type.png        # Gráfica
└── direction_distribution.png
```

---

## Ejemplos

### Ejemplo 1: Autopista

```bash
python examples/example_highway.py
```

### Ejemplo 2: Intersección

```bash
python examples/example_intersection.py
```

---

## Problemas Comunes

### "ModuleNotFoundError: No module named 'ultralytics'"

**En tu PC:**
```bash
pip install ultralytics
```

**En el Jetson Nano:** no lo instales nativo, el Python 3.6 de JetPack 4.6
no es compatible con `ultralytics` (requiere ≥3.8). Usa `bash
setup_jetson.sh` (Docker) — ver [README.md](README.md).

### "Video no encontrado"

**Solución:**
Verifica que el video esté en la carpeta `input/` y que la ruta sea correcta.

### "CUDA out of memory"

**Solución:**
```bash
# Usar modelo más pequeño
python main.py --video input/video.mp4 --model models/yolov8n.pt

# O reducir resolución
python main.py --video input/video.mp4 --input-size 416
```

---

## Siguiente Paso

Lee el [README completo](README.md) para opciones avanzadas y configuración detallada.

---

**¿Necesitas ayuda?** Consulta la [documentación completa](docs/) o abre un issue.
