# Despliegue en Jetson Orin Nano

Guía de referencia para cuando el Jetson Orin Nano esté armado (SSD NVMe,
teclado y cable de video conectados) y con JetPack ya instalado. No se ha
podido probar contra el hardware real todavía — está preparado y
documentado para que el primer deploy sea lo más directo posible.

## 0. Antes de empezar: confirmar la versión de JetPack

```bash
cat /etc/nv_tegra_release
```

Este proyecto asume **JetPack 6.x** (Ubuntu 22.04, L4T 36.x — lo normal
para un Orin Nano comprado en 2026). Si el resultado dice otra cosa,
avisa antes de seguir: el único cambio necesario sería la línea `FROM`
en [`Dockerfile.jetson`](../Dockerfile.jetson) (cambiar
`latest-jetson-jetpack6` por `latest-jetson-jetpack5`, por ejemplo).

## 1. Requisitos previos en el Jetson

```bash
docker --version
docker info | grep -i nvidia   # confirma que el runtime "nvidia" está disponible
```

JetPack trae Docker + `nvidia-container-runtime` de fábrica desde la
versión 4.4 en adelante, así que normalmente no hay que instalar nada
extra. Si `docker info` no muestra nada de nvidia:

```bash
sudo apt-get update && sudo apt-get install -y nvidia-container-runtime
sudo systemctl restart docker
```

## 2. Preparar el proyecto en el Jetson

```bash
git clone <url-del-repo> vehicle-traffic-counter
cd vehicle-traffic-counter

cp .env.example .env
nano .env   # pegar tu NVIDIA_API_KEY real ahí (nunca en un archivo del repo)
```

## 3. Construir y levantar

```bash
docker compose -f docker-compose.jetson.yml up -d --build
```

La primera construcción tarda — está descargando la imagen base de
Ultralytics para JetPack 6 (varios GB) y compilando lo que haga falta.
Los siguientes arranques son casi instantáneos.

> **Sobre el frontend.** La interfaz es React y hay que compilarla, pero
> eso pasa **dentro del build de Docker**, en una etapa aparte con Node
> (`node:22-alpine`, que tiene imagen para ARM64). A la imagen que corre
> en el Jetson solo llegan los archivos estáticos ya compilados: el
> equipo no lleva Node, ni npm, ni `node_modules`, y no compila nada en
> tiempo de ejecución. FastAPI los sirve directamente.
>
> Solo hace falta internet **al construir**, no al operar.

```bash
docker compose -f docker-compose.jetson.yml logs -f
```

Cuando se vea `Application startup complete`, abre desde cualquier
dispositivo en la misma red:

```
http://<ip-del-jetson>:8080
```

## 4. Límites de recursos (ya configurados)

El Orin Nano Super tiene **8GB de RAM compartida** entre CPU y GPU — no
es una GPU con VRAM aparte, es un solo pool. En
[`docker-compose.jetson.yml`](../docker-compose.jetson.yml) el
contenedor está limitado a:

| Recurso | Límite | Por qué |
|---|---|---|
| Memoria | 6GB (de 8GB totales) | Deja ~2GB para JetPack/el sistema operativo — si el contenedor se come toda la RAM, el equipo completo se cuelga, no solo la app |
| Swap adicional | 0 (memswap = mem_limit) | Mejor un reinicio controlado del contenedor que el equipo arrastrándose por swap en la microSD/NVMe |
| CPU | 5 de 6 núcleos | 1 núcleo libre para que el sistema operativo no se ahorque si YOLO + FastAPI + un video subido van a la vez |
| Logs | 10MB × 3 archivos | Para que los logs no se coman el almacenamiento con el tiempo |

Si el contenedor se reinicia solo por quedarse sin memoria, revisar con:

```bash
docker stats aforo-vehicular
```

y considerar bajar `--source` a menor resolución/skip_frames en
`configs/platform.yaml`, o subir el límite si de verdad hay margen.

## 5. Cámara

- **Cámara IP (RTSP)** — recomendado, no necesita nada especial en
  Docker, solo que el Jetson tenga red hacia la cámara. Configurar la
  URL en `.env`:
  ```
  CAMERA_SOURCE=rtsp://usuario:pass@192.168.1.50:554/stream1
  ```
- **Webcam USB** — hay que exponer el dispositivo al contenedor.
  Descomentar en `docker-compose.jetson.yml`:
  ```yaml
  devices:
    - /dev/video0:/dev/video0
  ```

## 6. Comandos útiles

```bash
# Ver estado / reiniciar
docker compose -f docker-compose.jetson.yml ps
docker compose -f docker-compose.jetson.yml restart

# Procesar un video puntual con reportes (en vez de levantar el servidor)
docker compose -f docker-compose.jetson.yml run --rm aforo-vehicular \
  python3 main.py --source input/video.mp4 --save-video

# Apagar todo
docker compose -f docker-compose.jetson.yml down

# Verificar la API de NVIDIA desde dentro del contenedor
docker compose -f docker-compose.jetson.yml exec aforo-vehicular python3 test_nvidia_api.py
```

## 6.5 Velocidad: lo primero que hay que medir y ajustar

El detector está en **yolov8s a imgsz 1280 sobre la franja de la vía**
(ver [DETECCION.md](DETECCION.md) para el porqué de cada valor). Eso da,
en la PC de desarrollo con una GPU de escritorio:

| imgsz | ms por cuadro | Un video de 10 min tarda |
|---|---|---|
| 640 | 11.1 | 1.7 min |
| 960 | 17.1 | 2.6 min |
| **1280** *(actual)* | **30.6** | **4.6 min** |

### Medido en el equipo real (Orin Nano Super, JetPack 6.2, modo MAXN)

| imgsz | ms por cuadro | Un video de 10 min tarda |
|---|---|---|
| 640 | 21.3 | 3.2 min |
| 960 | 24.0 | 3.6 min |
| **1280** *(actual)* | **37.3** | **5.6 min** |

Y de punta a punta sobre video real, con detector + tracker:
**40.7 ms/cuadro → 6.1 min por cada video de 10 min**, sin un solo error.

**El Orin Nano resultó solo 1.3 veces más lento que la PC**, no 5 a 8
como se había estimado antes de tenerlo. Procesa por encima del tiempo
real y **no hace falta TensorRT**: un aforo de 24 h (144 segmentos) sale
en unas 15 horas de proceso continuo.

Aun así conviene volver a medir al cambiar de equipo o de JetPack:

```bash
docker compose -f docker-compose.jetson.yml exec aforo-vehicular   python3 -c "
import time, cv2, numpy as np
from src.detector import VehicleDetector
d = VehicleDetector('models/yolov8s.pt', 0.25, 0.5, 1280, 'auto')
f = np.zeros((360, 640, 3), np.uint8)
for _ in range(5): d.detect(f)
t = time.time()
for _ in range(30): d.detect(f)
print(f'{(time.time()-t)/30*1000:.0f} ms por cuadro')
"
```

### Si en otro equipo sale por encima de unos 60 ms, encender TensorRT

En [`configs/platform.yaml`](../configs/platform.yaml):

```yaml
detector:
  use_tensorrt: true
  half_precision: true
```

TensorRT compila el modelo **para esa GPU concreta**: la primera vez
tarda varios minutos y deja un `.engine` junto al `.pt`, que se reutiliza
en los arranques siguientes. Da del orden de 2-3x. Como el `.engine` es
específico del equipo, no se sube al repo ni se copia a otro Jetson.

### Si aun así no alcanza

En este orden, porque así es como menos exactitud se pierde:

1. **`input_size: 960`** — casi la mitad de tiempo. Se pierden algunos
   vehículos de la calzada del fondo, que ya son los más difíciles.
2. **`input_size: 640`** — un tercio del tiempo, pero sobre este material
   el conteo baja bastante; ver la tabla de DETECCION.md antes de bajar
   aquí.
3. Procesar de noche o por lotes, dejando el equipo trabajando sin prisa:
   un aforo grabado no tiene que procesarse en tiempo real.

Lo que **no** conviene tocar es el modelo: volver a yolov8n hace que el
equipo vea la mitad de los vehículos, y entonces la velocidad da igual.

## 7. Ajustar rendimiento del sistema (fuera de Docker)

Independiente del contenedor — configura el propio Jetson para máximo
rendimiento (se resetea al reiniciar, conviene dejarlo en un cron
`@reboot` o correrlo manualmente tras cada arranque):

```bash
sudo bash configure_jetson_performance.sh
```

## 8. Lo que falta validar contra hardware real

Esta guía está lista para usarse, pero como no hay acceso al Jetson
físico todavía, quedan pendientes de confirmar en el primer deploy real:

- Que la versión de JetPack sea efectivamente 6.x (paso 0)
- **Los ms por cuadro reales** (paso 6.5) — es lo que decide si hace
  falta TensorRT o bajar `input_size`
- Que el `.engine` de TensorRT se compile sin errores en este JetPack
- Que los límites de memoria (6GB) sean suficientes con las IAs de
  NVIDIA activas (Fase D-F) corriendo junto al conteo
