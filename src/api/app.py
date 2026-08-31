"""
Backend FastAPI de la plataforma de aforo vehicular.

Envuelve el motor de conteo (src/engine/counting_service.py) en un
servicio web: arranca el conteo en segundo plano al iniciar, expone
los conteos por API y sirve el dashboard estático.
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import yaml
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.engine.counting_service import CountingService, set_service
from src.engine.video_job_processor import VideoJobProcessor, set_processor
from src.storage import traffic_db
from src.utils import setup_logger

CONFIG_PATH = os.environ.get("PLATFORM_CONFIG", "configs/platform.yaml")


def load_platform_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    # Permite sobreescribir la fuente de cámara sin editar el YAML
    env_source = os.environ.get("CAMERA_SOURCE")
    if env_source:
        config["camera_source"] = env_source
    return config


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logger(level=logging.INFO)
    traffic_db.init_schema()

    config = load_platform_config()
    service = CountingService(
        camera_source=config["camera_source"],
        model_path=config.get("model_path", "models/yolov8n.pt"),
        confidence_threshold=config.get("confidence_threshold", 0.4),
        device=config.get("device", "auto"),
        config={
            "detector": config.get("detector", {}),
            "tracker": config.get("tracker", {}),
        }
    )
    set_service(service)
    service.start()

    # Procesador de videos subidos (por lote, secuencial, aparte del
    # motor en vivo) — reusa el mismo modelo/config del detector.
    video_processor = VideoJobProcessor(
        model_path=config.get("model_path", "models/yolov8n.pt"),
        confidence_threshold=config.get("confidence_threshold", 0.4),
        device=config.get("device", "auto"),
        config={
            "detector": config.get("detector", {}),
            "tracker": config.get("tracker", {}),
        }
    )
    set_processor(video_processor)
    video_processor.start()

    yield

    service.stop()
    video_processor.stop()


app = FastAPI(title="Aforo Vehicular - Plataforma", lifespan=lifespan)

from src.api.routes_counts import router as counts_router  # noqa: E402
from src.api.routes_videos import router as videos_router  # noqa: E402
from src.api.routes_camera import router as camera_router  # noqa: E402
from src.api.routes_lanes import router as lanes_router  # noqa: E402
from src.api.routes_zones import router as zones_router  # noqa: E402
from src.api.routes_projects import router as projects_router  # noqa: E402
from src.api.routes_geo import router as geo_router  # noqa: E402
from src.api.routes_video_frames import router as frames_router  # noqa: E402
from src.api.routes_export import router as export_router  # noqa: E402
app.include_router(counts_router)
app.include_router(videos_router)
app.include_router(camera_router)
app.include_router(lanes_router)
app.include_router(zones_router)
app.include_router(projects_router)
app.include_router(geo_router)
app.include_router(frames_router)
app.include_router(export_router)


FRONTEND_DIR = Path(os.environ.get("FRONTEND_DIR", "web/dist"))


class SPAStaticFiles(StaticFiles):
    """
    Sirve el frontend ya construido (Vite → web/dist).

    Dos cosas que el StaticFiles de serie no hace y aquí hacen falta:

    1. **Rutas del enrutador.** /calibrar y /reporte no son archivos: los
       resuelve React Router en el navegador. Al recargar la página o
       entrar por un enlace directo, el servidor tiene que devolver
       index.html en vez de un 404.

    2. **Caché correcta según el tipo de archivo.** Vite pone un hash del
       contenido en el nombre de cada bundle (index-D6JvMFO6.js), así que
       esos archivos se pueden cachear para siempre: si el contenido
       cambia, cambia el nombre. index.html es lo contrario — es el que
       apunta a los bundles nuevos, así que se revalida siempre. Sin esa
       distinción el navegador se queda con la interfaz anterior después
       de actualizar la plataforma (pasó, y se veía como una página rota).
    """

    async def get_response(self, path, scope):
        # StaticFiles normaliza la ruta con os.path.normpath, que en Windows
        # devuelve "assets\index-abc.js" y en Linux "assets/index-abc.js".
        # Se unifica el separador para que las comprobaciones de abajo se
        # comporten igual en el equipo de desarrollo y en el Jetson.
        rel = path.replace(os.sep, "/").lstrip("/")

        # Una ruta /api/... que llega hasta aquí es un endpoint que no
        # existe. Devolver el index.html haría que el frontend recibiera
        # HTML donde espera JSON y fallara con un error incomprensible;
        # un 404 dice la verdad.
        if rel.startswith("api/"):
            raise StarletteHTTPException(status_code=404, detail="Endpoint no encontrado")

        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            # StaticFiles LANZA un 404 en vez de devolverlo, así que la
            # reserva del enrutador va en un except, no en un if. Y la
            # excepción es la de Starlette: capturar la de FastAPI no
            # sirve, porque esta es su clase padre y no su subclase.
            if exc.status_code != 404:
                raise
            response = await super().get_response("index.html", scope)

        if response.status_code == 404:
            response = await super().get_response("index.html", scope)

        if rel.startswith("assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers.setdefault("Cache-Control", "no-cache")
        return response


if FRONTEND_DIR.is_dir():
    app.mount("/", SPAStaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
else:
    @app.get("/")
    def missing_frontend():
        # Mensaje explícito en vez de un 404 pelado: lo que falta es el
        # build, y el mensaje dice cómo hacerlo.
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    f"No se encontró el frontend construido en '{FRONTEND_DIR}'. "
                    "Constrúyelo con: cd web && npm install && npm run build"
                )
            },
        )
