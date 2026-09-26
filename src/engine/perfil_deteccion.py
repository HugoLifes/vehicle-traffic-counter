"""
Perfil de detección por proyecto: qué modelo, a qué resolución y con qué
umbrales se detecta en ESTA cámara.

Existe porque cada ajuste que se midió ayudaba en una cámara y estorbaba en
otra, y la plataforma solo tenía una configuración para todas:

- `input_size` 960 da los mismos vehículos que 1280 en la cámara frontal de
  Cd. Juárez (158 de 158, vehículo de 115–150 px en la línea) y ahorra ~15 %
  del tiempo; en la cámara de agosto, con el vehículo a 14 px, perdería la
  calzada del fondo.
- `nms_agnostico` (que ya era por proyecto, en su propia columna) borra
  vehículos distintos en el material viejo y quita cajas repetidas en el
  nuevo.
- Quitar las cajas anidadas: con la cámara frontal el frente de un autobús o
  el chasis de un tractor se detectaban aparte y se contaban como un auto
  más (9 de 16 pesados con otro cruce encimado, revisados a ojo). En una
  cámara lejana, un auto tapado por un camión puede caer dentro de su caja.

El perfil vive en `projects.perfil_deteccion` como JSON. Lo que no traiga se
queda como en `configs/platform.yaml`, así que un proyecto sin perfil cuenta
exactamente igual que antes:

    {"modelo": "models/yolo26s.pt", "input_size": 960,
     "umbral_clase": {"motorcycle": 0.15}, "quitar_anidadas": 0.9,
     "clasificador_pesados": "models/pesados_v1.pt"}

`clasificador_pesados` da la clase fina de los pesados en el equipo, sin
internet (ver src/engine/clasificador_pesados.py).
"""
import json
import logging
from typing import Dict, List, Optional

CLASES_VEHICULO = ("car", "motorcycle", "bus", "truck")
GRANDES = ("bus", "truck")


def leer(proyecto: Optional[Dict]) -> Dict:
    """El perfil del proyecto, validado. Un perfil ilegible se ignora con un
    aviso en vez de tumbar el video: contar con la configuración general es
    mejor que no contar."""
    crudo = (proyecto or {}).get("perfil_deteccion")
    if not crudo:
        return {}
    try:
        perfil = json.loads(crudo) if isinstance(crudo, str) else dict(crudo)
    except (TypeError, ValueError):
        logging.warning(f"perfil_deteccion ilegible en el proyecto {proyecto.get('id')}; se ignora")
        return {}
    limpio = {}
    if isinstance(perfil.get("modelo"), str) and perfil["modelo"].strip():
        limpio["modelo"] = perfil["modelo"].strip()
    if isinstance(perfil.get("input_size"), int) and 320 <= perfil["input_size"] <= 2560:
        limpio["input_size"] = perfil["input_size"]
    umbrales = {c: float(u) for c, u in (perfil.get("umbral_clase") or {}).items()
                if c in CLASES_VEHICULO and isinstance(u, (int, float)) and 0.01 <= u <= 0.99}
    if umbrales:
        limpio["umbral_clase"] = umbrales
    anidadas = perfil.get("quitar_anidadas")
    if isinstance(anidadas, (int, float)) and 0.5 <= anidadas <= 1.0:
        limpio["quitar_anidadas"] = float(anidadas)
    if isinstance(perfil.get("clasificador_pesados"), str) and perfil["clasificador_pesados"].strip():
        limpio["clasificador_pesados"] = perfil["clasificador_pesados"].strip()
    return limpio


def umbral_de_deteccion(perfil: Dict, umbral_general: float) -> float:
    """El detector corre al umbral más bajo que pida alguna clase; después
    `filtrar_por_clase` deja a cada una en el suyo. Bajar el umbral no cambia
    qué cajas fuertes sobreviven a la NMS (una caja solo suprime a las de
    menor confianza), así que las demás clases cuentan igual."""
    return min([umbral_general] + list(perfil.get("umbral_clase", {}).values()))


def filtrar_por_clase(detecciones: List[Dict], perfil: Dict,
                      umbral_general: float) -> List[Dict]:
    umbrales = perfil.get("umbral_clase")
    if not umbrales:
        return detecciones
    return [d for d in detecciones
            if d["confidence"] >= umbrales.get(d.get("class_name"), umbral_general)]


def quitar_anidadas(detecciones: List[Dict], contencion: float) -> List[Dict]:
    """Quita la caja que cae casi entera dentro de un autobús o camión al
    menos del doble de área: el frente del autobús, el chasis del tractor o
    el faro que de noche sale como "moto", detectados aparte.

    `contencion` es la fracción del área de la caja chica que tiene que
    quedar dentro de la grande.
    """
    grandes = [d for d in detecciones if d.get("class_name") in GRANDES]
    if not grandes:
        return detecciones
    fuera = set()
    for i, d in enumerate(detecciones):
        x1, y1, x2, y2 = d["bbox"]
        area = max(1.0, (x2 - x1) * (y2 - y1))
        for g in grandes:
            if g is d:
                continue
            gx1, gy1, gx2, gy2 = g["bbox"]
            if (gx2 - gx1) * (gy2 - gy1) < 2 * area:
                continue
            ix = max(0.0, min(x2, gx2) - max(x1, gx1))
            iy = max(0.0, min(y2, gy2) - max(y1, gy1))
            if ix * iy >= contencion * area:
                fuera.add(i)
                break
    return [d for i, d in enumerate(detecciones) if i not in fuera]
