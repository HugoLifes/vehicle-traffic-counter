"""
Aforo direccional: de dónde viene y a dónde va cada vehículo.

El aforo por línea responde "cuántos pasaron por aquí". El direccional
responde "cuántos entraron por el norte y salieron por el oriente", que es
lo que pide un estudio de intersección (vueltas izquierda, derecha, de
frente y en U, por acceso).

Cómo se decide
--------------
Cada acceso de la intersección es una zona de tipo ``acceso`` dibujada en
la calibración. Un vehículo tiene:

  · **origen**  — la primera zona de acceso que pisa su punto de apoyo;
  · **destino** — la última zona de acceso que pisa DESPUÉS de haber salido
    del origen. Exigir la salida es lo que distingue una vuelta en U (sale
    al centro y regresa a su acceso) de un vehículo que se quedó formado en
    su acceso y nunca cruzó.

Es el enfoque por recorrido de zonas de la literatura, y la versión en
polígono de las "puertas" de entrada y salida que usan los productos
comerciales. Con polígonos y no con líneas porque a esta resolución el
rastro nace tarde: un vehículo que el detector ve por primera vez ya dentro
del acceso no cruzó ninguna línea de entrada, pero sí está en la zona.

Rastros partidos
----------------
Es el error dominante del conteo por movimiento: un vehículo tapado por
otro reaparece con otro identificador y queda como dos movimientos a
medias — uno sin destino y otro sin origen. Por eso los movimientos NO se
deciden en vivo sino al cerrar el video, cuando se conocen todos los
rastros y se pueden unir los pedazos (``unir_pedazos``).
"""

import math
from collections import Counter
from typing import Dict, List, Optional, Tuple

from src.engine.zones import _contiene, _punto_de_apoyo

# Cuántos puntos se guardan por rastro. Un vehículo tarda de 5 a 20 s en
# cruzar una intersección; a 15 fps son hasta 300 cuadros, y para decidir
# origen, destino y unir pedazos basta con conservar uno de cada pocos.
CADA_N_CUADROS = 2


def acceso_de_punto(accesos: List[Dict], x: float, y: float) -> Optional[int]:
    for z in accesos:
        if _contiene(z['points'], x, y):
            return z['id']
    return None


def firma_color(frame, bbox) -> Optional[Tuple[float, float, float]]:
    """
    Color medio del vehículo en Lab, sobre el centro de la caja.

    Sirve para no unir dos pedazos de rastro de vehículos distintos. En Blvd
    Ind, con tránsito cruzado, las uniones equivocadas que se vieron a ojo
    eran casi todas de colores obviamente distintos: camioneta blanca con
    auto oscuro, autobús con pickup, oscuro con amarillo. La posición, el
    tamaño y la dirección no los separan; el color sí.

    Se toma el 60 % central de la caja para no promediar el pavimento que
    asoma por las orillas. Lab y no RGB porque la distancia en Lab se parece
    a la diferencia de color que ve una persona.
    """
    import cv2
    x1, y1, x2, y2 = bbox
    w, h = x2 - x1, y2 - y1
    X1, X2 = int(max(0, x1 + 0.2 * w)), int(min(frame.shape[1], x2 - 0.2 * w))
    Y1, Y2 = int(max(0, y1 + 0.2 * h)), int(min(frame.shape[0], y2 - 0.2 * h))
    if X2 - X1 < 2 or Y2 - Y1 < 2:
        return None
    lab = cv2.cvtColor(frame[Y1:Y2, X1:X2], cv2.COLOR_BGR2LAB).reshape(-1, 3)
    m = lab.mean(axis=0)
    return (float(m[0]), float(m[1]), float(m[2]))


def distancia_color(a, b) -> Optional[float]:
    if a is None or b is None:
        return None
    return math.dist(a, b)


def _mediana_color(colores):
    if not colores:
        return None
    return tuple(sorted(c[i] for c in colores)[len(colores) // 2] for i in range(3))


class Rastro:
    __slots__ = ('id', 'puntos', 'clases', 'confianzas', 'colores')

    def __init__(self, tid):
        self.id = tid
        # (cuadro, x, y, alto_caja, acceso o None)
        self.puntos: List[Tuple[int, float, float, float, Optional[int]]] = []
        self.clases: Counter = Counter()
        self.confianzas: List[float] = []
        # Firmas de color muestreadas a lo largo del rastro, en orden.
        self.colores: List[Tuple[float, float, float]] = []

    def color_inicio(self):
        return _mediana_color(self.colores[:5])

    def color_fin(self):
        # Mediana de las últimas 5 y no la última: justo antes de perderse
        # detrás de un obstáculo la caja ya incluye al obstáculo (en Altozano,
        # un letrero amarillo) y su color deja de ser el del vehículo.
        return _mediana_color(self.colores[-5:])


def _tramos(puntos, min_fuera: int):
    """
    Comprime la secuencia en tramos [acceso, cuadro_inicio, cuadro_fin].

    Una salida al centro más corta que ``min_fuera`` cuadros entre dos
    tramos del MISMO acceso se funde con ellos: es el punto de apoyo
    temblando en el borde de la zona, no un vehículo que salió y volvió.
    Sin esto, cada temblor contaría como una vuelta en U.
    """
    tramos = []
    for f, *_, acc in puntos:
        if tramos and tramos[-1][0] == acc:
            tramos[-1][2] = f
        else:
            tramos.append([acc, f, f])
    fundidos = []
    for t in tramos:
        if (len(fundidos) >= 2 and fundidos[-1][0] is None
                and fundidos[-2][0] == t[0] and t[0] is not None
                and fundidos[-1][2] - fundidos[-1][1] < min_fuera):
            fundidos.pop()
            fundidos[-1][2] = t[2]
        else:
            fundidos.append(t)
    return fundidos


def recorrido(puntos, min_fuera: int = 15) -> Tuple[Optional[int], Optional[int]]:
    """
    Origen y destino de una secuencia de puntos.

    Casos, con X e Y accesos y · el centro de la intersección:
      X · Y  → X a Y          X · X  → vuelta en U en X
      X      → X sin destino (se quedó en la fila o se perdió ahí)
      X ·    → X sin destino (se perdió en el centro)
      · X    → sin origen, destino X (pedazo nacido en el centro)

    Para que "· X" signifique pedazo y no un vehículo que apareció antes de
    llegar a su acceso, las zonas de acceso tienen que llegar hasta donde el
    vehículo aparece por primera vez: la orilla de la imagen.
    """
    tramos = _tramos(puntos, min_fuera)
    accesos = [t for t in tramos if t[0] is not None]
    if not accesos:
        return None, None
    if tramos[0][0] is None and len(accesos) == 1 and tramos[-1][0] is not None:
        return None, accesos[0][0]
    origen = accesos[0][0]
    despues = tramos[tramos.index(accesos[0]) + 1:]
    posteriores = [t for t in despues if t[0] is not None]
    return origen, (posteriores[-1][0] if posteriores else None)


def _alto_de_extremo(puntos, al_final: bool, n: int = 5) -> float:
    """
    Alto del vehículo en un extremo del rastro: el MAYOR de los últimos (o
    primeros) n puntos, no el del punto extremo.

    Justo antes de perderse detrás de un obstáculo, y justo al reaparecer,
    la caja cubre solo la parte visible del vehículo y se encoge. Medido en
    Entrada y salida Altozano con ByteTrack: comparando un solo punto por
    extremo, 15 de 68 pares muerte-nacimiento se rechazaban por tamaño.
    """
    tramo = puntos[-n:] if al_final else puntos[:n]
    return max(p[3] for p in tramo)


# Parámetros de unión, medidos en Entrada y salida Altozano (5 min, ByteTrack,
# accesos dibujados), verificando a ojo cada unión recortada del video con
# tools/hoja_uniones.py:
#
#   hueco  tolerancia  tamaño    completos  uniones que juntan vehículos distintos
#   2 s    1.2 altos   0.6-1.6   47 %       —
#   1 s    2.0 altos   0.5-2.0   71 %       2 claras + 3 dudosas de 53
#   3 s    3.0 altos   0.5-2.0   75 %       ~5 claras + ~5 dudosas de 48
#
# Los errores se concentran en huecos largos (16-41 cuadros): pasado un
# segundo, el que reaparece suele ser OTRO vehículo. Por eso 1 s y no 3.
HUECO_MAX_S = 1.0
TOLERANCIA_ALTOS = 2.0
RANGO_TAMANO = (0.5, 2.0)


def unir_pedazos(rastros: List[Rastro], fps: float,
                 max_hueco_s: float = HUECO_MAX_S, tolerancia: float = TOLERANCIA_ALTOS,
                 rango_tamano: Tuple[float, float] = RANGO_TAMANO,
                 uniones: Optional[List] = None,
                 max_delta_color: Optional[float] = None,
                 hueco_detenido_s: Optional[float] = None) -> List[List[Rastro]]:
    """
    Encadena rastros sin destino con rastros sin origen que nacen poco
    después donde el primero habría llegado.

    Un pedazo "sin origen" es el que nace fuera de toda zona de acceso, o
    dentro de la misma zona donde murió el otro (el vehículo formado en la
    fila que alguien tapó un momento).

    Emparejamiento voraz por costo creciente, cada pedazo una sola vez. La
    tolerancia se mide en altos de caja para que valga igual cerca y lejos
    de la cámara.
    """
    info = {r.id: recorrido(r.puntos) for r in rastros}
    sin_destino = [r for r in rastros if info[r.id][1] is None and len(r.puntos) >= 2]
    hueco = max(1, int(max_hueco_s * fps))
    # Vehículo DETENIDO (formado en la fila del semáforo): otro lo tapa más
    # de un segundo y reaparece en el mismo sitio cuando la fila avanza. En
    # Blvd Ind casi todos los rastros sin destino morían dentro de los
    # accesos, no en el centro. Se le permite un hueco más largo, pero solo
    # si el nuevo nace casi en el mismo punto: en una fila el vehículo de
    # atrás avanza al menos un largo de auto, así que 0.35 altos de caja
    # separa "el mismo, reapareciendo" de "el siguiente, que tomó su lugar".
    hueco_detenido = int(hueco_detenido_s * fps) if hueco_detenido_s else 0

    def velocidad(puntos):
        k = min(len(puntos) - 1, 4)
        if k < 1:
            return 0.0, 0.0
        f1, x1, y1 = puntos[0][:3]
        f2, x2, y2 = puntos[k][:3]
        df = max(1, f2 - f1)
        return (x2 - x1) / df, (y2 - y1) / df

    pares = []
    for a in sin_destino:
        fa, xa, ya, _, acc_a = a.puntos[-1]
        ha = _alto_de_extremo(a.puntos, al_final=True)
        vx, vy = velocidad(a.puntos[-1 - min(len(a.puntos) - 1, 4):])
        rapidez_a = math.hypot(vx, vy)
        for b in rastros:
            if b is a or not b.puntos:
                continue
            fb, xb, yb, _, acc_b = b.puntos[0]
            hb = _alto_de_extremo(b.puntos, al_final=False)
            dt = fb - fa
            if dt <= 0:
                continue
            # Quieto: se mueve menos del 15 % de su alto por segundo.
            detenido = rapidez_a * fps <= 0.15 * ha
            largo = dt > hueco
            if largo and not (detenido and dt <= hueco_detenido):
                continue
            if acc_b is not None and acc_b != acc_a:
                continue       # nace dentro de OTRO acceso: es un origen legítimo
            if not rango_tamano[0] <= hb / max(ha, 1) <= rango_tamano[1]:
                continue
            escala = max(ha, hb, 1)
            if largo:
                cerca = math.hypot(xb - xa, yb - ya)
                if cerca > 0.35 * escala:
                    continue
                # Sin dirección que comparar (estaba quieto); el costo va por
                # encima de cualquier unión normal para no robarle su pareja.
                pares.append((a.id, b.id, 1.0 + cerca / (0.35 * escala) + dt / hueco_detenido))
                continue
            ex, ey = xa + vx * dt, ya + vy * dt
            dist = min(math.hypot(xb - ex, yb - ey), math.hypot(xb - xa, yb - ya))
            # La incertidumbre crece con el hueco: en una vuelta la
            # predicción en línea recta se abre con cada cuadro tapado.
            limite = tolerancia * escala + 0.5 * rapidez_a * dt
            if dist > limite:
                continue
            # Dos vehículos que se cruzan en el centro van en direcciones
            # distintas; el pedazo que sigue a otro va hacia el mismo lado.
            # Solo se exige si ambos se mueven: uno detenido en la fila no
            # tiene dirección que comparar.
            ubx, uby = velocidad(b.puntos)
            rapidez_b = math.hypot(ubx, uby)
            coseno = 0.0
            if rapidez_a > 0.5 and rapidez_b > 0.5:
                coseno = (vx * ubx + vy * uby) / (rapidez_a * rapidez_b)
                if coseno < -0.3:
                    continue
            costo_par = dist / limite + 0.5 * dt / hueco - 0.3 * coseno
            if max_delta_color is not None:
                dcol = distancia_color(a.color_fin(), b.color_inicio())
                if dcol is not None:
                    if dcol > max_delta_color:
                        continue   # otro color: otro vehículo
                    costo_par += 0.5 * dcol / max_delta_color
            pares.append((a.id, b.id, costo_par))

    # Asignación óptima global y no voraz: cuando dos vehículos se tapan a
    # la vez, la unión más barata para uno puede robarle al otro la suya.
    siguiente = {}
    if pares:
        from scipy.optimize import linear_sum_assignment
        ids_a = sorted({p[0] for p in pares}, key=str)
        ids_b = sorted({p[1] for p in pares}, key=str)
        ia = {v: i for i, v in enumerate(ids_a)}
        ib = {v: i for i, v in enumerate(ids_b)}
        import numpy as np
        costo = np.full((len(ids_a), len(ids_b)), 1e6)
        for ida, idb, c in pares:
            costo[ia[ida], ib[idb]] = c
        filas, cols = linear_sum_assignment(costo)
        for f, c in zip(filas, cols):
            if costo[f, c] < 1e6:
                siguiente[ids_a[f]] = ids_b[c]
                if uniones is not None:
                    # Para verificar a ojo que los dos pedazos son el mismo
                    # vehículo: cuadro y caja del final de uno y del inicio
                    # del otro.
                    uniones.append((ids_a[f], ids_b[c]))
    usados_b = set(siguiente.values())

    por_id = {r.id: r for r in rastros}
    cadenas = []
    for r in rastros:
        if r.id in usados_b:
            continue
        cadena = [r]
        vistos = {r.id}
        while cadena[-1].id in siguiente and siguiente[cadena[-1].id] not in vistos:
            nxt = por_id[siguiente[cadena[-1].id]]
            cadena.append(nxt)
            vistos.add(nxt.id)
        cadenas.append(cadena)
    return cadenas


class AforoDireccional:
    """
    Acumula los rastros de un video y al cerrarlo entrega los movimientos.

        od = AforoDireccional(accesos, fps)
        for cuadro in video:
            od.observar(n, tracks)
        movimientos = od.cerrar()
    """

    def __init__(self, accesos: List[Dict], fps: float):
        self.accesos = [z for z in accesos if z.get('kind') == 'acceso']
        self.fps = fps or 15.0
        self._rastros: Dict[int, Rastro] = {}

    @property
    def activo(self) -> bool:
        return len(self.accesos) >= 2

    def observar(self, cuadro: int, tracks: List[Dict], frame=None):
        if not self.activo:
            return
        guardar = cuadro % CADA_N_CUADROS == 0
        for t in tracks:
            r = self._rastros.get(t['id'])
            if r is None:
                r = self._rastros[t['id']] = Rastro(t['id'])
            r.clases[t['class_name']] += 1
            r.confianzas.append(t['confidence'])
            # Color cada 5 cuadros: basta para la mediana de cada extremo y
            # no suma costo apreciable frente a la detección.
            if frame is not None and (len(r.confianzas) <= 5 or cuadro % 5 == 0):
                c = firma_color(frame, t['bbox'])
                if c is not None:
                    r.colores.append(c)
            x, y = _punto_de_apoyo(t['bbox'])
            acc = acceso_de_punto(self.accesos, x, y)
            # Siempre se guarda el primer punto y todo cambio de zona: son
            # los que deciden origen y destino. El resto, submuestreado.
            cambio = not r.puntos or r.puntos[-1][4] != acc
            if guardar or cambio:
                r.puntos.append((cuadro, x, y, t['bbox'][3] - t['bbox'][1], acc))
            elif r.puntos:
                # El último punto se actualiza siempre: es de donde parte la
                # predicción para unir este rastro con su continuación.
                r.puntos[-1] = (cuadro, x, y, t['bbox'][3] - t['bbox'][1], acc)

    def cerrar(self) -> List[Dict]:
        rastros = [r for r in self._rastros.values() if r.puntos]
        movimientos = []
        for cadena in unir_pedazos(rastros, self.fps):
            puntos = [p for r in cadena for p in r.puntos]
            origen, destino = recorrido(puntos)
            if origen is None and destino is None:
                continue      # nunca pisó un acceso: no es tránsito de la intersección
            clases = Counter()
            confs = []
            for r in cadena:
                clases.update(r.clases)
                confs.extend(r.confianzas)
            # Alto de la caja en el ORIGEN: todos los vehículos de un acceso
            # se miden a una distancia parecida de la cámara, que es lo que
            # hace comparable el alto (la misma premisa que la regla del
            # alto por carril en el aforo por línea).
            altos_origen = sorted(p[3] for p in puntos if p[4] == origen) or \
                sorted(p[3] for p in puntos)
            movimientos.append({
                'origen_id': origen,
                'destino_id': destino,
                'cuadro_inicio': puntos[0][0],
                'cuadro_fin': puntos[-1][0],
                'vehicle_type': clases.most_common(1)[0][0],
                'bbox_height': int(altos_origen[len(altos_origen) // 2]),
                'confidence': round(sum(confs) / len(confs), 3) if confs else None,
                'pedazos': len(cadena),
                'completo': origen is not None and destino is not None,
            })
        self._rastros.clear()
        return movimientos
