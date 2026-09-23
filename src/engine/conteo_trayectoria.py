"""
Conteo por trayectoria: un vehículo, un conteo.

El contador de siempre (`src/counter.py`) decide en el instante: cuando el
punto de apoyo de un rastro pasa al otro lado de la línea, suma uno. Eso
hace que **un rastro partido cuente dos veces**: si el detector entrega dos
cajas del mismo vehículo, o el rastreador le cambia la identidad justo sobre
la línea, se registran dos cruces de un solo vehículo. Medido en la cámara
frontal de Cd. Juárez: una pickup contada como los rastros 5802 y 5814 en el
mismo segundo.

Aquí se cuenta al cerrar el video, sobre el recorrido completo:

1. Se descartan los rastros que no se movieron (vehículos estacionados).
2. Se **unen los pedazos** del mismo vehículo con la maquinaria ya medida
   del aforo direccional (`origen_destino.unir_pedazos`): hueco de hasta 1 s,
   la posición predicha a menos de 2 altos de caja y el tamaño entre 0.5 y
   2.0 del anterior. Verificado a ojo en dos aforos reales.
3. Cada recorrido unido cuenta **una sola vez por línea**, con el sentido del
   producto cruzado — la misma convención que el contador de siempre, para
   que los reportes viejos y los nuevos signifiquen lo mismo.

Es la práctica aceptada para este problema: contar las trayectorias que
cruzan la línea en vez de los instantes, justamente para no duplicar por
cambios de identidad.

La cámara en vivo **no** puede usar esto: no hay "final del video" donde
decidir. Ahí sigue el contador incremental.
"""

from typing import Dict, List, Optional, Sequence, Tuple

from src.engine.origen_destino import Rastro, se_movio, unir_pedazos
from src.engine.velocidad import fraccion_cruce

Punto = Tuple[float, float]

# Cuánto tiene que alejarse un rastro para no ser temblor de caja, en altos
# de caja. El direccional pide 2 (recorrer la intersección); para cruzar una
# línea basta mucho menos.
MOVIMIENTO_MINIMO_ALTOS = 0.5

# Unión de pedazos para un aforo POR SECCIÓN, más estricta que la del
# direccional. Medido con cajas sintéticas: con la tolerancia del
# direccional (1 s y 2 altos de caja) dos vehículos que se siguen a medio
# segundo se fusionan en uno, porque a 25 px por cuadro el que viene atrás
# cae dentro del radio de la posición predicha del de adelante. Un vehículo
# que reaparece de verdad cae mucho más cerca de esa predicción.
HUECO_MAX_S = 0.5
TOLERANCIA_ALTOS = 0.8

# Dos rastros que viven A LA VEZ sobre el mismo vehículo son un solo
# vehículo con dos cajas (el detector entregaba dos, una como 'car' y otra
# como 'truck'). Se unen antes de contar.
#
# El criterio es cuánto se ENCIERRAN las cajas, no la distancia entre sus
# puntos de apoyo: medido en la pickup duplicada de Cd. Juárez, una caja
# tomaba la cabina y la otra el vehículo entero, así que sus puntos de apoyo
# quedaban a 0.94 altos —tanto como dos vehículos en carriles contiguos—
# pero una caja estaba casi dentro de la otra.
GEMELOS_SOLAPE = 0.5       # fracción del rastro más corto que coincide en el tiempo
GEMELOS_ENCIERRO = 0.65    # intersección sobre el área de la caja más chica


def _encierro(a, b) -> float:
    """Intersección sobre el área de la caja más chica: 1.0 si una está
    dentro de la otra."""
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    menor = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return inter / menor if menor > 0 else 0.0


def _unir_gemelos(objetos, cajas):
    """Funde los rastros que coexisten sobre el mismo vehículo."""
    import statistics
    puntos = {r.id: {p[0]: p for p in r.puntos} for r in objetos}
    padre = {r.id: r.id for r in objetos}

    def raiz(i):
        while padre[i] != i:
            padre[i] = padre[padre[i]]
            i = padre[i]
        return i

    for i, a in enumerate(objetos):
        for b in objetos[i + 1:]:
            comunes = set(puntos[a.id]) & set(puntos[b.id])
            if not comunes or len(comunes) < GEMELOS_SOLAPE * min(len(a.puntos), len(b.puntos)):
                continue
            if not cajas.get(a.id) or not cajas.get(b.id):
                continue
            encierros = [_encierro(cajas[a.id][c], cajas[b.id][c]) for c in comunes
                         if c in cajas[a.id] and c in cajas[b.id]]
            if encierros and statistics.median(encierros) >= GEMELOS_ENCIERRO:
                padre[raiz(b.id)] = raiz(a.id)

    grupos = {}
    for r in objetos:
        grupos.setdefault(raiz(r.id), []).append(r)
    fundidos = []
    for ids, miembros in grupos.items():
        if len(miembros) == 1:
            fundidos.append(miembros[0])
            continue
        # Se conserva el rastro más largo y se le agregan los cuadros que
        # solo vio el otro, para no perder el tramo donde el vehículo tuvo
        # una sola caja.
        miembros.sort(key=lambda r: len(r.puntos), reverse=True)
        principal = miembros[0]
        vistos = {p[0] for p in principal.puntos}
        for otro in miembros[1:]:
            for p in otro.puntos:
                if p[0] not in vistos:
                    principal.puntos.append(p)
                    vistos.add(p[0])
        principal.puntos.sort()
        fundidos.append(principal)
    return fundidos


def _direccion(p0: Punto, p1: Punto, a: Punto, b: Punto) -> str:
    """'in' u 'out' con la convención del contador: signo del producto
    cruzado entre el movimiento y la línea."""
    cruz = (p1[0] - p0[0]) * (b[1] - a[1]) - (p1[1] - p0[1]) * (b[0] - a[0])
    return 'in' if cruz > 0 else 'out'


def contar(rastros: Dict[int, List[Tuple]], lineas: List[Dict], fps: float,
           zona_de_punto=None, unir_gemelos: bool = False) -> Dict[int, List[Dict]]:
    """
    rastros: {track_id: [(cuadro, x1, y1, x2, y2), ...]} con la caja de cada
        cuadro en que se vio el vehículo. El punto de apoyo (centro del borde
        inferior) sale de ahí, igual que en el contador y en las zonas.
    lineas: [{'id', 'puntos': [(x, y), (x, y)], 'zone_id': int | None}]
    zona_de_punto: función (x, y) -> id de calzada, o None si no hay zonas.
    unir_gemelos: fundir rastros que coexisten sobre el mismo vehículo. Ver
        abajo por qué está apagado por omisión.

    Devuelve
    {lane_id: [{'track_id', 'ids', 'cuadro', 'direccion', 'alto', 'caja'}]},
    con un cruce como mucho por vehículo y línea. `caja` es (x1, y1, x2, y2)
    en el cuadro del cruce, o None si ese cuadro no está en ningún pedazo.
    """
    objetos, cajas = [], {}
    for tid, secuencia in rastros.items():
        if len(secuencia) < 2:
            continue
        puntos = [(c, (x1 + x2) / 2.0, y2, y2 - y1) for (c, x1, y1, x2, y2) in secuencia]
        cajas[tid] = {c: (x1, y1, x2, y2) for (c, x1, y1, x2, y2) in secuencia}
        # La caja va aparte y no dentro del punto: `unir_pedazos` y
        # `se_movio` desempacan la tupla de 5 que comparten con el aforo
        # direccional, y alargarla los rompe. Se guarda entera —no solo el
        # ancho— porque con la esquina se puede RECORTAR el vehiculo.
        r = Rastro(tid)
        # El acceso va en None: aquí no hay zonas de origen y destino, y
        # `unir_pedazos` entonces trata a todos los pedazos como candidatos,
        # que es justo lo que se quiere para un aforo por sección.
        r.puntos = [(c, x, y, alto, None) for (c, x, y, alto) in sorted(puntos)]
        # Medio alto de caja, no dos: el umbral del direccional exige que el
        # vehículo recorra la intersección entera, y aquí basta con que pase
        # por la línea. Un estacionado solo tiembla unos píxeles, y además
        # nunca cruza; esto es contra el temblor, no contra el estacionado.
        if se_movio(r.puntos, altos=MOVIMIENTO_MINIMO_ALTOS):
            objetos.append(r)

    # Apagada por omisión. Las dos cajas del mismo vehículo se eliminan en su
    # origen (el filtro de repetidas entre clases del detector), y un umbral
    # que las atrape aquí fusiona también a un vehículo con el que lo tapa:
    # medido en un minuto real, los pares con encierro alto sostenido eran
    # muchos y no todos eran duplicados. Se conserva para una cámara donde
    # el detector no pueda arreglarlo en el origen.
    if unir_gemelos:
        objetos = _unir_gemelos(objetos, cajas)

    salida = {l['id']: [] for l in lineas}
    for cadena in unir_pedazos(objetos, fps, max_hueco_s=HUECO_MAX_S,
                               tolerancia=TOLERANCIA_ALTOS):
        puntos = sorted((p for pedazo in cadena for p in pedazo.puntos))
        ids = [pedazo.id for pedazo in cadena]
        for linea in lineas:
            a, b = tuple(linea['puntos'][0]), tuple(linea['puntos'][1])
            for (c0, x0, y0, h0, _), (c1, x1, y1, h1, _) in zip(puntos, puntos[1:]):
                if fraccion_cruce((x0, y0), (x1, y1), a, b) is None:
                    continue
                # La calzada se decide en el punto del cruce, como en
                # producción: en perspectiva las dos calzadas se superponen y
                # la línea de una recoge vehículos de la otra.
                if linea.get('zone_id') and zona_de_punto is not None:
                    if zona_de_punto(x1, y1) != linea['zone_id']:
                        continue
                salida[linea['id']].append({
                    'track_id': ids[0], 'ids': ids, 'cuadro': c1,
                    'direccion': _direccion((x0, y0), (x1, y1), a, b),
                    'alto': h1,
                    # El cuadro del cruce es de UN pedazo de la cadena; se
                    # busca en cuál para sacar su caja.
                    'caja': next((cajas[i][c1] for i in ids
                                  if c1 in cajas.get(i, {})), None),
                })
                break        # un vehículo, un conteo por línea
    for lane_id in salida:
        salida[lane_id].sort(key=lambda c: c['cuadro'])
    return salida


def resumen(cruces: Dict[int, List[Dict]]) -> Dict[int, Dict]:
    """Totales por línea y sentido, como los que muestra el video anotado."""
    out = {}
    for lane_id, lista in cruces.items():
        out[lane_id] = {
            'total': len(lista),
            'in': sum(1 for c in lista if c['direccion'] == 'in'),
            'out': sum(1 for c in lista if c['direccion'] == 'out'),
        }
    return out
