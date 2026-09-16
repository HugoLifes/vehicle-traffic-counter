"""
¿Este video sirve para aforar, y con qué exactitud esperable?

Existe porque descubrirlo procesando cuesta horas: Blvd Independencia se
contó 4 h para concluir que el puente tapa dos accesos, y la Glorieta 1.5 h
para ver que solo se veía un tercio del tránsito. Las mismas señales
estaban en el primer cuadro.

**No inventa un porcentaje de exactitud.** La exactitud real solo se sabe
contra un conteo manual. Lo que se califica son los factores que en este
proyecto SÍ se midieron contra conteos manuales, y el resultado se entrega
como rango esperado y avisos concretos:

| factor | medido en este proyecto |
|---|---|
| alto del vehículo | 36 px → 0.99x; 33 px → 0.96x; 15-18 px → 0.84x y sin clasificar |
| brillo / contraste | de noche el brillo sube a 177 y el conteo cae a 0.03x |
| nitidez | el obturador lento barre el vehículo y lo vuelve una estela |
| vehículos por cuadro | con la vía llena la exactitud baja de 0.95x a 0.86x |
| confianza media | 0.73 de día contra 0.45 de noche |

Se alimenta de las mismas medidas que produce `tools/calidad_video.py`, así
que el diagnóstico y la medición no pueden desviarse entre sí.
"""

import os
from typing import Dict, List, Optional

try:
    import cv2
except ImportError:      # pragma: no cover - cv2 siempre está en producción
    cv2 = None

# Alto del vehículo en píxeles. El detector necesita ~40 px para trabajar
# con holgura; a 33 px el aforo por línea dio 0.96x contra conteo manual y
# a 15-18 px no separa liviano de pesado.
ALTO_BUENO = 33.0
ALTO_MINIMO = 20.0

# De noche la cámara sobreexpone: brillo medio 168-177 contra 84 de día, y
# el conteo se desploma a 0.03x. No es falta de luz, es exceso.
BRILLO_ALTO = 150.0

# Varianza del laplaciano. Medido en el material: 2 400-4 700 en videos que
# cuentan bien, 156-930 en los que salen barridos o desenfocados.
NITIDEZ_BAJA = 1000.0

# Confianza media del detector sobre los vehículos vistos.
CONFIANZA_BUENA = 0.60
CONFIANZA_MALA = 0.45


def medir_imagen(video: str, det, muestras: int = 10) -> Dict:
    """
    Medidas de unos cuadros repartidos a lo largo del video.

    Vive aquí y no en tools/ porque las usan tres caminos —la herramienta de
    calidad, la de diagnóstico y la API— y si se duplican terminan midiendo
    cosas distintas con el mismo nombre.
    """
    import statistics
    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        return {'error': 'no abre'}
    ancho = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    alto = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0

    altos, confs, brillo, contraste, nitidez = [], [], [], [], []
    por_clase: Dict[str, int] = {}
    mejor, ejemplo = -1, None
    for i in range(muestras):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int((i + 0.5) * total / max(1, muestras)))
        ok, f = cap.read()
        if not ok:
            continue
        gris = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        brillo.append(float(gris.mean()))
        contraste.append(float(gris.std()))
        nitidez.append(float(cv2.Laplacian(gris, cv2.CV_64F).var()))
        dets, _ = det.detect(f)
        for d in dets:
            x1, y1, x2, y2 = d['bbox']
            altos.append(y2 - y1)
            confs.append(d['confidence'])
            por_clase[d['class_name']] = por_clase.get(d['class_name'], 0) + 1
        if len(dets) > mejor:
            mejor, ejemplo = len(dets), (f, dets)
    cap.release()

    def pct(p):
        if not altos:
            return None
        v = sorted(altos)
        return v[min(len(v) - 1, int(p * len(v)))]

    segundos = total / fps if fps else 0
    return {
        'resolucion': f'{ancho}x{alto}', 'fps': round(fps, 1),
        'minutos': round(segundos / 60, 1),
        'kbps': round(os.path.getsize(video) * 8 / segundos / 1000) if segundos else None,
        'brillo': round(statistics.mean(brillo)) if brillo else None,
        'contraste': round(statistics.mean(contraste)) if contraste else None,
        'nitidez': round(statistics.median(nitidez)) if nitidez else None,
        'detecciones_por_cuadro': round(len(altos) / max(1, len(brillo)), 1),
        'alto_p25': pct(.25), 'alto_mediana': pct(.5), 'alto_p75': pct(.75),
        'pct_bajo_20px': round(100 * sum(a < 20 for a in altos) / len(altos)) if altos else None,
        'pct_40px_o_mas': round(100 * sum(a >= 40 for a in altos) / len(altos)) if altos else None,
        'confianza': round(statistics.mean(confs), 2) if confs else None,
        'clases': por_clase,
        '_ejemplo': ejemplo,
    }


CELDA_EXTREMOS = 80


def medir_rastreo(video: str, det, minutos: float = 1.0, banda=None) -> Dict:
    """
    Rastrea unos minutos y mide dónde nacen y mueren los rastros.

    El detector tiene que venir con el umbral bajo (ByteTrack necesita ver
    las detecciones flojas para su segunda pasada); quien llama lo ajusta y
    lo restaura, porque el detector se comparte con la cola de conteo.
    """
    from collections import Counter

    from src.engine.origen_destino import Rastro, se_movio, unir_pedazos
    from src.engine.rastreo_bytetrack import RastreadorBytetrack

    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 15
    ancho = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    alto = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    det.set_detection_band(banda)
    trk = RastreadorBytetrack(fps)
    rastros: Dict[int, object] = {}
    n, tope = 0, int(minutos * 60 * fps)
    while n < tope:
        ok, f = cap.read()
        if not ok:
            break
        for tr in trk.update(det.detect(f)[0], f):
            r = rastros.get(tr['id'])
            if r is None:
                r = rastros[tr['id']] = Rastro(tr['id'])
            x1, y1, x2, y2 = tr['bbox']
            r.puntos.append((n, (x1 + x2) / 2, y2, y2 - y1, None))
        n += 1
    cap.release()

    cadenas = unir_pedazos([r for r in rastros.values() if r.puntos and se_movio(r.puntos)], fps)
    extremos = []
    for c in cadenas:
        pts = [p for r in c for p in r.puntos]
        extremos.append(pts[0][1:3])
        extremos.append(pts[-1][1:3])
    if not extremos:
        return {'rastros': 0, 'concentracion': 0, 'borde': 0, 'celdas': 0,
                'partidos_pct': 0, 'cuadros': n}
    rejilla = Counter((int(x) // CELDA_EXTREMOS, int(y) // CELDA_EXTREMOS) for x, y in extremos)
    return {
        'rastros': len(cadenas),
        'concentracion': 100 * sum(v for _, v in rejilla.most_common(6)) / len(extremos),
        'borde': 100 * sum(1 for x, y in extremos
                           if x < 70 or x > ancho - 70 or y < 70 or y > alto - 70) / len(extremos),
        'celdas': len(rejilla),
        'partidos_pct': 100 * sum(1 for c in cadenas if len(c) > 1) / max(1, len(cadenas)),
        'cuadros': n,
    }


def _banda(valor: float, bueno: float, malo: float) -> float:
    """0 en `malo`, 1 en `bueno`, lineal entre ambos. Sirve en los dos
    sentidos: `bueno` puede ser mayor o menor que `malo`."""
    if bueno == malo:
        return 1.0 if valor >= bueno else 0.0
    x = (valor - malo) / (bueno - malo)
    return max(0.0, min(1.0, x))


def calificar(m: Dict, direccional: bool = False) -> Dict:
    """
    m: medidas de un video, con las claves de tools/calidad_video.py
       (alto_mediana, alto_p25, pct_bajo_20px, brillo, contraste, nitidez,
        confianza, detecciones_por_cuadro, resolucion, fps, kbps).

    direccional: el aforo direccional exige seguir al vehículo por toda la
       intersección, no solo verlo cruzar una línea, así que pide más.
    """
    avisos: List[str] = []
    alto = m.get('alto_mediana')
    conf = m.get('confianza')
    brillo = m.get('brillo') or 0
    nitidez = m.get('nitidez') or 0
    bajo20 = m.get('pct_bajo_20px')
    dets = m.get('detecciones_por_cuadro') or 0

    if alto is None or conf is None:
        return {
            'puntaje': 0, 'veredicto': 'no sirve', 'color': 'rojo',
            'razon_es': 'No se detectó ningún vehículo en los cuadros de muestra.',
            'avisos': ['Puede estar de noche, desenfocado o apuntando a donde no pasa tránsito.'],
            'razon_esperada': None,
        }

    # Cada factor entre 0 y 1, con su peso. El tamaño pesa el doble porque
    # es el límite duro: lo que no está en los píxeles no lo recupera nada.
    factores = {
        'tamaño del vehículo': (_banda(alto, ALTO_BUENO, ALTO_MINIMO), 2.0),
        'confianza del detector': (_banda(conf, CONFIANZA_BUENA, CONFIANZA_MALA), 1.0),
        'exposición': (_banda(brillo, 110.0, BRILLO_ALTO), 1.0),
        'nitidez': (_banda(nitidez, 2400.0, NITIDEZ_BAJA), 1.0),
    }
    if direccional:
        # Para el direccional el vehículo debe verse grande TODO el recorrido,
        # no solo en un punto: se exige que la cola chica también aguante.
        factores['tamaño en todo el recorrido'] = (
            _banda(m.get('alto_p25') or 0, ALTO_BUENO, ALTO_MINIMO), 1.5)

    puntaje = round(100 * sum(v * p for v, p in factores.values())
                    / sum(p for _, p in factores.values()))

    if alto < ALTO_MINIMO:
        avisos.append(f'El vehículo mide {alto:.0f} px de alto; se necesitan ~33 px para '
                      'contar bien y 40 px para clasificar. Acerca el encuadre o sube la cámara.')
    elif alto < ALTO_BUENO:
        avisos.append(f'El vehículo mide {alto:.0f} px: alcanza para contar, pero el desglose '
                      'por tipo va a quedar corto.')
    if bajo20 is not None and bajo20 >= 40:
        avisos.append(f'El {bajo20:.0f} % de los vehículos se ve por debajo de 20 px. '
                      'Esa parte del encuadre no se puede aforar.')
    if brillo >= BRILLO_ALTO:
        avisos.append(f'Imagen sobreexpuesta (brillo {brillo:.0f}). De noche la cámara abre la '
                      'exposición y cada vehículo sale como una estela: fuerza obturador rápido.')
    if nitidez and nitidez < NITIDEZ_BAJA:
        avisos.append(f'Imagen poco nítida ({nitidez:.0f}). Puede ser desenfoque, suciedad en el '
                      'lente o movimiento barrido.')
    if conf < CONFIANZA_MALA:
        avisos.append(f'El detector reconoce los vehículos con poca seguridad ({conf:.2f}).')
    if dets >= 12:
        avisos.append(f'Hay {dets:.0f} vehículos por cuadro: con la vía llena se tapan entre sí '
                      'y el conteo baja (medido: de 0.95x a 0.86x). Ayuda subir la cámara.')

    if puntaje >= 75:
        veredicto, color = 'bueno', 'verde'
        razon = (0.90, 0.99)
    elif puntaje >= 50:
        veredicto, color = 'regular', 'ambar'
        razon = (0.80, 0.95)
    else:
        veredicto, color = 'no recomendable', 'rojo'
        razon = None

    if direccional:
        avisos.append('En aforo direccional, revisa además que los cuatro accesos estén '
                      'completos en el cuadro y que nada (un puente, un letrero, la carcasa) '
                      'tape por dónde entran o salen los vehículos: eso no lo ve esta medición.')

    return {
        'puntaje': puntaje,
        'veredicto': veredicto,
        'color': color,
        'factores': {k: round(100 * v) for k, (v, _) in factores.items()},
        'avisos': avisos,
        # Rango esperado contra conteo manual, del material ya validado. None
        # cuando el encuadre no da para prometer nada.
        'razon_esperada': razon,
    }


# --- Etapa 2: ¿se ve por dónde entra y sale el vehículo? -----------------
#
# La etapa por imagen califica qué tan grande y nítido se ve el vehículo, y
# con eso NO basta: en la prueba real calificó mejor a Blvd Independencia
# (41 px, que falló) que a Entrada y salida Altozano (43 px, el único que
# sirvió). Lo que decide es si el encuadre deja ver por dónde entra y sale
# cada vehículo, y eso solo se mide rastreando un minuto.
#
# Medido sobre los tres aforos cuyo resultado real se conoce:
#
#   aforo                       extremos en 6 celdas   en la orilla   resultado
#   Entrada y salida Altozano          81 %               36 %        sirvió
#   Blvd Independencia                 54 %               30 %        falló
#   Glorieta Altozano                  64 %                1 %        falló
#
# Son tres escenas: alcanza para avisar, no para prometer un porcentaje.
CONCENTRACION_BUENA = 75.0   # % de extremos en las 6 celdas más usadas
BORDE_MINIMO = 15.0          # % de extremos pegados a la orilla del cuadro

# Con menos de 10 rastros las proporciones de esta etapa son ruido (con 5
# rastros hay 10 extremos: un vehículo mueve la cifra 10 puntos). Y "pocos
# rastros" tiene DOS causas opuestas, una del encuadre y la otra no. Medido
# sobre el material: Fraccionamientos da 2.1 detecciones por cuadro y 5
# rastros —una calle tranquila, con el encuadre bien— y el amanecer de
# Entrada y salida Altozano da 0.5 detecciones por cuadro y 0 rastros, que
# ahí sí es que no se ve nada. Lo que las separa es cuántos vehículos ve el
# detector en la imagen, no cuántos alcanza a seguir.
RASTROS_MINIMOS = 10
DETS_CUADRO_HAY_TRANSITO = 1.0


def calificar_rastreo(r: Dict, dets_por_cuadro: Optional[float] = None) -> Dict:
    """
    r: {'rastros', 'concentracion', 'borde', 'celdas', 'partidos_pct'}
       tal como los mide tools/diagnosticar_encuadre.py sobre un minuto.

    dets_por_cuadro: el `detecciones_por_cuadro` de la etapa por imagen. Sin
       él, pocos rastros se toman como encuadre malo, que es lo que esta
       etapa suponía antes y sale mal en una calle de poco tránsito.
    """
    avisos: List[str] = []
    conc = r.get('concentracion') or 0
    borde = r.get('borde') or 0
    partidos = r.get('partidos_pct') or 0

    if r.get('rastros', 0) < RASTROS_MINIMOS:
        n = r.get('rastros', 0)
        if dets_por_cuadro is not None and dets_por_cuadro >= DETS_CUADRO_HAY_TRANSITO:
            # Hay vehículos en el cuadro; que pasen pocos no dice nada del
            # encuadre. Esta etapa se declara no concluyente y manda la otra.
            return {'concluyente': False, 'avisos': [
                f'Solo se siguieron {n} vehículos en el minuto de prueba, aunque el detector '
                f've {dets_por_cuadro:.1f} por cuadro: es poco tránsito, no un problema del '
                'encuadre. Para juzgarlo, diagnostica más minutos o un video de hora pico.']}
        return {'puntaje': 0, 'veredicto': 'no sirve', 'color': 'rojo', 'concluyente': True,
                'avisos': ['Casi no se siguió ningún vehículo en el minuto de prueba.']}

    if conc < CONCENTRACION_BUENA:
        avisos.append(
            f'Los rastros nacen y mueren repartidos por toda la escena (solo el {conc:.0f} % '
            'se concentra en unos pocos puntos). Suele significar que algo tapa la vía —un '
            'puente, un poste, un letrero— o que se pierden a media intersección.')
    if borde < BORDE_MINIMO:
        avisos.append(
            f'Solo el {borde:.0f} % de los vehículos entra o sale por la orilla del cuadro: '
            'aparecen y desaparecen a media escena, así que el acceso por donde circulan '
            'probablemente queda fuera del encuadre.')
    if partidos >= 25:
        avisos.append(f'El {partidos:.0f} % de los rastros se parte en pedazos: el vehículo se '
                      'pierde y reaparece. Se recupera parte al unirlos, pero cuesta exactitud.')

    puntaje = round(100 * (0.6 * _banda(conc, CONCENTRACION_BUENA, 40.0)
                           + 0.4 * _banda(borde, 35.0, 0.0)))
    if puntaje >= 70:
        veredicto, color = 'bueno', 'verde'
    elif puntaje >= 45:
        veredicto, color = 'regular', 'ambar'
    else:
        veredicto, color = 'no recomendable', 'rojo'
    return {'puntaje': puntaje, 'veredicto': veredicto, 'color': color,
            'concluyente': True, 'avisos': avisos}


def combinar(imagen: Dict, rastreo: Optional[Dict] = None) -> Dict:
    """
    Veredicto final. Manda el PEOR de los dos: un encuadre nítido y cercano
    no sirve si el vehículo desaparece a media intersección, y al revés.
    """
    if rastreo is None:
        return dict(imagen, etapa='solo imagen')
    if not rastreo.get('concluyente', True):
        # El rastreo no vio bastante para opinar: manda la etapa por imagen,
        # con el aviso de por qué. Puntuar esto como encuadre malo reprobaba
        # calles de poco tránsito por no tener tránsito.
        avisos = rastreo.get('avisos', []) + imagen.get('avisos', [])
        genericos = [a for a in avisos if a.startswith('En aforo direccional')]
        return dict(imagen,
                    avisos=[a for a in avisos if a not in genericos] + genericos,
                    imagen=imagen['puntaje'], rastreo=None,
                    etapa='solo imagen (el rastreo no fue concluyente)')
    orden = {'verde': 2, 'ambar': 1, 'rojo': 0}
    peor = min((imagen, rastreo), key=lambda d: orden.get(d['color'], 0))
    # El rango esperado sale del veredicto FINAL y no de la mejor etapa: con
    # la etapa por imagen mandando, Blvd Independencia salía "regular" pero
    # con la banda del bueno (0.90x-0.99x), que es justo lo que no cumplió.
    rangos = {'verde': (0.90, 0.99), 'ambar': (0.80, 0.95), 'rojo': None}
    # Primero los avisos concretos de cada etapa y al final los genéricos,
    # que son recordatorios y no hallazgos de esta medición.
    avisos = rastreo.get('avisos', []) + imagen.get('avisos', [])
    genericos = [a for a in avisos if a.startswith('En aforo direccional')]
    return {
        'puntaje': min(imagen['puntaje'], rastreo['puntaje']),
        'veredicto': peor['veredicto'],
        'color': peor['color'],
        'avisos': [a for a in avisos if a not in genericos] + genericos,
        'razon_esperada': rangos[peor['color']],
        'imagen': imagen['puntaje'],
        'rastreo': rastreo['puntaje'],
        'etapa': 'imagen y rastreo',
    }


def resumen_texto(d: Dict) -> str:
    partes = [f"{d['veredicto'].upper()} ({d['puntaje']}/100)"]
    if d.get('razon_esperada'):
        a, b = d['razon_esperada']
        partes.append(f"exactitud esperable {a:.2f}x-{b:.2f}x del conteo real")
    return ' · '.join(partes)
