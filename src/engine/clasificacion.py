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

# Clases FINAS. Solo salen donde estan medidas; ver ALTO_FINO abajo.
MOTO = "MOTO"           # motocicleta
AUTOBUS = "B"           # autobus de pasajeros
CAMION = "C"            # camion unitario y articulado (lo que no es autobus)

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

# Alto mediano del automovil desde el cual se separan MOTO y AUTOBUS
# ademas de liviano y pesado.
#
# NO es un numero elegido: es donde esta MEDIDO. En la camara frontal de
# Cd. Juarez (automovil de 123-126 px) se revisaron los recortes uno por
# uno y salieron 15 de 15 -5 trocas, 6 camiones y 4 autobuses- y las motos
# quedaron en 0.68-0.81 de razon ancho/alto contra 1.37-1.69 del automovil.
# Con la camara vieja, donde el autobus medida 65-90 px, YOLO no lo separaba
# del camion y esto no se intentaba.
#
# Entre 25 y 100 px no esta probado. Se deja alto a proposito: una clase
# equivocada cambia el entregable, y aqui se prefiere no darla.
ALTO_FINO = 100.0

# Una moto es ANGOSTA. El corte va como FRACCION de la silueta del
# automovil de esa misma calzada, no en un numero fijo, porque la razon
# ancho/alto depende del angulo de la camara: en el aforo frontal el
# automovil da 1.69 en una calzada y 1.37 en la otra.
MOTO_RAZON = 0.7

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


def perfil_de_calzada(cruces) -> dict:
    """Lo que hace falta para las clases finas: tamaño y silueta del automovil.

    Devuelve `{"fino": bool, "alto_auto": px, "razon_auto": ancho/alto}`.
    `fino` dice si esta calzada da para separar MOTO y AUTOBUS ademas de
    liviano y pesado; ver ALTO_FINO.

    La silueta del automovil se mide en la MISMA calzada porque depende del
    angulo: en el aforo frontal de Cd. Juarez el automovil da 1.69 de
    ancho/alto en una calzada y 1.37 en la otra, y un corte fijo para la
    moto habria fallado en una de las dos.
    """
    autos = [c for c in cruces if c.get("vehicle_type") == "car"
             and c.get("bbox_height")]
    if len(autos) < 30:
        return {"fino": False, "alto_auto": None, "razon_auto": None}
    alto_auto = statistics.median(c["bbox_height"] for c in autos)
    razones = [c["bbox_width"] / c["bbox_height"] for c in autos
               if c.get("bbox_width") and c["bbox_height"]]
    razon = statistics.median(razones) if len(razones) >= 30 else None
    return {"fino": alto_auto >= ALTO_FINO,
            "alto_auto": alto_auto, "razon_auto": razon}


def clasificar(tipo_coco: str, alto: Optional[float],
               umbral: Optional[float], ancho: Optional[float] = None,
               perfil: Optional[dict] = None) -> str:
    """Clase SCT de un cruce. SIN_RESOLVER si la calzada no da para separar.

    Sin umbral no se clasifica NADA, ni siquiera lo que COCO llama `car`:
    donde la calzada no resuelve, la etiqueta de COCO tampoco es de fiar, y
    clasificar solo los `car` dejaria escapar una cifra parcial que se lee
    como total.

    Con `perfil` de una calzada que da para clases finas (ver ALTO_FINO)
    devuelve MOTO / A / B / C en vez de A / PESADO. Sin perfil, o en una
    calzada que no da, se comporta exactamente como antes: eso es lo que
    permite que el mismo codigo sirva al aforo viejo de 15 px.
    """
    if umbral is None:
        return SIN_RESOLVER
    fino = bool(perfil and perfil.get("fino"))

    if tipo_coco == "motorcycle" and fino:
        razon_auto = perfil.get("razon_auto")
        if ancho and alto and razon_auto:
            # Una "moto" tan ancha como un automovil es un automovil mal
            # etiquetado. Medido en el aforo frontal: 1 de 133.
            if ancho / alto > MOTO_RAZON * razon_auto:
                return LIVIANO
        return MOTO

    if tipo_coco in LIVIANAS_COCO:
        return LIVIANO
    if alto is None:
        return SIN_RESOLVER
    if tipo_coco == "bus":
        # El autobus solo se declara aparte donde esta medido. Con la camara
        # vieja media 65-90 px y YOLO no lo separaba del camion.
        return AUTOBUS if fino else PESADO
    if alto <= umbral:
        return LIVIANO
    return CAMION if fino else PESADO


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
    """Que se puede escribir en un informe sobre este desglose.

    Las cifras que cita son las de la CALIBRACION —Cd. Juarez, camara
    lateral, contra el conteo manual de la empresa— y no son la exactitud
    del aforo que se este mirando. El nivel dice que la calzada da para
    clasificar; no dice que este aforo se haya contrastado con nada.

    Se nombra la fuente a proposito: el multiplo 1.58 se midio con esa
    camara y nadie ha comprobado que viaje a otra. Antes de entregar un
    desglose de una camara nueva, `tools/silueta_clases.py`.
    """
    if nivel == MEDIDO:
        return ("Desglose liviano/pesado MEDIDO: en esta calzada el vehiculo "
                "se ve con holgura y el umbral se calcula sobre sus propios "
                "automoviles. La regla se calibro en Cd. Juarez (camara "
                "lateral) contra aforo manual: composicion a 0.1 puntos, "
                "livianos 0.98x y pesados 1.09x sobre datos no usados para "
                "calibrar.")
    if nivel == ESTIMADO:
        return ("Desglose liviano/pesado ESTIMADO: usar los porcentajes, no "
                "las cifras. En la calzada donde se calibro (Cd. Juarez, "
                "camara lateral) la proporcion salia a 1.8 puntos del aforo "
                "manual con el conteo absoluto corto (0.84x). No se separa "
                "autobus de camion.")
    return ("Sin desglose por tipo: el vehiculo se ve demasiado pequeno en "
            "esta calzada, o las condiciones de luz no permiten "
            "identificarlo.")
