"""
Carga de carriles de conteo para una fuente de video.

Compartido entre el motor en vivo (counting_service.py) y el procesador
de videos subidos (video_job_processor.py) para no duplicar la traducción
de la config guardada a contadores reales.
"""

import logging
from typing import Dict, Optional, Tuple

from src.counter import BidirectionalCounter
from src.storage import traffic_db


def build_lane_counters(
    camera_source: str,
    frame_height: int,
    frame_width: int,
    project_id: Optional[int] = None,
    auto_create_default: bool = False,
) -> Tuple[Dict[int, BidirectionalCounter], Dict[int, Dict]]:
    """
    Devuelve un contador por cada carril configurado de esta fuente.

    auto_create_default: si no hay carriles, crear uno horizontal al centro
        del frame. Solo lo usa la CÁMARA EN VIVO, donde no hay nadie que
        calibre antes de que arranque el conteo (y que de todos modos se
        puede recalibrar en caliente con CountingService.reload_lanes()).
        Los videos subidos lo dejan en False a propósito: ahí el usuario
        define los carriles ANTES de procesar, para que el conteo nunca
        dependa de una línea inventada que quizá ni cruza la vía.
    """
    traffic_db.init_schema()

    if project_id is not None:
        lanes = traffic_db.list_lanes(project_id=project_id)
    else:
        lanes = traffic_db.list_lanes(camera_source=camera_source)

    if not lanes and auto_create_default and frame_height and frame_width:
        default_points = [[0, frame_height // 2], [frame_width, frame_height // 2]]
        traffic_db.create_lane(
            camera_source=camera_source,
            name="Carril 1",
            line_type="horizontal",
            points=default_points,
            project_id=project_id,
        )
        lanes = (
            traffic_db.list_lanes(project_id=project_id)
            if project_id is not None
            else traffic_db.list_lanes(camera_source=camera_source)
        )

    counters = {}
    meta = {}
    for lane in lanes:
        counter = BidirectionalCounter(line_type=lane["line_type"])
        points = lane["points"]
        if lane["line_type"] == "horizontal":
            counter.set_counting_line(
                line_type="horizontal", y=int(points[0][1]),
                frame_shape=(frame_height, frame_width)
            )
        elif lane["line_type"] == "vertical":
            counter.set_counting_line(
                line_type="vertical", x=int(points[0][0]),
                frame_shape=(frame_height, frame_width)
            )
        else:
            counter.set_counting_line(
                line_type=lane["line_type"], points=points,
                frame_shape=(frame_height, frame_width)
            )
        counters[lane["id"]] = counter
        meta[lane["id"]] = lane

    logging.info(f"Carriles cargados para {camera_source}: {list(counters.keys())}")
    return counters, meta
