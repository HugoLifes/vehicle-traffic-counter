"""
Regresión sin GPU del perfil de detección por proyecto
(`src/engine/perfil_deteccion.py`).

Lo que no se puede romper:

1. **Un proyecto sin perfil cuenta exactamente como antes.** Es la
   condición para poder desplegarlo sin recontar lo ya validado: los aforos
   del Jetson se contaron sin perfil y así tienen que seguir.
2. **Un perfil mal escrito no tumba el video**: se ignora lo ilegible y se
   cuenta con la configuración general.
3. **Bajar el umbral de una clase no toca a las demás.**
4. **Quitar anidadas quita el frente del autobús y no el auto de al lado.**
   Los casos de `ANIDADAS` salen de cajas reales de la cámara frontal
   (19-sep-2026), revisadas a ojo sobre el cuadro.

    python tools/probar_perfil_deteccion.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.engine import perfil_deteccion as pd  # noqa: E402

fallos = 0


def comprobar(ok, que):
    global fallos
    print(("ok   " if ok else "MAL  ") + que)
    fallos += 0 if ok else 1


def caja(clase, x1, y1, x2, y2, conf=0.8):
    return {"bbox": [x1, y1, x2, y2], "confidence": conf, "class_name": clase}


# --- 1. Sin perfil, todo igual ---------------------------------------------
dets = [caja("car", 0, 0, 100, 60, 0.9), caja("motorcycle", 200, 0, 240, 60, 0.3)]
comprobar(pd.leer({}) == {} and pd.leer({"perfil_deteccion": None}) == {},
          "un proyecto sin perfil da un perfil vacío")
comprobar(pd.umbral_de_deteccion({}, 0.25) == 0.25, "sin perfil el detector corre a 0.25")
comprobar(pd.filtrar_por_clase(dets, {}, 0.25) is dets, "sin perfil no se filtra nada")

# --- 2. Perfiles mal escritos -------------------------------------------------
comprobar(pd.leer({"id": 1, "perfil_deteccion": "{no es json"}) == {},
          "un JSON roto se ignora, no tumba el video")
raro = pd.leer({"perfil_deteccion": json.dumps({
    "input_size": 99999, "umbral_clase": {"motorcycle": 5, "person": 0.1, "car": 0.3},
    "quitar_anidadas": 0.2, "modelo": ""})})
comprobar(raro == {"umbral_clase": {"car": 0.3}},
          f"solo sobrevive lo válido (queda {raro})")
bueno = pd.leer({"perfil_deteccion": {"modelo": "models/yolo26s.pt", "input_size": 960,
                                      "umbral_clase": {"motorcycle": 0.15},
                                      "quitar_anidadas": 0.9}})
comprobar(bueno == {"modelo": "models/yolo26s.pt", "input_size": 960,
                    "umbral_clase": {"motorcycle": 0.15}, "quitar_anidadas": 0.9},
          "un perfil completo se lee tal cual")

# --- 3. Umbral por clase ------------------------------------------------------
perfil = {"umbral_clase": {"motorcycle": 0.10}}
comprobar(pd.umbral_de_deteccion(perfil, 0.25) == 0.10,
          "el detector corre al umbral más bajo del perfil")
dets = [caja("motorcycle", 0, 0, 40, 80, 0.12), caja("car", 100, 0, 200, 60, 0.20),
        caja("car", 300, 0, 400, 60, 0.26), caja("truck", 500, 0, 700, 200, 0.24)]
quedan = pd.filtrar_por_clase(dets, perfil, 0.25)
comprobar([d["confidence"] for d in quedan] == [0.12, 0.26],
          "la moto a 0.12 entra; el auto a 0.20 y el camión a 0.24 siguen fuera")

# --- 4. Cajas anidadas --------------------------------------------------------
autobus = caja("bus", 1000, 700, 1600, 960)
frente = caja("car", 1010, 830, 1140, 955)          # dentro del autobús
comprobar(pd.quitar_anidadas([autobus, frente], 0.9) == [autobus],
          "el frente del autobús detectado como auto se quita")
al_lado = caja("car", 1450, 800, 1700, 960)          # la mitad fuera del autobús
comprobar(len(pd.quitar_anidadas([autobus, al_lado], 0.9)) == 2,
          "el auto que pasa junto al autobús se queda")
dos_autos = [caja("car", 0, 0, 300, 200), caja("car", 20, 20, 120, 100)]
comprobar(len(pd.quitar_anidadas(dos_autos, 0.9)) == 2,
          "sin autobús ni camión no se quita nada, aunque se enciman")
camion_chico = caja("truck", 0, 0, 130, 130)
auto_casi_igual = caja("car", 5, 5, 125, 125)
comprobar(len(pd.quitar_anidadas([camion_chico, auto_casi_igual], 0.9)) == 2,
          "si la grande no dobla el área no es un pedazo: lo resuelve la NMS")

# --- 5. Rastros nacidos dentro de un pesado ---------------------------------
bus = dict(caja("bus", 1000, 700, 1600, 960), id=1)
comprobar(pd.nacio_dentro_de_pesado([1010, 830, 1140, 955], [bus], propio_id=2) == 1,
          "el frente que aparece dentro del autobús es un pedazo de él")
comprobar(pd.nacio_dentro_de_pesado([1450, 800, 1700, 960], [bus], propio_id=2) is None,
          "el auto que aparece a medias fuera del autobús es un vehículo")
comprobar(pd.nacio_dentro_de_pesado([1010, 830, 1140, 955], [dict(caja("car", 1000, 700, 1600, 960), id=1)],
                                    propio_id=2) is None,
          "dentro de un auto grande no cuenta: solo autobús o camión")
comprobar(pd.leer({"perfil_deteccion": {"quitar_nacidos_en_pesado": True}})
          == {"quitar_nacidos_en_pesado": True}, "la opción se lee del perfil")

# --- 6. Tipo de cámara (lo que se elige en la pantalla) ---------------------
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

raiz = Path(tempfile.mkdtemp())
(raiz / "models").mkdir()
for ruta in pd.MODELOS_CAMARA_GRANDE.values():
    (raiz / ruta).write_bytes(b"x")
nms, perfil = pd.aplicar_tipo_camara("grandes", None, raiz)
comprobar(nms and perfil == {**pd.MODELOS_CAMARA_GRANDE, "quitar_pedazos_de_pesado": True},
          "cámara de vehículos grandes: cajas entre clases, los dos clasificadores y pedazos de pesado")
nms, perfil = pd.aplicar_tipo_camara(
    "grandes", json.dumps({"umbral_clase": {"motorcycle": 0.1}}), raiz)
comprobar(perfil.get("umbral_clase") == {"motorcycle": 0.1} and "clasificador_pesados" in perfil,
          "elegir el tipo no borra lo demás del perfil (el umbral de motos)")
nms, perfil = pd.aplicar_tipo_camara("chicos", perfil, raiz)
comprobar(not nms and perfil == {"umbral_clase": {"motorcycle": 0.1}},
          "cámara de vehículos chicos: quita la comparación entre clases y los clasificadores")
vacia = Path(tempfile.mkdtemp())
nms, perfil = pd.aplicar_tipo_camara("grandes", None, vacia)
comprobar(nms and perfil == {"quitar_pedazos_de_pesado": True},
          "sin los modelos en el equipo no se piden clasificadores")
comprobar(pd.tipo_camara({"nms_agnostico": 1}) == "grandes"
          and pd.tipo_camara({"nms_agnostico": 0}) == "chicos", "el tipo se lee del proyecto")

# --- 7. Los clasificadores solo mandan donde la calzada da para clases finas
from src.engine.clasificador_pesados import clase_final, subtipo_final  # noqa: E402

comprobar(clase_final("PESADO", "T-S", 0.9, fino=False) == "PESADO",
          "en una calzada de vehículo chico el clasificador de pesados no cambia nada")
comprobar(clase_final("C", "T-S", 0.9, fino=True) == "T-S",
          "en una calzada fina decide qué pesado es")
comprobar(clase_final("A", "T-S", 0.9, fino=True) == "A",
          "nunca convierte un liviano en pesado: la frontera es la de la regla")
comprobar(clase_final("B", "TRACTOR", 0.4, fino=True) == "B",
          "con probabilidad baja se queda la regla")
comprobar(subtipo_final("PICKUP", 0.8, 13, (7, 19), fino=True) == "PICKUP"
          and subtipo_final("PICKUP", 0.8, 13, (7, 19), fino=False) == "SIN_SUBTIPO"
          and subtipo_final("PICKUP", 0.8, 21, (7, 19), fino=True) == "SIN_SUBTIPO",
          "el subtipo de A solo con calzada fina y con luz")

# Cajas reales de la cámara frontal, del mismo cuadro, revisadas a ojo.
# (grande, chica, es_pedazo, descripción)
ANIDADAS = []
ruta_casos = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "casos_anidadas_frontal.json")
if os.path.exists(ruta_casos):
    with open(ruta_casos, encoding="utf-8") as fh:
        ANIDADAS = json.load(fh)
for c in ANIDADAS:
    g = caja(c["grande"]["clase"], *c["grande"]["bbox"])
    ch = caja(c["chica"]["clase"], *c["chica"]["bbox"])
    quitada = len(pd.quitar_anidadas([g, ch], c.get("contencion", 0.9))) == 1
    comprobar(quitada == c["es_pedazo"],
              f"{c['descripcion']}: {'se quita' if quitada else 'se queda'}")

# Pedazos que viajan pegados al pesado. Recorridos sintéticos con la forma de
# los casos reales medidos (6-oct-2026): el frente del autobús va dentro de
# su caja todo el tiempo y en el mismo lugar; el auto que sale de detrás del
# tráiler nace dentro y se separa; el que rebasa al autobús va encimado pero
# se mueve respecto a él.


def recorrido(pp_, cuadros):
    for rastros in cuadros:
        pp_.observar(rastros)


def r_(id_, clase, x1, y1, x2, y2):
    return {"id": id_, "class_name": clase, "bbox": [x1, y1, x2, y2]}


pp = pd.PedazosDePesado()
recorrido(pp, [[r_(1, "bus", 300 + 8 * n, 700, 900 + 8 * n, 980),
                r_(2, "car", 320 + 8 * n, 830, 470 + 8 * n, 960)] for n in range(20)])
comprobar(pp.es_pedazo(2), "frente del autobús que viaja con él: pedazo")

pp = pd.PedazosDePesado()
recorrido(pp, [[r_(1, "truck", 100, 600, 900, 980),
                r_(2, "car", 600 + 25 * n, 850, 760 + 25 * n, 960)] for n in range(30)])
comprobar(not pp.es_pedazo(2), "auto que sale de detrás del tráiler: se cuenta")

pp = pd.PedazosDePesado()
recorrido(pp, [[r_(1, "bus", 300 + 5 * n, 700, 900 + 5 * n, 980),
                r_(2, "car", 300 + 15 * n, 840, 470 + 15 * n, 960)] for n in range(40)])
comprobar(not pp.es_pedazo(2), "auto que rebasa al autobús, encimado: se cuenta")

pp = pd.PedazosDePesado()
recorrido(pp, [[r_(2, "car", 600 + 10 * n, 850, 760 + 10 * n, 960)] for n in range(10)])
comprobar(not pp.es_pedazo(2) and not pp.es_pedazo(99),
          "sin pesado cerca, o rastro desconocido: se cuenta")

print(f"\n{fallos} fallos")
sys.exit(1 if fallos else 0)
