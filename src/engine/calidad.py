"""
Calidad del seguimiento de un aforo direccional: qué parte de los vehículos
se vio entrar Y salir, en un número que se lea solo y con su color.

Por qué. OpenTrafficCam da por video cuántos rastros quedaron asignados a un
movimiento, cuántos cruzaron una sección sin quedar asignados y cuántos ni
cruzaron (ver docs/IDEAS_DE_OTRAS_HERRAMIENTAS.md). Aquí los datos ya
existían —completos e incompletos en `movimientos`— pero nadie los resumía, y
Blvd. Independencia costó 4 h de proceso antes de saber que no servía.

Los cortes están medidos en los cinco direccionales con resultado conocido,
fracción de vehículos con origen y destino contra lo que dio el conteo a mano:

    Calle terracería           89 %   103 %, 6 de 6 movimientos con GEH < 5
    Entrada y salida Altozano  66 %   97 % por trayectoria
    Blvd. Independencia        56 %   no pasa (el puente tapa dos accesos)
    Gómez Morín                36 %   46 % (640x360, calzada lejana invisible)
    Fraccionamiento             4 %   cordón: sale por las líneas, 93 %

Son cinco escenas: el color avisa, no autoriza. Lo que valida un aforo sigue
siendo el conteo a mano (validacion_od.py).

En un cordón de líneas (traffic_db.es_cordon) el número no aplica: los
movimientos que la cámara no sigue de punta a punta se miden con la línea de
su calle a propósito, y un 4 % ahí no es una falla.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional

VERDE = 0.60
AMBAR = 0.45
# Un video con menos movimientos no dice nada de su fracción.
MIN_POR_VIDEO = 20


def color_de(fraccion: Optional[float]) -> str:
    if fraccion is None:
        return "gris"
    if fraccion >= VERDE:
        return "verde"
    if fraccion >= AMBAR:
        return "ambar"
    return "rojo"


def resumir(movs: List[Dict], nombres: Dict[int, str], videos: Dict[int, Dict],
            cordon: bool) -> Dict:
    """`movs`: {job_id, origen_id, destino_id}. `nombres`: acceso -> nombre.
    `videos`: job_id -> {nombre, hora}."""
    total = len(movs)
    completos = sum(1 for m in movs if m["origen_id"] is not None and m["destino_id"] is not None)
    fraccion = completos / total if total else None

    acc = defaultdict(lambda: {"entran": 0, "salen": 0, "sin_destino": 0, "sin_origen": 0})
    for m in movs:
        o, d = m["origen_id"], m["destino_id"]
        if o is not None:
            acc[o]["entran"] += 1
            if d is None:
                acc[o]["sin_destino"] += 1
        if d is not None:
            acc[d]["salen"] += 1
            if o is None:
                acc[d]["sin_origen"] += 1
    por_acceso = []
    for a, v in acc.items():
        vistos = v["entran"] + v["salen"]
        perdidos = v["sin_destino"] + v["sin_origen"]
        por_acceso.append({"acceso_id": a, "nombre": nombres.get(a, f"Acceso {a}"), **v,
                           "perdidos": round(perdidos / vistos, 3) if vistos else None})
    por_acceso.sort(key=lambda x: x["nombre"])

    pv = defaultdict(lambda: [0, 0])
    for m in movs:
        pv[m["job_id"]][1] += 1
        if m["origen_id"] is not None and m["destino_id"] is not None:
            pv[m["job_id"]][0] += 1
    por_video = [{"job_id": j, **videos.get(j, {}), "total": t, "fraccion": round(c / t, 3)}
                 for j, (c, t) in pv.items() if t >= MIN_POR_VIDEO]
    por_video.sort(key=lambda x: x["fraccion"])

    if cordon:
        color = "gris"
        texto = ("Cordón de líneas: los movimientos que la cámara no sigue de punta a punta se "
                 "miden con la línea de su calle, así que esta fracción no dice si el aforo sirve. "
                 "Lo dice el conteo a mano.")
    elif fraccion is None:
        color, texto = "gris", "Todavía no hay movimientos contados."
    else:
        color = color_de(fraccion)
        texto = {
            "verde": "La cámara sigue a la mayoría de los vehículos de un acceso a otro. Así salieron "
                     "los aforos que cuadraron con el conteo a mano.",
            "ambar": "Se pierde a muchos vehículos entre la entrada y la salida. Revisa en la tabla qué "
                     "acceso los pierde y, en Calibrar, el mapa de recorridos: puede ser un acceso mal "
                     "dibujado o algo que tapa la vía.",
            "rojo": "La cámara no sigue a la mayoría de los vehículos de punta a punta. Con esta "
                    "fracción los aforos medidos no cuadraron con el conteo a mano; no entregues la "
                    "matriz sin compararla antes.",
        }[color]
    return {"total": total, "completos": completos,
            "fraccion": round(fraccion, 3) if fraccion is not None else None,
            "color": color, "cordon": cordon, "texto": texto,
            "por_acceso": por_acceso, "peores_videos": por_video[:5],
            "cortes": {"verde": VERDE, "ambar": AMBAR}}
