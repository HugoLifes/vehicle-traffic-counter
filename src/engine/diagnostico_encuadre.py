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

from typing import Dict, List, Optional

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


def calificar_rastreo(r: Dict) -> Dict:
    """
    r: {'rastros', 'concentracion', 'borde', 'celdas', 'partidos_pct'}
       tal como los mide tools/diagnosticar_encuadre.py sobre un minuto.
    """
    avisos: List[str] = []
    conc = r.get('concentracion') or 0
    borde = r.get('borde') or 0
    partidos = r.get('partidos_pct') or 0

    if r.get('rastros', 0) < 10:
        return {'puntaje': 0, 'veredicto': 'no sirve', 'color': 'rojo',
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
    return {'puntaje': puntaje, 'veredicto': veredicto, 'color': color, 'avisos': avisos}


def combinar(imagen: Dict, rastreo: Optional[Dict] = None) -> Dict:
    """
    Veredicto final. Manda el PEOR de los dos: un encuadre nítido y cercano
    no sirve si el vehículo desaparece a media intersección, y al revés.
    """
    if rastreo is None:
        return dict(imagen, etapa='solo imagen')
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
