"""
Métricas de ingeniería de tránsito derivadas de los conteos.

Todo se calcula a partir de los cruces ya registrados — no se re-procesa
video. La métrica central es el **Factor de Hora Pico (FHP)**, que es lo
que un ingeniero de tránsito calcula normalmente a mano a partir de una
hoja de aforo:

    FHP = VHMD / (N × q_max)

donde VHMD es el volumen de la hora de máxima demanda, q_max el conteo
del subperiodo más cargado dentro de esa hora, y N el número de
subperiodos que caben en la hora (4 si son de 15 min).

El FHP siempre es ≤ 1.0. Un valor cercano a 1.0 significa flujo parejo
durante toda la hora; por debajo de 0.85 el flujo es muy irregular
(picos concentrados) y las condiciones de operación de la vía varían
sustancialmente dentro de la misma hora — que es justo la razón por la
que los aforos se levantan en intervalos y no como un total de una hora.
"""

import datetime as _dt
from typing import Dict, List, Optional

from src.storage import traffic_db

# Umbral clásico: por debajo de esto el flujo se considera irregular.
FHP_FLUJO_IRREGULAR = 0.85


def _parse(ts: str) -> _dt.datetime:
    return _dt.datetime.fromisoformat(ts)


def _peak_hour(intervals: List[Dict], interval_minutes: int) -> Optional[Dict]:
    """
    Ventana deslizante de 60 minutos con el mayor volumen. Devuelve la
    hora de máxima demanda y el FHP calculado sobre ella.

    Si los intervalos no cubren una hora completa no se puede calcular un
    FHP honesto, y se devuelve None en vez de un número inventado sobre
    datos parciales.
    """
    per_hour = 60 // interval_minutes
    if per_hour < 2 or len(intervals) < per_hour:
        return None

    best_start = 0
    best_volume = -1
    for i in range(len(intervals) - per_hour + 1):
        window = intervals[i:i + per_hour]
        volume = sum(iv["total"] for iv in window)
        if volume > best_volume:
            best_volume = volume
            best_start = i

    window = intervals[best_start:best_start + per_hour]
    q_max = max(iv["total"] for iv in window)

    # Con volumen cero no hay pico que medir; devolver FHP=0 sería
    # afirmar "flujo perfectamente irregular", que no es cierto.
    fhp = (best_volume / (per_hour * q_max)) if q_max > 0 else None

    return {
        "start": window[0]["start"],
        "end": window[-1]["end"],
        "volume": best_volume,
        "peak_interval_volume": q_max,
        "peak_interval_start": next(iv["start"] for iv in window if iv["total"] == q_max),
        "fhp": round(fhp, 3) if fhp is not None else None,
        "flujo_irregular": (fhp is not None and fhp < FHP_FLUJO_IRREGULAR),
        "subperiodos": per_hour,
    }


def get_project_metrics(project_id: int, interval_minutes: int = 15) -> Dict:
    """
    Resumen completo de un proyecto: totales, composición vehicular,
    reparto direccional, hora de máxima demanda y FHP — por carril y
    para el proyecto entero.
    """
    report = traffic_db.get_interval_counts(project_id, interval_minutes)
    lanes = report.get("lanes", [])

    lane_metrics = []
    totals = {"in": 0, "out": 0, "total": 0}
    composition: Dict[str, int] = {}

    for lane in lanes:
        intervals = lane["intervals"]
        lane_total = sum(iv["total"] for iv in intervals)
        lane_in = sum(iv["in"] for iv in intervals)
        lane_out = sum(iv["out"] for iv in intervals)

        lane_composition: Dict[str, int] = {}
        for iv in intervals:
            for vtype, counts in iv.get("by_vehicle_type", {}).items():
                n = counts.get("in", 0) + counts.get("out", 0)
                lane_composition[vtype] = lane_composition.get(vtype, 0) + n
                composition[vtype] = composition.get(vtype, 0) + n

        totals["in"] += lane_in
        totals["out"] += lane_out
        totals["total"] += lane_total

        lane_metrics.append({
            "lane_id": lane["lane_id"],
            "lane_name": lane["lane_name"],
            "total": lane_total,
            "in": lane_in,
            "out": lane_out,
            "composition": lane_composition,
            "peak_hour": _peak_hour(intervals, report["interval_minutes"]),
            "intervals": intervals,
        })

    # La hora pico del proyecto se calcula sobre el flujo agregado de
    # todos los carriles, no sumando los picos de cada uno: los carriles
    # pueden picar en momentos distintos y sumarlos inflaría el pico.
    combined = []
    if lanes:
        for idx in range(len(lanes[0]["intervals"])):
            slot = lanes[0]["intervals"][idx]
            combined.append({
                "start": slot["start"],
                "end": slot["end"],
                "in": sum(l["intervals"][idx]["in"] for l in lanes),
                "out": sum(l["intervals"][idx]["out"] for l in lanes),
                "total": sum(l["intervals"][idx]["total"] for l in lanes),
            })

    return {
        "interval_minutes": report["interval_minutes"],
        "totals": totals,
        "composition": composition,
        "composition_pct": {
            vtype: round(100 * n / totals["total"], 1)
            for vtype, n in composition.items()
        } if totals["total"] else {},
        "peak_hour": _peak_hour(combined, report["interval_minutes"]),
        "combined_intervals": combined,
        "lanes": lane_metrics,
    }
