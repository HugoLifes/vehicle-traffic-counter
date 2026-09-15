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


class Rastro:
    __slots__ = ('id', 'puntos', 'clases', 'confianzas')

    def __init__(self, tid):
        self.id = tid
        # (cuadro, x, y, alto_caja, acceso o None)
        self.puntos: List[Tuple[int, float, float, float, Optional[int]]] = []
        self.clases: Counter = Counter()
        self.confianzas: List[float] = []


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


def unir_pedazos(rastros: List[Rastro], fps: float,
                 max_hueco_s: float = 2.0, tolerancia: float = 1.2,
                 rango_tamano: Tuple[float, float] = (0.6, 1.6),
                 uniones: Optional[List] = None) -> List[List[Rastro]]:
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
            if not 0 < dt <= hueco:
                continue
            if acc_b is not None and acc_b != acc_a:
                continue       # nace dentro de OTRO acceso: es un origen legítimo
            if not rango_tamano[0] <= hb / max(ha, 1) <= rango_tamano[1]:
                continue
            escala = max(ha, hb, 1)
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
            pares.append((a.id, b.id, dist / limite + 0.5 * dt / hueco - 0.3 * coseno))

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

    def observar(self, cuadro: int, tracks: List[Dict]):
        if not self.activo:
            return
        guardar = cuadro % CADA_N_CUADROS == 0
        for t in tracks:
            r = self._rastros.get(t['id'])
            if r is None:
                r = self._rastros[t['id']] = Rastro(t['id'])
            r.clases[t['class_name']] += 1
            r.confianzas.append(t['confidence'])
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
