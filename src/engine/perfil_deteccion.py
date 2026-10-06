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
    horas = perfil.get("horas_subtipo")
    if (isinstance(horas, (list, tuple)) and len(horas) == 2
            and all(isinstance(h, int) and 0 <= h <= 24 for h in horas) and horas[0] < horas[1]):
        limpio["horas_subtipo"] = (horas[0], horas[1])
    if perfil.get("quitar_nacidos_en_pesado") is True:
        limpio["quitar_nacidos_en_pesado"] = True
    if perfil.get("quitar_pedazos_de_pesado") is True:
        limpio["quitar_pedazos_de_pesado"] = True
    for clave in ("clasificador_pesados", "clasificador_livianos"):
        if isinstance(perfil.get(clave), str) and perfil[clave].strip():
            limpio[clave] = perfil[clave].strip()
    # Rectángulo [x1, y1, x2, y2] del cuadro original que se difumina en el
    # video con detecciones: la leyenda de la cámara frontal dice otra fecha y
    # otra hora (revisar_reloj.py) y contradice la hora real del encabezado.
    tapar = perfil.get("tapar_leyenda")
    if (isinstance(tapar, (list, tuple)) and len(tapar) == 4
            and all(isinstance(v, (int, float)) and v >= 0 for v in tapar)
            and tapar[2] > tapar[0] and tapar[3] > tapar[1]):
        limpio["tapar_leyenda"] = [int(v) for v in tapar]
    return limpio


# --- Tipo de cámara: lo que se elige al crear el proyecto -------------------
#
# Quien levanta un aforo no sabe qué es "NMS agnóstica" ni tiene terminal,
# pero sí sabe si en su cámara el vehículo se ve grande o chico. Hasta la
# beta, todo lo validado del aforo frontal (cajas repetidas entre clases y
# clasificadores propios) solo se encendía con curl, así que un proyecto nuevo
# desde la pantalla salía sin tractocamión ni tractor, sin automóvil /
# camioneta / pickup, y con la misma camioneta contada como auto y como
# camión. Cada tipo aplica exactamente lo que se validó con esa cámara:
#
# - "grandes" (de frente o cercana, como la de Cd. Juárez del 19-sep):
#   comparar cajas entre clases y los dos clasificadores. Los clasificadores
#   solo mandan donde la calzada da para clases finas
#   (clasificador_pesados.clase_final), así que equivocarse de tipo no
#   inventa clases en una cámara lejana.
# - "chicos" (lejana o de lado, como la de agosto): ni lo uno ni lo otro;
#   ahí comparar entre clases borra vehículos distintos que se enciman.
MODELOS_CAMARA_GRANDE = {"clasificador_pesados": "models/pesados_v1.pt",
                         "clasificador_livianos": "models/livianos_v3.pt"}
TIPOS_CAMARA = ("grandes", "chicos")


def aplicar_tipo_camara(tipo: str, perfil_actual, raiz) -> tuple:
    """(nms_agnostico, perfil) para un tipo de cámara, conservando lo demás
    del perfil que ya tenga el proyecto (un umbral de motos, un modelo)."""
    from pathlib import Path
    if tipo not in TIPOS_CAMARA:
        raise ValueError(f"Tipo de cámara desconocido: {tipo}")
    perfil = leer({"perfil_deteccion": perfil_actual}) if perfil_actual else {}
    if isinstance(perfil.get("horas_subtipo"), tuple):
        perfil["horas_subtipo"] = list(perfil["horas_subtipo"])
    if tipo == "grandes":
        for clave, ruta in MODELOS_CAMARA_GRANDE.items():
            # Solo si el modelo está en el equipo: un clasificador que falta
            # no detiene el conteo, pero sí llena el registro de errores.
            if clave not in perfil and (Path(raiz) / ruta).exists():
                perfil[clave] = ruta
        # Medido solo con vehículos de 115-150 px (cámara frontal): ver
        # PedazosDePesado.
        perfil.setdefault("quitar_pedazos_de_pesado", True)
        return True, perfil
    for clave in MODELOS_CAMARA_GRANDE:
        perfil.pop(clave, None)
    perfil.pop("quitar_pedazos_de_pesado", None)
    return False, perfil


def tipo_camara(proyecto: Optional[Dict]) -> str:
    """El tipo que corresponde a lo que ya tiene el proyecto."""
    return "grandes" if (proyecto or {}).get("nms_agnostico") else "chicos"


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


def nacio_dentro_de_pesado(caja, rastros: List[Dict], propio_id=None,
                           contencion: float = 0.8) -> Optional[int]:
    """Id del autobús o camión dentro del cual APARECE un rastro, o None.

    Un pedazo de pesado (su frente, el chasis, un faro) nace cuando el
    pesado ya está encima, casi entero dentro de su caja. NO basta para
    decidir, y por eso `quitar_nacidos_en_pesado` va apagado: un auto que
    sale de detrás de un tráiler también nace dentro de él. En 58 minutos
    escogidos por tener dobles conteos quitó 8 pedazos; en 12 minutos sin
    escoger (el de más pesados de cada hora) quitó 6 cruces y 5 eran autos
    reales, revisados en su cuadro exacto (27-sep-2026).
    """
    x1, y1, x2, y2 = caja
    area = max(1.0, (x2 - x1) * (y2 - y1))
    for r in rastros:
        if r.get("id") == propio_id or r.get("class_name") not in GRANDES:
            continue
        gx1, gy1, gx2, gy2 = r["bbox"]
        if (gx2 - gx1) * (gy2 - gy1) < 2 * area:
            continue
        ix = max(0.0, min(x2, gx2) - max(x1, gx1))
        iy = max(0.0, min(y2, gy2) - max(y1, gy1))
        if ix * iy >= contencion * area:
            return r.get("id")
    return None


class PedazosDePesado:
    """El rastro que VIAJA pegado a un autobús o camión no es un vehículo:
    es su frente, su chasis o un faro detectados aparte.

    Lo que lo distingue de un auto real no es dónde nace —un auto que sale de
    detrás de un tráiler también nace dentro de él, y por eso "nació dentro"
    borraba autos reales— sino lo que pasa DESPUÉS: el pedazo pasa casi toda
    su vida dentro de la caja del MISMO pesado y en el mismo lugar relativo a
    ella; el auto real se separa o se mueve respecto a él.

    Regla, al cruzar la línea: ≥ 60 % de sus cuadros dentro (≥ 0.8 de su
    caja) de un mismo pesado del doble de área o más, y su centro se movió
    ≤ 0.45 (suma de los rangos en x e y, en fracciones de la caja del pesado).

    Medido por el camino de producción sobre 70 minutos del frontal (58 con
    dobles conteos conocidos, 12 sin escoger), 6-oct-2026: quita 7 cruces y
    los 7 son pedazos vistos en su cuadro exacto (frentes de autobús, la
    defensa de un tráiler, el chasis de un tractor, faros como moto); respeta
    los 12 autos reales etiquetados (7 junto al autobús, 5 que salen de
    detrás de un tráiler, los que "nació dentro" borraba) y no toca nada en
    los minutos normales. Se le escapan ~5 pedazos (la bomba de una pipa, que
    sobresale de la caja; chasis a medias): prefiere dejar un pedazo a borrar
    un auto.
    """

    FRACCION = 0.6
    MOVIMIENTO = 0.45
    CONTENCION = 0.8

    def __init__(self):
        self._vida: Dict[int, List] = {}

    def observar(self, rastros: List[Dict]):
        pesados = [r for r in rastros if r.get("class_name") in GRANDES]
        for r in rastros:
            x1, y1, x2, y2 = r["bbox"]
            area = max(1.0, (x2 - x1) * (y2 - y1))
            mejor = None
            for g in pesados:
                if g is r:
                    continue
                gx1, gy1, gx2, gy2 = g["bbox"]
                if (gx2 - gx1) * (gy2 - gy1) < 2 * area:
                    continue
                ix = max(0.0, min(x2, gx2) - max(x1, gx1))
                iy = max(0.0, min(y2, gy2) - max(y1, gy1))
                frac = ix * iy / area
                if frac >= self.CONTENCION and (mejor is None or frac > mejor[1]):
                    mejor = (g, frac)
            if mejor is None:
                self._vida.setdefault(r["id"], []).append((None, None))
            else:
                gx1, gy1, gx2, gy2 = mejor[0]["bbox"]
                rel = (((x1 + x2) / 2 - gx1) / max(1.0, gx2 - gx1),
                       ((y1 + y2) / 2 - gy1) / max(1.0, gy2 - gy1))
                self._vida.setdefault(r["id"], []).append((mejor[0].get("id"), rel))

    def es_pedazo(self, rastro_id) -> bool:
        vida = self._vida.get(rastro_id) or []
        ids = [p for p, _ in vida if p is not None]
        if not ids:
            return False
        padre = max(set(ids), key=ids.count)
        con_padre = [rel for p, rel in vida if p == padre]
        if len(con_padre) < 2 or len(con_padre) / len(vida) < self.FRACCION:
            return False
        xs = [a for a, _ in con_padre]
        ys = [b for _, b in con_padre]
        return (max(xs) - min(xs)) + (max(ys) - min(ys)) <= self.MOVIMIENTO


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
