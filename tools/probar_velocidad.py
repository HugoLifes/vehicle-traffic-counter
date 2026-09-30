"""
Regresión sin GPU de la velocidad por tramo (`src/engine/velocidad.py`).

Lo que no se puede romper:

1. **El instante del cruce se interpola entre cuadros.** A 20 cuadros por
   segundo y un tramo de 8.5 m, un cuadro de error son 5 km/h a 60 km/h.
2. **Da igual el sentido**: el vehículo que viene y el que se va.
3. **Lo imposible no se publica** (fuera de 3–160 km/h), pero se guarda el
   tiempo: al corregir la distancia puede volverse válido.
4. **Una hora con menos del 70 % medido no se publica.** De noche, hacia la
   cámara, los faros cortaban el recorrido y los pocos medidos no
   representaban al resto.
5. **El control de la distancia no da falsas alarmas con la cámara de
   frente** y sí atrapa una distancia mal capturada con la de lado. La
   primera versión medía entre los puntos medios de las líneas y el Excel
   del aforo frontal decía que los autos medirían 3.46 m.

    python tools/probar_velocidad.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.engine.velocidad import (FRACCION_MINIMA, MedidorVelocidad,  # noqa: E402
                                  control_distancia, horas_representativas, kmh_de)

fallos = 0


def comprobar(ok, que):
    global fallos
    print(("ok   " if ok else "MAL  ") + que)
    fallos += 0 if ok else 1


def recorrido(y0, paso, cuadros, x=1000, alto=120, ancho=180, tid=1):
    """Caja cuyo borde inferior (el punto de apoyo) va de y0 a y0+paso*n."""
    for f in range(cuadros):
        yb = y0 + paso * f
        yield f, [{"id": tid, "bbox": (x - ancho / 2, yb - alto, x + ancho / 2, yb)}]


# Líneas como las del aforo frontal: horizontales, conteo en 960, tramo en 870.
A = [(600, 960), (1400, 960)]
B = [(600, 870), (1400, 870)]


def medir(y0, paso, cuadros, distancia=9.0, fps=20.0):
    med = MedidorVelocidad(A, B, distancia, fps)
    out = []
    for f, tracks in recorrido(y0, paso, cuadros):
        out += med.observar(f, tracks)
    return out


# --- 1 y 2. Interpolación y sentido ------------------------------------------
m = medir(803, 7, 40)   # cruza 870 en el cuadro 9.571 y 960 en el 22.429
esperado = 9.0 / ((960 - 870) / 7 / 20.0) * 3.6
comprobar(len(m) == 1 and abs(m[0]["kmh"] - esperado) < 0.05,
          f"viene hacia la cámara: {m[0]['kmh'] if m else None:.2f} km/h, esperado {esperado:.2f} (entre cuadros)")
m2 = medir(1027, -7, 40)
comprobar(len(m2) == 1 and abs(m2[0]["kmh"] - esperado) < 0.05,
          "se aleja: la misma velocidad")
m3 = medir(900, 5, 30)   # arranca pasada la segunda línea: solo cruza la de conteo
comprobar(m3 == [], "si no cruzó las dos líneas no hay medición")

# --- 3. Lo imposible -----------------------------------------------------------
med = MedidorVelocidad(A, B, 9.0, 20.0)
med.observar(0, [{"id": 7, "bbox": (900, 700, 1100, 850)}])
salto = med.observar(1, [{"id": 7, "bbox": (900, 850, 1100, 1000)}])   # 150 px en un cuadro
comprobar(len(salto) == 1 and salto[0]["kmh"] is None and not salto[0]["valida"]
          and salto[0]["segundos"] > 0,
          "un rastro que brinca las dos líneas en un cuadro sale inválido, con su tiempo guardado")
comprobar(kmh_de(9.0, 0.5) == 64.8 and kmh_de(9.0, 0.01) is None and kmh_de(9.0, 20) is None,
          "fuera de 3–160 km/h no hay velocidad")

# --- 4. Horas representativas --------------------------------------------------
cruces = {(1, "2026-09-19 22"): 10, (1, "2026-09-19 23"): 10}
medidos = {(1, "2026-09-19 22"): 7, (1, "2026-09-19 23"): 6}
validas = horas_representativas(cruces, medidos)
comprobar((1, "2026-09-19 22") in validas and (1, "2026-09-19 23") not in validas,
          f"se publica con {FRACCION_MINIMA:.0%} medido o más, y no con menos")

# --- 5. Control de la distancia -----------------------------------------------
autos = [125.0] * 30
comprobar(control_distancia(autos, [(200, 960), (980, 960)], [(612, 870), (1179, 870)],
                            8.82)["estado"] == "no_aplica",
          "cámara de frente (líneas horizontales, corridas de lado): el control no aplica")
lateral = control_distancia([15.5] * 30, [(520, 192), (520, 260)], [(632, 188), (632, 250)], 11.2)
comprobar(lateral["estado"] == "coherente" and 1.4 <= lateral["alto_auto_m"] <= 1.7,
          f"cámara de lado con la distancia buena: auto de {lateral['alto_auto_m']} m, coherente")
mal = control_distancia([15.5] * 30, [(520, 192), (520, 260)], [(632, 188), (632, 250)], 26.3)
comprobar(mal["estado"] == "revisar", f"con la distancia mal capturada: auto de {mal['alto_auto_m']} m, revisar")

print(f"\n{fallos} fallos")
sys.exit(1 if fallos else 0)
