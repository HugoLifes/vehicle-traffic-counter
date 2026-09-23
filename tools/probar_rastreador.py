"""
Regresión del rastreador y del contador, con cajas sintéticas y sin GPU.

Cada caso reproduce un defecto que se coló a producción y costó conteos
equivocados. Corre en un segundo:

    python tools/probar_rastreador.py

1. **Rastros partidos por la ausencia multiplicada.** `predict()` se llamaba
   dentro del doble ciclo detección × rastro, así que con D vehículos en
   pantalla el contador de ausencias subía D por cuadro y un vehículo que el
   detector perdía unos cuadros se borraba en 30/D en vez de 30.
2. **Dos rastros del mismo vehículo.** Una detección cuyo mejor
   emparejamiento quedaba por debajo del umbral de IoU entraba dos veces a
   la lista de "sin pareja" y creaba dos rastros. En la cámara nueva de Cd.
   Juárez eso contó una pickup dos veces en el mismo segundo.
3. **Antiduplicado del contador a escala.** El umbral de 6 px se midió sobre
   video de 640×360; con 2560×1440 el mismo vehículo mide 150 px y sus cajas
   duplicadas quedan a 20-40 px de distancia.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.counter import BidirectionalCounter     # noqa: E402
from src.tracker import VehicleTracker           # noqa: E402


def caja(x, y, ancho, alto):
    return [x - ancho / 2, y - alto / 2, x + ancho / 2, y + alto / 2]


def deteccion(x, y, ancho=60, alto=40, clase=2, conf=0.9):
    return {'bbox': caja(x, y, ancho, alto), 'confidence': conf,
            'class_id': clase, 'class_name': 'car'}


def sin_partirse_con_la_via_llena(vehiculos=15, perdidos=5):
    """Un vehículo perdido unos cuadros no puede cambiar de identidad porque
    haya OTROS vehículos en pantalla."""
    trk = VehicleTracker(max_age=30, min_hits=3, iou_threshold=0.3)
    ids = {}
    for cuadro in range(40):
        dets = []
        for v in range(vehiculos):
            if v == 0 and 20 <= cuadro < 20 + perdidos:
                continue        # al primero lo pierde el detector unos cuadros
            dets.append(deteccion(100 + 8 * cuadro, 100 + 60 * v))
        for tr in trk.update(dets):
            if abs(tr['bbox'][1] - (100 - 20)) < 30:      # el vehículo 0
                ids.setdefault(cuadro, tr['id'])
    vistos = set(ids.values())
    return len(vistos), vistos


def un_rastro_por_vehiculo():
    """Un vehículo que salta (IoU bajo con su propio rastro) crea UN rastro
    nuevo, no dos.

    El rastro viejo sigue vivo unos cuadros, y eso está bien: lo que se
    cuenta aquí son los rastros que quedan SOBRE el vehículo.
    """
    trk = VehicleTracker(max_age=30, min_hits=1, iou_threshold=0.3)
    trk.update([deteccion(100, 300)])
    trk.update([deteccion(108, 300)])
    # Salto grande: el mejor emparejamiento queda por debajo del umbral.
    trk.update([deteccion(400, 300)])
    encima = [tr for tr in trk.tracks
              if abs((tr.bbox[0] + tr.bbox[2]) / 2 - 400) < 40]
    return len(encima)


def la_clase_la_decide_el_rastro_entero():
    """La clase del vehículo sale del voto de todas sus detecciones, no de la
    primera.

    Un vehículo que entra al cuadro como una rebanada se detecta un instante
    como motocicleta; si esa clase se queda fija, se reporta como moto aunque
    el detector diga automóvil con 0.90 durante cien cuadros. Pasó en la
    cámara frontal de Cd. Juárez: 113 de 709 cruces de una calzada salieron
    como motocicleta y eran minivans, sedanes y hasta una pipa.
    """
    trk = VehicleTracker(max_age=30, min_hits=1, iou_threshold=0.3)
    primera = deteccion(300, 300, clase=3, conf=0.55)
    primera['class_name'] = 'motorcycle'
    trk.update([primera])
    for i in range(1, 12):
        d = deteccion(300 + 6 * i, 300, clase=2, conf=0.9)
        trk.update([d])
    return trk.tracks[0].class_name


def sin_doble_conteo_en_camara_grande():
    """Dos cajas del mismo vehículo, como las que deja un rastro partido, no
    cuentan dos veces en una cámara donde el vehículo mide 150 px."""
    contador = BidirectionalCounter(line_type='diagonal')
    contador.set_counting_line(line_type='diagonal', points=[(0, 960), (2000, 960)],
                               frame_shape=(1440, 2560))
    total = 0
    for cuadro in range(8):
        y = 880 + cuadro * 25
        tracks = [
            {'id': 1, 'bbox': caja(800, y, 220, 150), 'class_name': 'car', 'confidence': 0.9,
             'trajectory': [(800, y - 25 * k) for k in range(4)]},
            {'id': 2, 'bbox': caja(815, y + 12, 250, 187), 'class_name': 'car', 'confidence': 0.4,
             'trajectory': [(815, y + 12 - 25 * k) for k in range(4)]},
        ]
        r = contador.update(tracks)
        total += len(r['in']) + len(r['out'])
    return total


def main():
    fallos = 0

    n, ids = sin_partirse_con_la_via_llena()
    print(f'Vía llena, vehículo perdido 5 cuadros: {n} identidad(es) {sorted(ids)}')
    if n != 1:
        print('MAL  el vehículo cambió de identidad por culpa de los demás')
        fallos += 1

    n = un_rastro_por_vehiculo()
    print(f'Vehículo que salta: {n} rastro(s)')
    if n != 1:
        print('MAL  una detección sin pareja creó más de un rastro')
        fallos += 1

    clase = la_clase_la_decide_el_rastro_entero()
    print(f'Clase tras 11 cuadros de automóvil y 1 de moto: {clase}')
    if clase != 'car':
        print('MAL  la clase se quedó con la del primer cuadro')
        fallos += 1

    n = sin_doble_conteo_en_camara_grande()
    print(f'Dos cajas del mismo vehículo a 150 px: {n} conteo(s)')
    if n != 1:
        print('MAL  el mismo vehículo se contó más de una vez')
        fallos += 1

    print()
    print(f'4 casos, {fallos} fallos')
    return 1 if fallos else 0


if __name__ == '__main__':
    sys.exit(main())
