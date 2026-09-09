"""
Traduce las clases de COCO a la clasificacion que usa la empresa, y dice
con cuanta confianza puede hacerlo en cada calzada.

El problema: YOLO sale con las clases de COCO, donde `truck` mete en el
mismo saco una pickup y un tractocamion. En la clasificacion SCT
(A, B, C, T-S, T-S-R) la pickup es **A, un automovil**. Publicar
"total_truck = 1501" a un cliente le hace leer 1501 camiones donde hay
sobre todo camionetas.

La separacion se hace por ALTO EN PIXELES. Funciona por una razon concreta
del montaje: los vehiculos se cuentan al cruzar una linea fija, o sea a la
misma distancia de la camara, y a distancia constante el alto en pixeles es
proporcional al alto real. Fuera de la linea la premisa no se sostiene: el
mismo vehiculo mide 19 px al fondo de la zona y 33 px en la linea.

TRES NIVELES, NO DOS
--------------------

La primera version era todo o nada: o clasificaba, o devolvia
SIN_RESOLVER para la calzada entera. Se midio que eso tiraba informacion
buena. En la calzada del fondo, con el automovil a 15 px, la PROPORCION
sale bien aunque el conteo absoluto vaya corto:

    calzada cercana (32 px)   87.5 / 12.5 %   contra 87.4 / 12.6 %   0.1 puntos
    calzada del fondo (15 px) 89.2 / 10.8 %   contra 87.4 / 12.6 %   1.8 puntos

1.8 puntos es utilizable si se declara como estimacion. Negarse a darlo era
quedarse corto a proposito.

Por eso ahora se devuelve un NIVEL junto con la clasificacion:

    MEDIDO       el automovil se ve con holgura; conteo y proporcion valen
    ESTIMADO     se ve pequeño; la proporcion vale, el conteo absoluto no
    NO_RESOLUBLE no se ve; no se da ningun desglose

**Los umbrales son fisicos, sobre la imagen.** Eso importa para el futuro:
si llega una camara mejor o se acerca el encuadre, el vehiculo ocupa mas
pixeles y la calzada SUBE de nivel sola. El sistema no decide "esta no la
veo bien y paso"; mide lo que tiene y declara hasta donde llega.
"""
from __future__ import annotations

import statistics
from typing import Iterable, Optional, Tuple

# Clases de COCO que nunca son vehiculo pesado, midan lo que midan.
LIVIANAS_COCO = ("car", "motorcycle", "bicycle")

# Etiquetas de salida. Se usan los nombres de la empresa, no los de COCO.
LIVIANO = "A"           # automoviles, camionetas, pickups, vans ligeras
PESADO = "PESADO"       # autobuses, camiones unitarios y articulados
SIN_RESOLVER = "SIN_RESOLVER"

# Calidad del desglose de una calzada.
MEDIDO = "medido"
ESTIMADO = "estimado"
NO_RESOLUBLE = "no_resoluble"

# Multiplo del alto mediano del automovil por encima del cual un `truck` de
# COCO es de verdad un vehiculo pesado. Calibrado contra el conteo manual:
# 1.55 con la primera mitad de la mañana, 1.61 con la ventana completa. Se
# toma el punto medio. El barrido de sensibilidad deja los livianos entre
# 0.96x y 1.01x para cualquier valor entre 1.3 y 2.0, asi que la cifra
# exacta no es critica; lo que importa es que exista el corte.
MULTIPLO = 1.58

# Alto mediano del automovil a partir del cual el desglose es MEDIDO.
# A 32 px la proporcion sale a 0.1 puntos del conteo manual.
ALTO_MEDIDO = 25.0

# Por debajo de esto no se da ningun desglose. A 15 px la proporcion todavia
# sale a 1.8 puntos; no hay medicion por debajo, asi que el corte se pone
# conservador y por debajo se calla.
ALTO_MINIMO = 12.0

# Confianza media minima. Sirve para descartar la noche, donde la camara
# sobreexpone y el vehiculo sale como una estela: ahi la etiqueta de COCO no
# significa nada. Medido: de dia 0.67-0.76, de noche 0.44-0.57.
CONFIANZA_MINIMA = 0.65


def nivel_de_calzada(alturas_de_autos: Iterable[float],
                     confianzas: Optional[Iterable[float]] = None
                     ) -> Tuple[str, Optional[float]]:
    """Devuelve (nivel, umbral_pesado_px) de una calzada.

    El umbral es None cuando el nivel es NO_RESOLUBLE.
    """
    alturas = [h for h in alturas_de_autos if h and h > 0]
    if len(alturas) < 30:
        # Sin automoviles suficientes no hay escala, y sin escala el umbral
        # seria un numero inventado.
        return NO_RESOLUBLE, None

    if confianzas is not None:
        cs = [c for c in confianzas if c is not None]
        if cs and statistics.fmean(cs) < CONFIANZA_MINIMA:
            return NO_RESOLUBLE, None

    mediana = statistics.median(alturas)
    if mediana < ALTO_MINIMO:
        return NO_RESOLUBLE, None
    return (MEDIDO if mediana >= ALTO_MEDIDO else ESTIMADO), MULTIPLO * mediana


def umbral_de_calzada(alturas_de_autos: Iterable[float]) -> Optional[float]:
    """Compatibilidad: solo el umbral, sin el nivel."""
    return nivel_de_calzada(alturas_de_autos)[1]


def clasificar(tipo_coco: str, alto: Optional[float],
               umbral: Optional[float]) -> str:
    """Clase SCT de un cruce. SIN_RESOLVER si la calzada no da para separar.

    Sin umbral no se clasifica NADA, ni siquiera lo que COCO llama `car`:
    donde la calzada no resuelve, la etiqueta de COCO tampoco es de fiar, y
    clasificar solo los `car` dejaria escapar una cifra parcial que se lee
    como total.
    """
    if umbral is None:
        return SIN_RESOLVER
    if tipo_coco in LIVIANAS_COCO:
        return LIVIANO
    if alto is None:
        return SIN_RESOLVER
    if tipo_coco == "bus":
        return PESADO
    return PESADO if alto > umbral else LIVIANO


def clasificar_calzada(cruces: list[dict]) -> tuple[dict[str, int], Optional[float]]:
    """Reparte los cruces de UNA calzada y devuelve (conteos, umbral usado).

    Cada cruce necesita `vehicle_type` y `bbox_height`; `confidence` es
    opcional y sirve para descartar la noche.
    """
    nivel, umbral = nivel_de_calzada(
        (c.get("bbox_height") for c in cruces if c.get("vehicle_type") == "car"),
        (c.get("confidence") for c in cruces),
    )
    conteos: dict[str, int] = {LIVIANO: 0, PESADO: 0, SIN_RESOLVER: 0}
    for c in cruces:
        conteos[clasificar(c.get("vehicle_type", ""), c.get("bbox_height"), umbral)] += 1
    return conteos, umbral


def exactitud_declarable(nivel: str) -> str:
    """Que se puede escribir en un informe sobre este desglose."""
    if nivel == MEDIDO:
        return ("Desglose liviano/pesado MEDIDO. Contrastado contra aforo "
                "manual: composicion a 0.1 puntos, livianos 0.98x y pesados "
                "1.09x sobre datos no usados para calibrar.")
    if nivel == ESTIMADO:
        return ("Desglose liviano/pesado ESTIMADO. La proporcion sale a 1.8 "
                "puntos del aforo manual, pero el conteo absoluto de esta "
                "calzada va corto (0.84x): usar los porcentajes, no las "
                "cifras. No se separa autobus de camion.")
    return ("Sin desglose por tipo: el vehiculo se ve demasiado pequeno en "
            "esta calzada, o las condiciones de luz no permiten "
            "identificarlo.")
