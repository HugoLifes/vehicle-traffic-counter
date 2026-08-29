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
- FPS real de YOLOv8n sobre el Orin Nano con la cámara definitiva
- Que los límites de memoria (6GB) sean suficientes con las IAs de
  NVIDIA activas (Fase D-F) corriendo junto al conteo
