"""
Velocidad por tramo: dos líneas sobre el pavimento y la distancia entre ellas.

Es el mismo principio del contador de ejes: dos mangueras a una distancia
conocida (183 cm en el de Juárez) y el tiempo que tarda el eje en pasar de
una a otra. Aquí las mangueras son dos líneas dibujadas sobre el cuadro y el
eje es el punto de apoyo del vehículo (centro del borde inferior de la caja,
el mismo que usan el contador y las zonas).

Por qué dos líneas y no una escala de metros por píxel: en perspectiva la
escala cambia a lo largo de la vía (en Juárez la misma calzada mide 34 px de
alto en x=210 y 71 px en x=519). Con dos líneas no hace falta modelar la
cámara: el vehículo recorre la distancia medida en el pavimento, sea cual
sea el número de píxeles que ocupe en la imagen. Lo único que hay que medir
es esa distancia, en campo con cinta o sobre el mapa satelital.

Lo que el contador de ejes enseñó sobre esa distancia: el equipo ote-pte de
Juárez tenía mal capturada la separación y reportó 93 km/h de media en una
avenida urbana, con los automóviles clasificados como camiones de dos ejes
(el mismo error estira la distancia entre ejes). Un error en la distancia
escala TODAS las velocidades por el mismo factor y no da ningún aviso. Por
eso la distancia se pide explícita y se guarda junto al tramo.
"""

from typing import Dict, List, Optional, Sequence, Tuple

Punto = Tuple[float, float]

# Fuera de este rango la medición es un rastro mal armado, no un vehículo:
# un rastro que salta de un vehículo a otro atraviesa el tramo en dos
# cuadros. Sirve de control, como pide la PT-914.
MIN_KMH = 3.0
MAX_KMH = 160.0

# Un rastro que no se ve en tantos cuadros se olvida. El rastreador propio
# borra a los 30; se deja margen para no perder a uno que reaparece.
OLVIDAR_CUADROS = 60


def punto_de_apoyo(bbox) -> Punto:
    x1, _y1, x2, y2 = bbox
    return ((x1 + x2) / 2.0, float(y2))


def _lado(a: Punto, b: Punto, p: Punto) -> float:
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def fraccion_cruce(p0: Punto, p1: Punto, a: Punto, b: Punto) -> Optional[float]:
    """En qué fracción del paso p0 → p1 se cruza el segmento a-b, o None.

    Devuelve s en (0, 1]: el cruce ocurre en p0 + s·(p1 − p0). La fracción es
    la que da la posición exacta entre dos cuadros. A 15 cuadros por segundo
    un automóvil a 40 km/h avanza 0.74 m por cuadro, y sin interpolar el
    error de tiempo en un tramo de 15 m sería de hasta 5 %.
    """
    d0, d1 = _lado(a, b, p0), _lado(a, b, p1)
    # Caer justo sobre la línea cuenta como cruce en ese paso (s = 1); el
    # paso siguiente, que arranca sobre ella, ya no.
    if d0 == 0 or (d1 != 0 and (d0 > 0) == (d1 > 0)):
        return None
    # El cruce tiene que caer dentro del segmento, no en su prolongación:
    # la línea de un tramo solo cubre su calzada. Si los dos extremos del
    # segmento quedan del mismo lado del paso, el paso no lo toca.
    e0, e1 = _lado(p0, p1, a), _lado(p0, p1, b)
    if e0 != 0 and e1 != 0 and (e0 > 0) == (e1 > 0):
        return None
    return d0 / (d0 - d1)


class MedidorVelocidad:
    """Mide la velocidad de cada rastro que atraviesa el tramo completo.

    `linea_a` y `linea_b` son segmentos [(x, y), (x, y)] en píxeles del cuadro;
    `distancia_m` es la distancia en el pavimento entre las dos, medida en el
    sentido de circulación. Vale para los dos sentidos: se mide el tiempo
    entre cruzar una y cruzar la otra, sin importar cuál fue primero.
    """

    def __init__(self, linea_a: Sequence[Punto], linea_b: Sequence[Punto],
                 distancia_m: float, fps: float):
        if distancia_m <= 0:
            raise ValueError('La distancia del tramo tiene que ser positiva')
        self.a = (tuple(linea_a[0]), tuple(linea_a[1]))
        self.b = (tuple(linea_b[0]), tuple(linea_b[1]))
        self.distancia_m = float(distancia_m)
        self.fps = float(fps)
        self._ultimo: Dict[int, Tuple[float, Punto]] = {}
        self._cruce_a: Dict[int, float] = {}
        self._cruce_b: Dict[int, float] = {}
        self._medidos: set = set()
        self.descartados = 0

    def observar(self, cuadro: int, tracks: List[Dict]) -> List[Dict]:
        """Avanza un cuadro. Devuelve las mediciones que se completaron en él:
        [{'track_id', 'kmh', 'segundos', 'cuadro', 'valida'}].

        Devuelve también las imposibles, marcadas con valida=False: lo que se
        guarda es el TIEMPO, y si la distancia estaba mal capturada, al
        corregirla una medición "imposible" puede resultar perfectamente
        normal."""
        listas = []
        for t in tracks:
            tid = t['id']
            p1 = punto_de_apoyo(t['bbox'])
            previo = self._ultimo.get(tid)
            self._ultimo[tid] = (cuadro, p1)
            if previo is None or tid in self._medidos:
                continue
            c0, p0 = previo
            for linea, cruces in ((self.a, self._cruce_a), (self.b, self._cruce_b)):
                if tid in cruces:
                    continue
                s = fraccion_cruce(p0, p1, *linea)
                if s is not None:
                    cruces[tid] = c0 + s * (cuadro - c0)
            if tid in self._cruce_a and tid in self._cruce_b:
                self._medidos.add(tid)
                segundos = abs(self._cruce_b[tid] - self._cruce_a[tid]) / self.fps
                kmh = kmh_de(self.distancia_m, segundos)
                valida = kmh is not None
                if not valida:
                    self.descartados += 1
                listas.append({'track_id': tid, 'kmh': kmh, 'segundos': segundos,
                               'cuadro': cuadro, 'valida': valida})
        self._olvidar(cuadro)
        return listas

    def _olvidar(self, cuadro: int):
        viejos = [tid for tid, (c, _p) in self._ultimo.items()
                  if cuadro - c > OLVIDAR_CUADROS]
        for tid in viejos:
            self._ultimo.pop(tid, None)
            self._cruce_a.pop(tid, None)
            self._cruce_b.pop(tid, None)
            self._medidos.discard(tid)


def kmh_de(distancia_m: float, segundos: Optional[float]) -> Optional[float]:
    """Velocidad del tiempo de paso por el tramo; None si es imposible.

    Se calcula al reportar y no al contar: la base guarda el tiempo, así que
    corregir una distancia mal capturada corrige todas las velocidades sin
    volver a procesar ningún video.
    """
    if not segundos or segundos <= 0 or not distancia_m:
        return None
    kmh = distancia_m / segundos * 3.6
    return kmh if MIN_KMH <= kmh <= MAX_KMH else None


def percentil(valores: List[float], q: float) -> Optional[float]:
    """Percentil con interpolación lineal, como numpy, sin depender de él."""
    if not valores:
        return None
    v = sorted(valores)
    k = (len(v) - 1) * q / 100.0
    i = int(k)
    if i + 1 >= len(v):
        return v[-1]
    return v[i] + (v[i + 1] - v[i]) * (k - i)


# Fraccion minima de los cruces de una hora que tienen que llegar a la
# segunda linea para publicar su velocidad. Medido en el aforo frontal de
# Cd. Juarez contra el contador de ejes, 12 horas por sentido: donde se
# midio al 75-96 % de los vehiculos el percentil 85 quedo a 0-5 km/h del
# tubo; de noche, hacia la camara, los faros parten el rastro entre las dos
# lineas, se midio al 21-50 % y el error subio a 8-10 km/h. Una velocidad
# sacada de los pocos que si llegan no representa al resto.
FRACCION_MINIMA = 0.70


def horas_representativas(cruces: Dict, medidos: Dict) -> set:
    """Claves (carril, hora) cuya velocidad se puede publicar.

    `cruces` y `medidos` cuentan, por la misma clave, los vehiculos que
    cruzaron la linea de conteo y los que ademas dieron una velocidad.
    """
    return {k for k, n in cruces.items()
            if n and medidos.get(k, 0) / n >= FRACCION_MINIMA}


def resumen(valores: List[float]) -> Dict:
    """Lo que pide un estudio de velocidad: media, mediana y percentil 85.

    El percentil 85 es el que se usa para fijar límites de velocidad: la
    velocidad que no rebasa el 85 % de los conductores.
    """
    if not valores:
        return {'n': 0, 'media': None, 'p15': None, 'p50': None, 'p85': None}
    return {
        'n': len(valores),
        'media': sum(valores) / len(valores),
        'p15': percentil(valores, 15),
        'p50': percentil(valores, 50),
        'p85': percentil(valores, 85),
    }


# --- Control de la distancia: el automóvil como regla -----------------------
#
# Un automóvil mide de 1.4 a 1.8 m de alto (sedán a camioneta). Con la
# distancia del tramo y lo que mide en píxeles el recorrido entre las dos
# líneas sale la escala, y con la escala, el alto de los automóviles. Si la
# distancia está mal capturada, los automóviles "miden" una altura imposible.
#
# Medido en Juárez con la distancia que da el contador de ejes bueno: los
# automóviles de la calzada del fondo salen de 1.39 m de alto y 3.8 m de
# largo. Con la distancia del contador ote-pte, que reportó 93 km/h, los de
# la cercana habrían salido de 4.1 m de alto: el control lo habría delatado.
#
# El margen es amplio a propósito. En una vista oblicua la escala horizontal
# y la vertical no son iguales (la misma población de automóviles salió en
# 1.39 m en una calzada y 1.54 m en la otra), y el alto se toma en la línea
# de conteo, no a la mitad del tramo. Sirve para atrapar un error grueso
# —metros por pies, 55 por 5.5—, no para calibrar.
ALTO_AUTO_MIN_M = 1.1
ALTO_AUTO_MAX_M = 2.1
MIN_AUTOS_CONTROL = 20
# Solo vale si el tramo corre de lado en la imagen. Si el vehículo viene
# hacia la cámara, el recorrido se acorta por la perspectiva y el alto no.
MAX_INCLINACION_GRADOS = 30


def control_distancia(altos_auto_px: List[float], linea_a: Sequence[Punto],
                      linea_b: Sequence[Punto], distancia_m: float) -> Dict:
    import math
    m1 = ((linea_a[0][0] + linea_a[1][0]) / 2, (linea_a[0][1] + linea_a[1][1]) / 2)
    m2 = ((linea_b[0][0] + linea_b[1][0]) / 2, (linea_b[0][1] + linea_b[1][1]) / 2)
    dx, dy = abs(m2[0] - m1[0]), abs(m2[1] - m1[1])
    largo_px = math.hypot(dx, dy)
    if largo_px == 0 or math.degrees(math.atan2(dy, dx)) > MAX_INCLINACION_GRADOS:
        return {'estado': 'no_aplica', 'alto_auto_m': None}
    altos = [a for a in altos_auto_px if a]
    if len(altos) < MIN_AUTOS_CONTROL:
        return {'estado': 'sin_datos', 'alto_auto_m': None}
    alto_m = percentil(altos, 50) * distancia_m / largo_px
    estado = 'coherente' if ALTO_AUTO_MIN_M <= alto_m <= ALTO_AUTO_MAX_M else 'revisar'
    return {'estado': estado, 'alto_auto_m': round(alto_m, 2)}
