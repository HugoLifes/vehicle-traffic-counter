"""
Traduce las clases de COCO a la clasificacion que usa la empresa, y se
NIEGA a hacerlo donde la imagen no da para tanto.

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

Verificado MIRANDO 54 vehiculos recortados en la linea de la calzada
cercana, uno por uno contra la taxonomia SCT: los 54 caen del lado
correcto. Los casos frontera son los que importan y tambien salen bien —
camioneta de 46 px y van de pasajeros de 50 px del lado liviano; camion con
pipa de 53 px y autobus de 58 px del lado pesado.

Y en agregado, con holdout temporal (se calibra con 07:00-08:30 y se mide
con 08:30-10:00) contra el aforo contado a mano:

    calzada cercana    livianos 0.98x   pesados 1.09x
    calzada del fondo  livianos 1.03x   pesados 0.63x

Por eso `clasificar_calzada` devuelve SIN_RESOLVER en la calzada del fondo:
a 15-17 px de alto un camion y un automovil miden lo mismo, y el barrido de
umbrales va de 0.77x a 0.43x sin acertar nunca. Es preferible no dar el
dato que darlo mal.
"""
from __future__ import annotations

import statistics
from typing import Iterable, Optional

# Clases de COCO que nunca son vehiculo pesado, midan lo que midan.
LIVIANAS_COCO = ("car", "motorcycle", "bicycle")

# Etiquetas de salida. Se usan los nombres de la empresa, no los de COCO.
LIVIANO = "A"           # automoviles, camionetas, pickups, vans ligeras
PESADO = "PESADO"       # autobuses, camiones unitarios y articulados
SIN_RESOLVER = "SIN_RESOLVER"

# Multiplo del alto mediano del automovil por encima del cual un `truck` de
# COCO es de verdad un vehiculo pesado. Calibrado contra el conteo manual:
# 1.55 con la primera mitad de la mañana, 1.61 con la ventana completa. Se
# toma el punto medio. El barrido de sensibilidad deja los livianos entre
# 0.96x y 1.01x para cualquier valor entre 1.3 y 2.0, asi que la cifra
# exacta no es critica; lo que importa es que exista el corte.
MULTIPLO = 1.58

# Alto mediano minimo del automovil para que la regla signifique algo.
#
# Medido en los dos extremos: a 32 px de mediana la regla acierta (pesados
# 1.09x sobre datos no usados para calibrar); a 15 px falla (0.63x). Entre
# medias NO esta medido, asi que el corte se pone alto a proposito: mas
# vale devolver SIN_RESOLVER que publicar un desglose que no aguanta que lo
# revisen.
MINIMO_RESOLUBLE = 25.0


def umbral_de_calzada(alturas_de_autos: Iterable[float]) -> Optional[float]:
    """Alto a partir del cual un `truck` cuenta como pesado en esa calzada.

    None cuando no hay automoviles suficientes para fijar la escala: sin
    escala el umbral seria un numero inventado.
    """
    alturas = [h for h in alturas_de_autos if h and h > 0]
    if len(alturas) < 30:
        return None
    mediana = statistics.median(alturas)
    if mediana < MINIMO_RESOLUBLE:
        return None
    return MULTIPLO * mediana


def clasificar(tipo_coco: str, alto: Optional[float],
               umbral: Optional[float]) -> str:
    """Clase SCT de un cruce. SIN_RESOLVER si la calzada no da para separar.

    Sin umbral no se clasifica NADA, ni siquiera lo que COCO llama `car`.
    Es deliberado: donde el vehiculo mide 15 px la etiqueta de COCO tampoco
    es de fiar —la confianza media cae a 0.66— asi que un `car` de esa
    calzada puede ser un camion mal visto. Clasificar solo los `car` dejaria
    escapar una cifra parcial que se lee como total: en la calzada del fondo
    daba "A = 1 800" cuando el conteo manual dice 2 420.
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

    Cada cruce necesita `vehicle_type` y `bbox_height`. Se calcula el
    umbral con los propios automoviles de esa calzada, que es lo que hace
    que la regla valga tambien donde la escala es otra.
    """
    umbral = umbral_de_calzada(
        c.get("bbox_height") for c in cruces if c.get("vehicle_type") == "car"
    )
    conteos: dict[str, int] = {LIVIANO: 0, PESADO: 0, SIN_RESOLVER: 0}
    for c in cruces:
        conteos[clasificar(c.get("vehicle_type", ""), c.get("bbox_height"), umbral)] += 1
    return conteos, umbral


def exactitud_declarable(umbral: Optional[float]) -> str:
    """Que se puede escribir en un informe sobre esta clasificacion."""
    if umbral is None:
        return ("Sin desglose por tipo: el vehiculo se ve demasiado pequeno en "
                "esta calzada para separar liviano de pesado de forma "
                "defendible.")
    return ("Desglose liviano/pesado contrastado contra aforo manual: "
            "livianos 0.98x, pesados 1.09x sobre datos no usados para "
            "calibrar. No se separa autobus de camion.")
