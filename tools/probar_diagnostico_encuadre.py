"""
Regresión del diagnóstico de encuadre, sin GPU y en un segundo.

Los casos son los que se midieron de verdad en el Jetson sobre el material
de la empresa (16-sep-2026): las cifras de abajo salieron de
`medir_imagen` y `medir_rastreo`, no están inventadas. Sirven para que un
cambio de umbrales se pueda comprobar contra los aforos cuyo resultado ya
se conoce, en vez de volver a gastar horas de GPU.

Se comprueban dos cosas:
  1. cada caso conserva su color, y
  2. **ningún puntaje bajo se queda sin explicación**: si el video no sale
     "bueno", tiene que haber al menos un aviso concreto. Pasó lo contrario
     (Fraccionamientos 06:46, 49/100 sin un solo aviso) porque los avisos
     tenían umbrales más duros que el puntaje.

    python tools/probar_diagnostico_encuadre.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.engine.diagnostico_encuadre import (calificar, calificar_rastreo,   # noqa: E402
                                             combinar, resumen_texto)

GENERICO = 'En aforo direccional'

# nombre, medidas de la etapa por imagen, medidas de la etapa por rastreo,
# color esperado, qué se sabe del aforo por haberlo contado de verdad. Las
# de rastreo vienen redondeadas como las imprime la herramienta.
CASOS = [
    ('Entrada Altozano 07:26',
     dict(alto_mediana=43, alto_p25=27, pct_bajo_20px=10, confianza=0.64,
          brillo=141, nitidez=2859, detecciones_por_cuadro=5.0),
     dict(rastros=26, concentracion=87, borde=38, partidos_pct=42),
     'verde', 'sirvió: movimiento dominante con GEH 3.9'),

    ('Entrada Altozano 07:56 (por la API)',
     dict(alto_mediana=33.7, alto_p25=18.6, pct_bajo_20px=33, confianza=0.61,
          brillo=142, nitidez=3099, detecciones_por_cuadro=3.3),
     dict(rastros=21, concentracion=81.0, borde=33.3, partidos_pct=52.4),
     'ambar', 'sirvió, pero aquí la cola chica baja a 19 px'),

    ('Entrada Altozano 06:56 (amanecer)',
     dict(alto_mediana=10.8, alto_p25=10.7, pct_bajo_20px=60, confianza=0.56,
          brillo=148, nitidez=1960, detecciones_por_cuadro=0.5),
     dict(rastros=0, concentracion=0, borde=0, partidos_pct=0),
     'rojo', 'a esa hora no se ve nada: 11 px y 0.5 detecciones por cuadro'),

    ('Glorieta Altozano 07:14',
     dict(alto_mediana=29, alto_p25=21, pct_bajo_20px=23, confianza=0.51,
          brillo=130, nitidez=2288, detecciones_por_cuadro=14.9),
     dict(rastros=78, concentracion=62, borde=1, partidos_pct=10),
     'rojo', 'falló: la glorieta queda fuera de cuadro'),

    ('Altozano y Blvd Ind 07:49 (640x360)',
     dict(alto_mediana=22, alto_p25=14, pct_bajo_20px=48, confianza=0.55,
          brillo=129, nitidez=4601, detecciones_por_cuadro=5.0),
     dict(rastros=80, concentracion=77, borde=25, partidos_pct=10),
     'rojo', 'mismo límite de tamaño que el aforo de Cd. Juárez'),

    ('Fraccionamientos 07:26 (calle tranquila)',
     dict(alto_mediana=30, alto_p25=24, pct_bajo_20px=14, confianza=0.71,
          brillo=148, nitidez=1298, detecciones_por_cuadro=2.1),
     dict(rastros=5, concentracion=80, borde=50, partidos_pct=0),
     'ambar', 'pocos rastros por poco tránsito, no por el encuadre'),

    ('Fraccionamientos 06:46',
     dict(alto_mediana=39, alto_p25=17, pct_bajo_20px=27, confianza=0.78,
          brillo=149, nitidez=1180, detecciones_por_cuadro=1.5),
     dict(rastros=11, concentracion=86, borde=41, partidos_pct=0),
     'rojo', 'se ve grande de cerca y baja a 17 px al fondo'),

    ('Blvd Independencia 17:04',
     dict(alto_mediana=36, alto_p25=27, pct_bajo_20px=13, confianza=0.58,
          brillo=145, nitidez=2611, detecciones_por_cuadro=12.7),
     dict(rastros=63, concentracion=66, borde=28, partidos_pct=13),
     'ambar', 'FALLÓ y el diagnóstico no lo ve: el puente tapa dos accesos'),
]


def main():
    fallos = 0
    for nombre, m, r, color_esperado, nota in CASOS:
        imagen = calificar(m, direccional=True)
        rastreo = dict(r, **calificar_rastreo(r, m.get('detecciones_por_cuadro')))
        d = combinar(imagen, rastreo)
        concretos = [a for a in d['avisos'] if not a.startswith(GENERICO)]

        marca = 'ok  '
        if d['color'] != color_esperado:
            marca, fallos = 'MAL ', fallos + 1
        # Un puntaje que no llega a "bueno" sin un solo aviso concreto deja
        # al usuario sin saber qué cambiar de la cámara.
        if d['color'] != 'verde' and not concretos:
            marca, fallos = 'MAL ', fallos + 1
            nota += '  <-- sin ningún aviso concreto'

        print(f"{marca}{nombre:<40} {resumen_texto(d):<70} {nota}")
        for a in concretos:
            print(f"        · {a}")

    # Sin el dato de la etapa por imagen, pocos rastros siguen siendo
    # "no sirve": es como se comportaban las llamadas viejas.
    sin_dato = calificar_rastreo(dict(rastros=3, concentracion=50, borde=10, partidos_pct=0), None)
    if sin_dato.get('puntaje') != 0:
        print('MAL  sin detecciones_por_cuadro deberia seguir siendo "no sirve"')
        fallos += 1

    print()
    print(f'{len(CASOS)} casos, {fallos} fallos')
    return 1 if fallos else 0


if __name__ == '__main__':
    sys.exit(main())
