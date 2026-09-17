"""
Aforo direccional por TRAYECTORIA: decidir el movimiento de cada vehículo
por la forma de su recorrido, y no solo por las zonas que pisó.

Por qué existe
--------------
`origen_destino.py` decide por zonas: origen es el primer acceso que pisa
el vehículo y destino el último. Medido en Entrada y salida Altozano contra
el conteo manual, eso tiene dos fallas:

  · exige ver al vehículo en los DOS extremos. Un letrero de peatones justo
    después del arco parte los rastros, y a las 7:15-7:45 quedaron 346
    movimientos completos contra 468 del manual (0.74x);
  · una zona que roza el carril de otro flujo inventa un movimiento: 92
    vehículos del movimiento principal pasaban por la esquina del acceso
    "Derecha" antes de que el letrero los tapara, y quedaban como si fueran
    a ese acceso.

Los mejores equipos del AI City Challenge 2021 (conteo por movimiento, en
Jetson) asignaban cada rastro al movimiento cuyo recorrido representativo
le queda más cerca, con distancia de Hausdorff y dirección. Aquí se hace lo
mismo con representativos sacados de los completos del propio aforo, y con
esto Entrada y salida Altozano pasó de 0.74x a 0.99x (461 contra 468), el
movimiento principal con GEH 1.5. Se validó con plantillas aprendidas de
otros videos del mismo aforo (07:46 y 07:56) para no medir sobre lo mismo
con lo que se aprendió: 0.99x igual.

Cómo decide
-----------
1. Plantillas: por cada par de zonas con al menos MIN_EJEMPLOS completos,
   hasta K_EJEMPLARES recorridos que cubren el ancho de la franja (carriles,
   quien abre o cierra la vuelta).
2. Una plantilla cuyo recorrido entero cabe, en el mismo sentido, dentro de
   la franja de otra es esa otra vista a medias, y sus completos pasan a ser
   pedazos de ella. Salvo que termine en una salida de verdad: si la mayoría
   de sus rastros MUERE dentro de su zona de destino, es otro camino.
3. Cada incompleto se asigna al movimiento más probable (cercanía y cuántos
   vehículos lo hacen), si pasa por la franja en su sentido y cubre al menos
   MIN_COBERTURA del recorrido, y solo si esa probabilidad supera
   MIN_POSTERIOR. Un pedazo no se reparte entre movimientos.
4. Pedazos del mismo movimiento que pueden ser el mismo vehículo (el
   segundo arranca más adelante y el hueco de tiempo es coherente con lo que
   tarda el movimiento) cuentan una vez. Para contar no importa si se
   confunde a dos vehículos del mismo movimiento: el número sale igual.

Candados, medidos donde la cámara NO cubre el cruce
----------------------------------------------------
Sin ellos, en la Glorieta Altozano (la cámara ve un tercio del tránsito)
el método inventó 421 vueltas en U: pedazos de movimientos que la cámara
nunca ve completos se pegaban a la única plantilla parecida.
  · Una vuelta en U nunca se completa con pedazos: se define por el regreso.
  · Un movimiento no se completa con más pedazos que completos vistos
    (MAX_PEDAZOS_POR_COMPLETO). En Altozano el principal usó 0.4.
Con los candados la Glorieta queda exactamente como con zonas y Blvd
Independencia no empeora (2 de 16 movimientos con GEH < 5, igual).
"""

from collections import Counter, defaultdict
from typing import Dict, List, Optional

import numpy as np

N_PLANTILLA = 32
N_PEDAZO = 16
MIN_EJEMPLOS = 3
K_EJEMPLARES = 12
# Separación máxima a la franja: el punto MÁS alejado, en altos de caja para
# que valga igual cerca y lejos de la cámara. Con el percentil 90, dos
# movimientos que solo se separan al final se confundían.
UMBRAL_ALTOS = 1.0
SIGMA_ALTOS = 0.5
MIN_POSTERIOR = 0.9
MIN_COBERTURA = 0.25
MIN_MONOTONO = 0.8
MAX_PEDAZOS_POR_COMPLETO = 1.0

# Puntos que se guardan por vehículo. Cuarenta y ocho bastan para la forma
# del recorrido y para comparar dos rastros en el tiempo; guardar todos los
# cuadros serían cientos por vehículo.
MAX_PUNTOS = 48


def compactar(puntos, fps: float, destino) -> Dict:
    """
    Recorrido compacto de una cadena de rastros, para guardarlo en la base.

    puntos: (cuadro, x, y, alto_caja, acceso) como los acumula
    `origen_destino.Rastro`. El tiempo va en segundos desde el inicio del
    video.
    """
    n = len(puntos)
    if n > MAX_PUNTOS:
        idx = sorted(set(np.linspace(0, n - 1, MAX_PUNTOS).round().astype(int).tolist()))
    else:
        idx = range(n)
    fps = fps or 15.0
    return {
        't': [round(puntos[i][0] / fps, 2) for i in idx],
        'x': [round(float(puntos[i][1]), 1) for i in idx],
        'y': [round(float(puntos[i][2]), 1) for i in idx],
        'h': [round(float(puntos[i][3]), 1) for i in idx],
        # ¿Murió DENTRO de su zona de destino, o solo la cruzó y se perdió
        # más adelante? Distingue una salida de verdad de una zona rozada.
        'fin_en_destino': destino is not None and puntos[-1][4] == destino,
    }


def registro(origen, destino, recorrido: Dict, inicio_s: float, video,
             vehicle_type: Optional[str] = None, clave=None) -> Dict:
    """Lo que necesita `decidir` de cada vehículo: tiempos absolutos en segundos."""
    t = recorrido['t']
    return {
        'org': origen, 'dst': destino, 'video': video, 'clave': clave,
        't0': inicio_s + t[0], 't1': inicio_s + t[-1],
        'puntos': [(inicio_s + t[i], recorrido['x'][i], recorrido['y'][i], recorrido['h'][i])
                   for i in range(len(t))],
        'fin_en_destino': bool(recorrido.get('fin_en_destino')),
        'vehicle_type': vehicle_type,
    }


# --- Geometría -------------------------------------------------------------

def _suavizar(puntos, k=5):
    """Mediana móvil del punto de apoyo: la caja tiembla unos píxeles de un
    cuadro al siguiente y ese temblor infla la longitud del recorrido."""
    xy = np.array([(p[1], p[2]) for p in puntos], float)
    h = np.array([p[3] for p in puntos], float)
    if len(xy) < k:
        return xy, h
    r = k // 2
    return np.array([np.median(xy[max(0, i - r):i + r + 1], axis=0)
                     for i in range(len(xy))]), h


def remuestrear(puntos, n):
    xy, h = _suavizar(puntos)
    if len(xy) < 2:
        return None
    s = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(xy, axis=0).T))])
    if s[-1] < 1e-6:
        return None
    t = np.linspace(0, s[-1], n)
    return (np.stack([np.interp(t, s, xy[:, 0]), np.interp(t, s, xy[:, 1])], 1),
            np.interp(t, s, h))


def _polilinea(xy, h):
    largo = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(xy, axis=0).T))])
    return {'xy': xy, 'h': h, 'largo': largo}


def plantillas(registros: List[Dict]) -> Dict:
    """Recorridos representativos de cada par de zonas con completos."""
    por_mov = defaultdict(list)
    for c in registros:
        if c['org'] is None or c['dst'] is None:
            continue
        r = remuestrear(c['puntos'], N_PLANTILLA)
        if r is not None:
            por_mov[(c['org'], c['dst'])].append((r, c['t1'] - c['t0'], c['fin_en_destino']))
    salida = {}
    for mov, lista in por_mov.items():
        if len(lista) < MIN_EJEMPLOS:
            continue
        muestra = lista[:150]
        xy = np.stack([r[0] for r, _, _ in muestra])
        h = np.stack([r[1] for r, _, _ in muestra])
        d = np.linalg.norm(xy[:, None] - xy[None], axis=3)
        dist = (d / np.maximum((h[:, None] + h[None]) / 2, 1)).mean(axis=2)
        tipicidad = dist.mean(axis=1)
        medoide = int(np.argmin(tipicidad))
        # Se descarta el 10 % más atípico para que un rastro raro no ensanche
        # la franja; del resto se eligen los que más la cubren.
        validos = [int(i) for i in np.where(tipicidad <= np.percentile(tipicidad, 90))[0]]
        elegidos = [medoide]
        while len(elegidos) < min(K_EJEMPLARES, len(validos)):
            resto = [i for i in validos if i not in elegidos]
            if not resto:
                break
            lejos = max(resto, key=lambda i: dist[i, elegidos].min())
            if dist[lejos, elegidos].min() < 0.25:
                break
            elegidos.append(lejos)
        salida[mov] = dict(_polilinea(xy[medoide], h[medoide]), ejemplos=len(lista),
                           ejemplares=[_polilinea(xy[i], h[i]) for i in elegidos],
                           duracion=float(np.median([t for _, t, _ in lista])),
                           sale=sum(s for _, _, s in lista) / len(lista))
    return salida


def _proyectar(plantilla, pts):
    """Distancia (px) y avance (0-1) de cada punto sobre la polilínea."""
    a, b = plantilla['xy'][:-1], plantilla['xy'][1:]
    ab = b - a
    l2 = np.maximum((ab ** 2).sum(1), 1e-9)
    t = np.clip(((pts[:, None] - a[None]) * ab[None]).sum(2) / l2[None], 0, 1)
    proy = a[None] + t[..., None] * ab[None]
    d = np.linalg.norm(pts[:, None] - proy, axis=2)
    j = d.argmin(1)
    fila = np.arange(len(pts))
    largo = plantilla['largo']
    s = (largo[j] + t[fila, j] * np.sqrt(l2[j])) / max(largo[-1], 1e-9)
    return d[fila, j], s


def _medir(plantilla, pts, h):
    d, s = _proyectar(plantilla, pts)
    pasos = np.diff(s)
    return {'sep': float(np.max(d / np.maximum(h, 1))),
            's0': float(s[0]), 's1': float(s[-1]), 'cobertura': float(s[-1] - s[0]),
            'monotono': float((pasos >= -0.02).mean()) if len(pasos) else 0.0}


def _medir_mov(plantilla, pts, h):
    return min((_medir(e, pts, h) for e in plantilla['ejemplares']), key=lambda m: m['sep'])


def depurar(tpl: Dict):
    """(plantillas que quedan, {absorbida: absorbente}); ver paso 2 arriba."""
    absorbida = {}
    for a in sorted(tpl, key=lambda m: tpl[m]['ejemplos']):
        for b in sorted(tpl, key=lambda m: -tpl[m]['ejemplos']):
            if a == b or b in absorbida or tpl[b]['ejemplos'] < tpl[a]['ejemplos']:
                continue
            if a[1] != b[1] and tpl[a]['sale'] >= 0.5:
                continue
            m = _medir_mov(tpl[b], tpl[a]['xy'], tpl[a]['h'])
            if m['sep'] <= UMBRAL_ALTOS and m['monotono'] >= MIN_MONOTONO and m['cobertura'] > 0:
                absorbida[a] = b
                break
    return {m: p for m, p in tpl.items() if m not in absorbida}, absorbida


def asignar(reg: Dict, tpl: Dict):
    """(movimiento, medida, motivo) para un rastro incompleto."""
    r = remuestrear(reg['puntos'], N_PEDAZO)
    if r is None:
        return None, None, 'sin plantilla'
    candidatos = []
    for mov, p in tpl.items():
        m = _medir_mov(p, *r)
        if (m['sep'] <= UMBRAL_ALTOS and m['cobertura'] >= MIN_COBERTURA
                and m['monotono'] >= MIN_MONOTONO):
            peso = np.exp(-0.5 * (m['sep'] / SIGMA_ALTOS) ** 2) * (p['ejemplos'] + 1)
            candidatos.append((peso, mov, m))
    if not candidatos:
        return None, None, 'sin plantilla'
    candidatos.sort(key=lambda c: -c[0])
    if candidatos[0][0] / sum(c[0] for c in candidatos) < MIN_POSTERIOR:
        return None, None, 'ambiguo'
    return candidatos[0][1], candidatos[0][2], 'asignado'


# --- Pedazos del mismo vehículo --------------------------------------------

def _duplicado(reg: Dict, completos: List[Dict]) -> bool:
    """¿Va pegado a un completo del mismo movimiento, al mismo tiempo? Es una
    segunda caja sobre el mismo vehículo, no otro vehículo."""
    for c in completos:
        if c['video'] != reg['video'] or c['t1'] < reg['t0'] or c['t0'] > reg['t1']:
            continue
        tc = np.array([p[0] for p in c['puntos']])
        cerca = []
        for t, x, y, _ in reg['puntos']:
            if tc[0] <= t <= tc[-1]:
                cx = np.interp(t, tc, [p[1] for p in c['puntos']])
                cy = np.interp(t, tc, [p[2] for p in c['puntos']])
                ch = np.interp(t, tc, [p[3] for p in c['puntos']])
                cerca.append(np.hypot(x - cx, y - cy) / max(ch, 1))
        if len(cerca) >= 5 and np.median(cerca) <= 1.0:
            return True
    return False


def _emparejar(pedazos: List[Dict], duracion: float):
    from scipy.optimize import linear_sum_assignment
    if len(pedazos) < 2:
        return []
    t0 = np.array([p['reg']['t0'] for p in pedazos])
    t1 = np.array([p['reg']['t1'] for p in pedazos])
    s0 = np.array([p['medida']['s0'] for p in pedazos])
    s1 = np.array([p['medida']['s1'] for p in pedazos])
    hueco = t0[None, :] - t1[:, None]
    avance = s0[None, :] - s1[:, None]
    esperado = np.maximum(avance, 0) * duracion
    valido = ((hueco > 0) & (avance >= -0.1)
              & (hueco >= esperado * 0.3 - 1.0) & (hueco <= esperado * 3.0 + 2.0))
    np.fill_diagonal(valido, False)
    if not valido.any():
        return []
    costo = np.where(valido, np.abs(hueco - esperado) / (esperado + 1.0), 1e6)
    filas_v = np.where(valido.any(1))[0]
    cols_v = np.where(valido.any(0))[0]
    sub = costo[np.ix_(filas_v, cols_v)]
    filas, cols = linear_sum_assignment(sub)
    return [(pedazos[filas_v[f]], pedazos[cols_v[c]])
            for f, c in zip(filas, cols) if sub[f, c] < 1e6]


# --- Decidir ---------------------------------------------------------------

def decidir(registros: List[Dict], tpl: Optional[Dict] = None) -> Dict:
    """
    registros: vehículos como los arma `registro` (con recorrido). Los que
       no traen recorrido se deciden por zonas, como antes.
    tpl: plantillas ya calculadas; por omisión, las de los propios registros.

    Devuelve:
      vehiculos   — los que cuentan: t0, movimiento, clase y cómo se decidió
                    ('zonas' o 'trayectoria');
      sin_decidir — incompletos que no se pudieron asignar, con el motivo;
      motivos     — resumen de cada decisión, para declararlo en el informe.
    """
    con_recorrido = [r for r in registros if r.get('puntos')]
    tpl, absorbida = depurar(plantillas(con_recorrido) if tpl is None else tpl)

    def raiz(mov):
        while mov in absorbida:
            mov = absorbida[mov]
        return mov

    vehiculos, sin_decidir, rozadas = [], [], []
    motivos = Counter()
    pedazos = defaultdict(list)
    completos = defaultdict(list)

    def contar(reg, mov, como):
        vehiculos.append({'t0': reg['t0'], 'origen_id': mov[0], 'destino_id': mov[1],
                          'vehicle_type': reg.get('vehicle_type'), 'decision': como,
                          'clave': reg.get('clave')})

    def aparte(reg, motivo):
        motivos[motivo] += 1
        sin_decidir.append({'t0': reg['t0'], 'origen_id': reg['org'],
                            'destino_id': reg['dst'], 'motivo': motivo,
                            'clave': reg.get('clave')})

    for reg in registros:
        completo = reg['org'] is not None and reg['dst'] is not None
        if not reg.get('puntos'):
            if completo:
                motivos['completo por zonas'] += 1
                contar(reg, (reg['org'], reg['dst']), 'zonas')
            else:
                aparte(reg, 'sin recorrido guardado')
            continue
        if completo:
            mov = raiz((reg['org'], reg['dst']))
            if mov == (reg['org'], reg['dst']):
                motivos['completo por zonas'] += 1
                contar(reg, mov, 'zonas')
                completos[mov].append(reg)
                continue
            # Su destino era de mentira: rozó una zona y murió más adelante.
            # Es un PEDAZO del movimiento que lo absorbió; contarlo como
            # completo lo duplicaba cuando el vehículo reaparecía más allá.
            r = remuestrear(reg['puntos'], N_PEDAZO)
            if r is None:
                aparte(reg, 'sin plantilla')
                continue
            motivos['zona rozada, reasignado'] += 1
            if mov[1] != reg['dst']:
                # Solo si lo falso era el destino. En "Abajo -> Izquierda"
                # lo falso era el origen (nació tarde) y la salida sí ocurrió.
                rozadas.append(reg.get('clave'))
            pedazos[mov].append({'reg': reg, 'medida': _medir_mov(tpl[mov], *r)})
            continue
        mov, medida, motivo = asignar(reg, tpl)
        if mov is not None and mov[0] == mov[1]:
            mov, motivo = None, 'vuelta en U a medias'
        if mov is None:
            aparte(reg, motivo)
            continue
        pedazos[mov].append({'reg': reg, 'medida': medida})

    for mov, lista in pedazos.items():
        propios = [p for p in lista if not _duplicado(p['reg'], completos[mov])]
        motivos['caja duplicada de un completo'] += len(lista) - len(propios)
        pares = _emparejar(propios, tpl[mov]['duracion'])
        segundos = {id(b) for _, b in pares}
        nuevos = [p for p in propios if id(p) not in segundos]
        if len(nuevos) > MAX_PEDAZOS_POR_COMPLETO * len(completos[mov]):
            for p in nuevos:
                aparte(p['reg'], 'la cámara no cubre el movimiento')
            continue
        motivos['pedazos del mismo vehículo'] += len(pares)
        motivos['completado por trayectoria'] += len(nuevos)
        for p in nuevos:
            contar(p['reg'], mov, 'trayectoria')

    return {'vehiculos': vehiculos, 'sin_decidir': sin_decidir, 'motivos': dict(motivos),
            # Completos por zonas cuyo destino era una zona solo rozada: esa
            # "salida" no ocurrió.
            'rozadas': rozadas,
            'plantillas': tpl, 'absorbida': absorbida}
