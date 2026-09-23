"""
Regresión del conteo por trayectoria, con cajas sintéticas y sin GPU.

Cada caso es una situación real del aforo por sección, con la respuesta que
tiene que dar. Corre en un segundo:

    python tools/probar_conteo_trayectoria.py

Los dos errores que se cazan aquí van en sentidos opuestos, y por eso hace
falta medir los dos a la vez:

  · contar de más — el rastro se parte o cambia de identidad sobre la línea;
  · contar de menos — dos vehículos que se siguen de cerca se fusionan en uno
    al unir los pedazos.

Los umbrales de la unión (0.5 s de hueco, 0.8 altos de caja) salieron de
estos casos: con los del aforo direccional (1 s y 2 altos, medidos con
vehículos más lentos) dos vehículos separados por medio segundo se fusionan.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.engine.conteo_trayectoria import contar, resumen   # noqa: E402

LINEA = [{'id': 1, 'puntos': [(0, 960), (2000, 960)], 'zone_id': None}]
FPS = 20.0


def caja(cuadro, x, y, alto=150, ancho=220):
    """Un vehículo con su punto de apoyo en (x, y)."""
    return (cuadro, x - ancho / 2, y - alto, x + ancho / 2, y)


def bajando(ids_y_cuadros, x=800, y0=860, paso=25):
    """Vehículo que baja por el cuadro cruzando y=960."""
    return {tid: [caja(c, x, y0 + (c - cuadros[0]) * paso + desplaza)
                  for c in cuadros]
            for tid, (cuadros, desplaza) in ids_y_cuadros.items()}


CASOS = [
    ('un vehículo entero',
     {7: [caja(i, 800, 860 + i * 25) for i in range(10)]}, 1),

    ('rastro partido justo en la línea',
     {7: [caja(i, 800, 860 + i * 25) for i in range(4)],
      9: [caja(i, 800, 860 + i * 25) for i in range(5, 10)]}, 1),

    ('tapado 0.4 s y reaparece',
     {7: [caja(i, 800, 660 + i * 25) for i in range(8)],
      9: [caja(i, 800, 660 + i * 25) for i in range(16, 22)]}, 1),

    ('dos vehículos separados',
     {7: [caja(i, 800, 860 + i * 25) for i in range(10)],
      8: [caja(i, 500, 700 + i * 25) for i in range(16)]}, 2),

    ('dos vehículos pegados, medio segundo',
     {7: [caja(i, 800, 860 + i * 25) for i in range(10)],
      8: [caja(i, 800, 610 + i * 25) for i in range(10, 24)]}, 2),

    ('dos vehículos pegados, un segundo',
     {7: [caja(i, 800, 860 + i * 25) for i in range(10)],
      8: [caja(i, 800, 360 + i * 25) for i in range(20, 34)]}, 2),

    ('no llega a la línea',
     {7: [caja(i, 800, 700 + i * 8) for i in range(10)]}, 0),

    ('estacionado encima de la línea',
     {7: [caja(i, 800, 960 + (i % 2) * 2 - 1) for i in range(40)]}, 0),

    ('vehículo en sentido contrario',
     {7: [caja(i, 800, 1100 - i * 25) for i in range(12)]}, 1),
]


def main():
    fallos = 0
    for nombre, rastros, esperado in CASOS:
        r = resumen(contar(rastros, LINEA, FPS))[1]
        marca = 'ok  '
        if r['total'] != esperado:
            marca, fallos = 'MAL ', fallos + 1
        print(f"{marca}{nombre:38} contó {r['total']} (esperado {esperado})   "
              f"in={r['in']} out={r['out']}")

    # Los dos sentidos tienen que salir distintos, o el reparto direccional
    # del reporte no significa nada.
    bajando_ = resumen(contar({7: [caja(i, 800, 860 + i * 25) for i in range(10)]},
                              LINEA, FPS))[1]
    subiendo = resumen(contar({7: [caja(i, 800, 1100 - i * 25) for i in range(12)]},
                              LINEA, FPS))[1]
    if bajando_['in'] == subiendo['in']:
        print('MAL  los dos sentidos se registran igual')
        fallos += 1

    # El cruce tiene que traer la CAJA del cuadro en que cruzó. Del ancho
    # sale la silueta, que es lo que separa una troca de un automóvil; de la
    # esquina sale el recorte del vehículo. Si se pierde, la clasificación
    # se queda sin la mitad de la silueta y nadie se entera.
    #
    # Se prueba con el rastro PARTIDO porque ahí está la trampa: el cuadro
    # del cruce pertenece a uno solo de los pedazos de la cadena.
    partido = contar({7: [caja(i, 800, 860 + i * 25, ancho=220) for i in range(4)],
                      9: [caja(i, 800, 860 + i * 25, ancho=310) for i in range(5, 10)]},
                     LINEA, FPS)[1]
    c = partido[0]['caja'] if partido else None
    ancho = (c[2] - c[0]) if c else None
    if ancho != 310:
        print(f'MAL  el ancho del cruce salió {ancho} y el del pedazo que '
              f'cruzó es 310')
        fallos += 1
    elif c[0] != 800 - 310 / 2:
        print(f'MAL  la esquina de la caja salió en x={c[0]} y el vehículo '
              f'va por x=800')
        fallos += 1
    else:
        print(f"ok  caja del cruce                    {ancho:.0f} px de ancho "
              f"en x={c[0]:.0f} (del pedazo que cruzó)")

    print()
    print(f'{len(CASOS)} casos, {fallos} fallos')
    return 1 if fallos else 0


if __name__ == '__main__':
    sys.exit(main())
