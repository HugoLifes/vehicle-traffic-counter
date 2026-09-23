"""
Regresion de la clasificacion vehicular, sin GPU y en un segundo.

    python tools/probar_clasificacion.py

Cada caso es un vehiculo REAL de los que se revisaron recorte por recorte en
el aforo frontal de Cd. Juarez (`hoja_cruces.py --clase`), con su alto y su
ancho medidos: las cinco trocas, los seis camiones y los cuatro autobuses que
salieron 15 de 15, mas las motos y el unico falso positivo de moto que
aparecio en 133.

Lo que cuida esta regresion, y por que cada cosa costo trabajo saberla:

  · **Que la camara vieja siga saliendo igual.** El aforo de 15 px esta
    validado contra el conteo manual de la empresa y no se puede mover. Sin
    perfil, o en una calzada que no da para clases finas, la respuesta tiene
    que ser exactamente la de antes: A / PESADO.
  · **Que el corte de la moto sea RELATIVO a la silueta del automovil.** La
    razon ancho/alto depende del angulo: 1.69 en una calzada del aforo
    frontal y 1.37 en la otra. Un corte fijo falla en una de las dos.
  · **Que una troca sea A.** En la taxonomia SCT la pickup es un automovil.
    Contarla como pesada fue lo que hizo declarar 1 501 camiones donde el
    aforo manual conto 417.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.engine.clasificacion import (AUTOBUS, CAMION, LIVIANO, MOTO,   # noqa: E402
                                      MULTIPLO, PESADO, SIN_RESOLVER,
                                      clasificar, perfil_de_calzada)

# Las dos calzadas del aforo frontal, medidas sobre 10 146 cruces.
CERCA = {"fino": True, "alto_auto": 126.0, "razon_auto": 1.69}
LEJOS = {"fino": True, "alto_auto": 123.0, "razon_auto": 1.37}
# La camara vieja: automovil de 15 px en la calzada del fondo.
VIEJA = {"fino": False, "alto_auto": 15.0, "razon_auto": None}

U_CERCA = MULTIPLO * 126.0      # 199 px
U_LEJOS = MULTIPLO * 123.0      # 194 px
U_VIEJA = MULTIPLO * 15.0       # 24 px

CASOS = [
    # (nombre, tipo_coco, alto, ancho, umbral, perfil, esperado)
    # --- las cinco trocas de la hoja, calzada que se aleja -----------------
    ("RAM roja",              "truck", 167, 228, U_LEJOS, LEJOS, LIVIANO),
    ("GMC blanca",            "truck", 153, 211, U_LEJOS, LEJOS, LIVIANO),
    ("pickup negra",          "truck", 165, 194, U_LEJOS, LEJOS, LIVIANO),
    ("Ford Sport Trac roja",  "truck", 162, 205, U_LEJOS, LEJOS, LIVIANO),
    ("F-150 roja",            "truck", 150, 221, U_LEJOS, LEJOS, LIVIANO),
    # --- los seis pesados de la hoja, calzada hacia la camara --------------
    ("Freightliner de caja",  "truck", 313, 518, U_CERCA, CERCA, CAMION),
    ("International con caja", "truck", 310, 547, U_CERCA, CERCA, CAMION),
    ("volteo Scania",         "truck", 254, 408, U_CERCA, CERCA, CAMION),
    ("tractocamion blanco",   "truck", 309, 533, U_CERCA, CERCA, CAMION),
    ("tractocamion con caja", "truck", 312, 536, U_CERCA, CERCA, CAMION),
    ("tractocamion plataforma", "truck", 308, 526, U_CERCA, CERCA, CAMION),
    # --- los cuatro autobuses de la hoja -----------------------------------
    ("autobus escolar 1",     "bus", 245, 361, U_LEJOS, LEJOS, AUTOBUS),
    ("autobus escolar 2",     "bus", 254, 293, U_LEJOS, LEJOS, AUTOBUS),
    ("autobus escolar 3",     "bus", 240, 353, U_LEJOS, LEJOS, AUTOBUS),
    ("autobus Senda Citi",    "bus", 257, 352, U_LEJOS, LEJOS, AUTOBUS),
    # --- motos --------------------------------------------------------------
    ("moto, calzada cercana", "motorcycle", 90, 73, U_CERCA, CERCA, MOTO),
    ("moto, calzada lejana",  "motorcycle", 81, 56, U_LEJOS, LEJOS, MOTO),
    # El unico de 133: ancho de automovil, asi que NO es moto.
    ("'moto' ancha como auto", "motorcycle", 147, 182, U_CERCA, CERCA, LIVIANO),
    # Sin ancho guardado (cruces de antes de capturarlo) se cree a COCO.
    ("moto sin ancho",        "motorcycle", 88, None, U_CERCA, CERCA, MOTO),
    # --- automoviles --------------------------------------------------------
    ("sedan",                 "car", 123, 168, U_LEJOS, LEJOS, LIVIANO),
    ("SUV alta",              "car", 170, 210, U_LEJOS, LEJOS, LIVIANO),
    # --- la camara vieja no se mueve ----------------------------------------
    ("camion, camara vieja",  "truck", 40, None, U_VIEJA, VIEJA, PESADO),
    ("autobus, camara vieja", "bus", 60, None, U_VIEJA, VIEJA, PESADO),
    ("pickup, camara vieja",  "truck", 19, None, U_VIEJA, VIEJA, LIVIANO),
    ("moto, camara vieja",    "motorcycle", 12, None, U_VIEJA, VIEJA, LIVIANO),
    # --- sin perfil: exactamente el comportamiento anterior -------------------
    ("camion sin perfil",     "truck", 313, 518, U_CERCA, None, PESADO),
    ("autobus sin perfil",    "bus", 245, 361, U_CERCA, None, PESADO),
    ("moto sin perfil",       "motorcycle", 90, 73, U_CERCA, None, LIVIANO),
    # --- calzada que no resuelve ---------------------------------------------
    ("sin umbral",            "truck", 313, 518, None, CERCA, SIN_RESOLVER),
    ("truck sin alto",        "truck", None, None, U_CERCA, CERCA, SIN_RESOLVER),
]


def probar_perfil():
    """El perfil sale de los cruces, y tiene que decidir `fino` por el alto."""
    fallos = 0
    frontal = [{"vehicle_type": "car", "bbox_height": 124, "bbox_width": 170}] * 40
    p = perfil_de_calzada(frontal)
    if not p["fino"]:
        print("MAL  el automovil de 124 px tendria que dar clases finas")
        fallos += 1
    vieja = [{"vehicle_type": "car", "bbox_height": 15, "bbox_width": None}] * 40
    if perfil_de_calzada(vieja)["fino"]:
        print("MAL  el automovil de 15 px NO puede dar clases finas")
        fallos += 1
    # Pocos automoviles: no hay escala y no se inventa una.
    if perfil_de_calzada(frontal[:10])["fino"]:
        print("MAL  con 10 automoviles no hay escala para nada")
        fallos += 1
    if not fallos:
        print("ok  el perfil decide por el alto del automovil, no por la clase")
    return fallos


def main():
    fallos = 0
    for nombre, tipo, alto, ancho, umbral, perfil, esperado in CASOS:
        got = clasificar(tipo, alto, umbral, ancho=ancho, perfil=perfil)
        marca = "ok  "
        if got != esperado:
            marca, fallos = "MAL ", fallos + 1
        medida = f"{alto}x{ancho}px" if ancho else f"{alto}px"
        print(f"{marca}{nombre:26} {medida:>11}  ->  {got:12} "
              f"(esperado {esperado})")
    print()
    fallos += probar_perfil()
    print()
    print(f"{len(CASOS)} casos, {fallos} fallos")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
