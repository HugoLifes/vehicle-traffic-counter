"""
Backend FastAPI de la plataforma de aforo vehicular.

Envuelve el motor de conteo (src/engine/counting_service.py) en un
servicio web: arranca el conteo en segundo plano al iniciar, expone
los conteos por API y sirve el dashboard estático.
"""

import logging
import os
from contextlib import asynccontextmanager

import yaml
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

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
from src.api.routes_projects import router as projects_router  # noqa: E402
from src.api.routes_geo import router as geo_router  # noqa: E402
app.include_router(counts_router)
app.include_router(videos_router)
app.include_router(camera_router)
app.include_router(lanes_router)
app.include_router(projects_router)
app.include_router(geo_router)


@app.get("/")
def root():
    # Los proyectos son la puerta de entrada: todo lo demás (subir, calibrar,
    # reportar) necesita una intersección seleccionada.
    return RedirectResponse(url="/proyectos.html")


class NoCacheStaticFiles(StaticFiles):
    """
    Sirve el frontend pidiéndole al navegador que revalide siempre.

    Sin esto, el navegador se queda con el CSS/JS viejo tras actualizar la
    plataforma y muestra una interfaz rota o a medias (comprobado: tras
    editar shared.css, Chrome seguía usando la copia anterior aunque el
    servidor ya servía la nueva). `no-cache` no significa "no guardar":
    el archivo se sigue cacheando, solo que el navegador pregunta primero
    si cambió — y recibe un 304 barato cuando no.
    """

    def is_not_modified(self, response_headers, request_headers) -> bool:
        response_headers.setdefault("Cache-Control", "no-cache")
        return super().is_not_modified(response_headers, request_headers)

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers.setdefault("Cache-Control", "no-cache")
        return response


app.mount("/", NoCacheStaticFiles(directory="frontend", html=True), name="frontend")
