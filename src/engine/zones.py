"""
Uso de las zonas dibujadas durante el conteo.

Las zonas resuelven un problema que la línea de conteo sola no puede: en
perspectiva, la calzada cercana ocupa media pantalla y la del fondo cabe
en una franja de 15 px, pero en la imagen quedan una encima de la otra.
Una línea vertical las cruza a AMBAS, así que sin zonas no hay forma de
saber a qué calzada pertenece un cruce — que es exactamente lo que se
pierde hoy cuando "arriba hacia abajo" no se distingue de "abajo hacia
arriba".

Tres usos, en orden de impacto:

1. **Atribuir** cada cruce a su calzada (`zone_for_point`).
2. **Descartar** lo que se mueve fuera de la vía — patios, estacionamientos,
   banquetas — antes de que llegue al tracker (`filter_detections`).
3. **Acotar** la inferencia a la franja que ocupan las zonas, que es lo que
   permite subir imgsz sin pagarlo en tiempo (`band_from_zones`).
"""

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np

try:
    import cv2
except ImportError:      # pragma: no cover - cv2 siempre está en producción
    cv2 = None

from src.storage import traffic_db


def load_zones(project_id: Optional[int]) -> List[Dict]:
    if project_id is None:
        return []
    try:
        return traffic_db.list_zones(project_id=project_id, active_only=True)
    except Exception as e:
        logging.warning(f"No se pudieron cargar las zonas del proyecto {project_id}: {e}")
        return []


def _contiene(points: List[List[float]], x: float, y: float) -> bool:
    """Punto dentro del polígono, por el algoritmo del rayo.

    Se implementa a mano y no con cv2.pointPolygonTest para no construir un
    array de numpy por cada detección de cada cuadro: esto corre decenas de
    miles de veces por video.
    """
    dentro = False
    n = len(points)
    j = n - 1
    for i in range(n):
        xi, yi = points[i][0], points[i][1]
        xj, yj = points[j][0], points[j][1]
        if (yi > y) != (yj > y):
            corte_x = (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi
            if x < corte_x:
                dentro = not dentro
        j = i
    return dentro


def _punto_de_apoyo(bbox) -> Tuple[float, float]:
    """
    Punto que representa al vehículo para decidir en qué zona está.

    Se usa el centro del borde INFERIOR de la caja, no el centroide: es
    donde el vehículo toca el pavimento. Con el centroide, un tráiler alto
    en la calzada del fondo tiene su centro flotando sobre la calzada de
    enfrente y se atribuiría a la calzada equivocada.
    """
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2.0, y2)


def zone_for_point(zones: List[Dict], x: float, y: float) -> Optional[int]:
    """Id de la calzada que contiene el punto, o None si no cae en ninguna."""
    for z in zones:
        if z.get('kind') == 'calzada' and _contiene(z['points'], x, y):
            return z['id']
    return None


def zone_for_bbox(zones: List[Dict], bbox) -> Optional[int]:
    x, y = _punto_de_apoyo(bbox)
    return zone_for_point(zones, x, y)


def filter_detections(zones: List[Dict], detections: List[Dict]) -> List[Dict]:
    """
    Deja pasar solo lo que está sobre alguna calzada y fuera de las zonas
    de exclusión. Si no hay ninguna calzada dibujada no filtra nada: un
    proyecto sin zonas tiene que seguir comportándose como antes.
    """
    calzadas = [z for z in zones if z.get('kind') == 'calzada']
    excluir = [z for z in zones if z.get('kind') == 'excluir']
    if not calzadas and not excluir:
        return detections

    salida = []
    for d in detections:
        x, y = _punto_de_apoyo(d['bbox'])
        if any(_contiene(z['points'], x, y) for z in excluir):
            continue
        if calzadas and not any(_contiene(z['points'], x, y) for z in calzadas):
            continue
        salida.append(d)
    return salida


def band_from_zones(zones: List[Dict], frame_height: int,
                    margin_ratio: float = 0.08) -> Optional[Tuple[int, int]]:
    """
    Franja vertical que cubre las calzadas dibujadas.

    El margen es menor que el de `band_from_lanes` porque una zona ya
    describe el área completa del vehículo, no solo la línea que cruza:
    no hace falta tanto colchón para el tráiler alto.
    """
    ys = [p[1] for z in zones if z.get('kind') == 'calzada' for p in z['points']]
    if not ys:
        return None
    margen = max(10, int(frame_height * margin_ratio))
    y0 = max(0, int(min(ys)) - margen)
    y1 = min(frame_height, int(max(ys)) + margen)
    if y1 - y0 >= frame_height * 0.9:
        return None
    return (y0, y1)


def draw_zones(frame: np.ndarray, zones: List[Dict],
               colores: Optional[Dict[int, tuple]] = None) -> np.ndarray:
    """Dibuja las zonas sobre el cuadro: relleno translúcido y contorno."""
    if cv2 is None or not zones:
        return frame
    capa = frame.copy()
    for i, z in enumerate(zones):
        pts = np.array(z['points'], dtype=np.int32).reshape((-1, 1, 2))
        color = (colores or {}).get(z['id']) or _color(i, z.get('kind'))
        cv2.fillPoly(capa, [pts], color)
        cv2.polylines(frame, [pts], True, color, 1, cv2.LINE_AA)
    cv2.addWeighted(capa, 0.22, frame, 0.78, 0, frame)
    for i, z in enumerate(zones):
        pts = np.array(z['points'], dtype=np.int32)
        x, y = int(pts[:, 0].mean()), int(pts[:, 1].min())
        cv2.putText(frame, z['name'][:22], (x - 30, max(10, y - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.34, _color(i, z.get('kind')),
                    1, cv2.LINE_AA)
    return frame


def _color(i: int, kind: Optional[str]) -> tuple:
    if kind == 'excluir':
        return (80, 80, 200)      # rojo apagado: aquí NO se cuenta
    paleta = [(255, 190, 70), (120, 235, 130), (235, 140, 235), (90, 200, 255)]
    return paleta[i % len(paleta)]
