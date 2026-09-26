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

print(f"\n{fallos} fallos")
sys.exit(1 if fallos else 0)
