"""
Si la regla de clase tiene sentido en ESTA camara, antes de entregar nada.

La regla de liviano/pesado se calibro contra el conteo manual de Cd. Juarez
con la camara DE LADO: el umbral es 1.58 veces el alto mediano del
automovil de esa calzada. El multiplo viaja bien entre calzadas de una misma
camara —eso esta medido— pero **nadie ha comprobado que viaje entre
camaras**, y de frente la silueta del vehiculo es otra: de lado un camion se
ve larguisimo y de frente se ve alto y ancho.

Esta herramienta no decide nada; ensena lo que hay para poder decidir:

    python tools/silueta_clases.py --proyecto 7

Por cada carril saca el alto y el ancho de cada clase de COCO en la linea,
el umbral que la regla va a aplicar, y de que lado cae cada vehiculo. Tres
preguntas que se contestan de un vistazo:

  · el umbral, ¿lo alcanza ALGUN vehiculo? Si ningun `truck` lo pasa, o la
    camara no vio ningun pesado en toda la muestra, o el multiplo no aplica
    aqui. Las dos cosas hay que saberlas antes de entregar un desglose.
  · los `truck`, ¿salen en dos grupos? Con la camara de lado salian: la
    pickup (que en la taxonomia SCT es A, un automovil) y el camion de
    verdad. Ese es el corte que la regla busca.
  · las `motorcycle`, ¿tienen silueta de moto? Una moto es ANGOSTA. Una
    "moto" tan ancha como un automovil es un automovil mal etiquetado, y de
    esos hubo 113 en una sola calzada antes de que la clase la decidiera el
    rastro entero.

Lo que mide es la silueta EN LA LINEA, nunca en toda la zona: el mismo
vehiculo mide distinto segun lo lejos que este, y mezclar distancias deja al
alto sin significado, que es la premisa entera de la regla.

Despues de mirar estos numeros, mirar los vehiculos:

    python tools/hoja_cruces.py --job N --carril M --clase truck --salida data/t.png
"""

import argparse
import os
import statistics as st
import sys
from collections import Counter

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from src.engine.clasificacion import (ALTO_MEDIDO, MULTIPLO, NO_RESOLUBLE,  # noqa: E402
                                      nivel_de_calzada)
from src.storage import traffic_db                                          # noqa: E402

# Una moto es angosta: su ancho sobre su alto queda muy por debajo del de un
# automovil. El corte se pone a medio camino entre las dos medianas del
# carril, no en un numero fijo, porque depende del angulo de la camara.
MINIMO_MOTOS = 8


def mediana(xs, d=0):
    xs = [x for x in xs if x is not None]
    return round(st.median(xs), d) if xs else None


def percentil(xs, q):
    xs = sorted(x for x in xs if x is not None)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else None


def corte_en_dos(valores):
    """El corte que mejor parte estos valores en dos grupos, o None.

    Es el metodo de Otsu, el mismo que usa la vision por computadora para
    separar tinta de papel: se prueba cada corte y se queda con el que deja
    los dos grupos mas apartados entre si. Se busca a proposito un metodo
    que no mire ningun umbral nuestro, para que sirva de segunda opinion
    sobre donde esta el corte de verdad en esta camara.

    Devuelve None cuando no hay dos grupos: si el mejor corte deja un grupo
    casi vacio, o las dos medianas se parecen, lo que hay es una sola
    poblacion y anunciar un corte seria inventarlo.
    """
    v = sorted(x for x in valores if x)
    if len(v) < 30:
        return None
    mejor, corte = -1.0, None
    for i in range(len(v) // 10, len(v) - len(v) // 10):
        if v[i] == v[i + 1]:
            continue
        a, b = v[:i + 1], v[i + 1:]
        # Varianza entre grupos: cuanto se apartan sus medias, pesado por
        # su tamano. El maximo es el corte natural.
        entre = (len(a) * len(b) / len(v) ** 2) * (st.fmean(b) - st.fmean(a)) ** 2
        if entre > mejor:
            mejor, corte = entre, v[i]
    if corte is None:
        return None
    a = [x for x in v if x <= corte]
    b = [x for x in v if x > corte]
    if min(len(a), len(b)) < 0.1 * len(v) or st.median(b) < 1.3 * st.median(a):
        return None
    return corte


def cruces_del_carril(conn, lane_id, job_ids=None):
    sql = ("""SELECT vehicle_type, bbox_height, bbox_width, confidence
              FROM crossings WHERE lane_id = ?""")
    p = [lane_id]
    if job_ids:
        sql += f" AND job_id IN ({','.join('?' * len(job_ids))})"
        p += list(job_ids)
    return [dict(r) for r in conn.execute(sql, p)]


def informe_carril(nombre, cruces):
    print(f"\n=== {nombre} · {len(cruces)} cruces ===")
    if not cruces:
        return

    altos_auto = [c["bbox_height"] for c in cruces if c["vehicle_type"] == "car"]
    nivel, umbral = nivel_de_calzada(
        altos_auto, (c["confidence"] for c in cruces))
    med_auto = mediana(altos_auto)
    print(f"automovil mediano {med_auto} px  ·  nivel {nivel}"
          + (f"  ·  umbral pesado {umbral:.0f} px ({MULTIPLO}x)"
             if umbral else "  ·  sin umbral"))
    if nivel == NO_RESOLUBLE and med_auto and med_auto >= ALTO_MEDIDO:
        print("  AVISO: el vehiculo se ve de sobra y aun asi no resuelve. "
              "Suele ser la confianza media (noche) o menos de 30 automoviles.")

    con_ancho = sum(1 for c in cruces if c["bbox_width"])
    if con_ancho < len(cruces):
        print(f"  {len(cruces) - con_ancho} cruces sin ancho guardado "
              "(se contaron antes de que se capturara)")

    print(f"\n  {'clase':12} {'n':>4} {'alto p25':>9} {'mediana':>8} {'p75':>6} "
          f"{'ancho':>7} {'ancho/alto':>11} {'conf':>6}")
    por_clase = {}
    for clase in sorted({c["vehicle_type"] for c in cruces}):
        g = [c for c in cruces if c["vehicle_type"] == clase]
        por_clase[clase] = g
        razones = [c["bbox_width"] / c["bbox_height"] for c in g
                   if c["bbox_width"] and c["bbox_height"]]
        print(f"  {clase:12} {len(g):>4} {percentil([c['bbox_height'] for c in g], .25) or 0:>9} "
              f"{mediana(c['bbox_height'] for c in g) or 0:>8} "
              f"{percentil([c['bbox_height'] for c in g], .75) or 0:>6} "
              f"{mediana(c['bbox_width'] for c in g) or 0:>7} "
              f"{(mediana(razones, 2) if razones else 0):>11} "
              f"{mediana((c['confidence'] for c in g), 2) or 0:>6}")

    # 1. ¿El umbral lo alcanza alguien?
    pesados_coco = [c for c in cruces
                    if c["vehicle_type"] in ("truck", "bus") and c["bbox_height"]]
    if umbral and pesados_coco:
        arriba = [c for c in pesados_coco if c["bbox_height"] > umbral]
        print(f"\n  de {len(pesados_coco)} truck/bus, {len(arriba)} pasan el umbral "
              f"de {umbral:.0f} px")
        if not arriba:
            print("  AVISO: NINGUNO lo pasa. O en esta muestra no hubo ningun "
                  "pesado de verdad,\n         o el multiplo 1.58 no aplica a "
                  "esta camara: se midio de lado,\n         donde un camion se "
                  "ve mucho mas alto respecto al automovil.")
        alt = sorted(c["bbox_height"] for c in pesados_coco)
        corte = corte_en_dos(alt)
        if corte:
            bajos = [h for h in alt if h <= corte]
            altos = [h for h in alt if h > corte]
            print(f"  se parten en dos grupos por si solos en {corte} px: "
                  f"{len(bajos)} de mediana {mediana(bajos):.0f} y "
                  f"{len(altos)} de mediana {mediana(altos):.0f}")
            # Dos grupos pueden ser dos TIPOS de vehiculo (que es lo que la
            # regla busca) o dos DISTANCIAS: una linea que recoge las dos
            # calzadas ve el mismo vehiculo el doble de alto en la cercana.
            # Lo que los separa es el automovil: un automovil siempre mide
            # lo mismo, asi que si TAMBIEN sale en dos grupos, lo que hay
            # son dos distancias y el corte no dice nada del tipo.
            if corte_en_dos([c["bbox_height"] for c in por_clase.get("car", [])
                             if c["bbox_height"]]):
                print("  AVISO: el automovil tambien sale en dos grupos, y un "
                      "automovil no cambia\n         de tamano: esta linea esta "
                      "recogiendo DOS calzadas a distinta\n         distancia. "
                      "Eso es calibracion, no clasificacion — revisar la zona\n"
                      "         atada al carril antes de mirar ningun umbral.")
            elif umbral and not 0.7 * umbral <= corte <= 1.6 * umbral:
                print(f"  AVISO: el corte natural ({corte} px) no se parece al "
                      f"de la regla ({umbral:.0f} px).\n         El multiplo "
                      "1.58 se midio con la camara de lado; esta camara puede\n"
                      "         necesitar otro. Mirar los vehiculos con "
                      "hoja_cruces.py --clase truck.")
            else:
                print("         (ese corte es el que separa la pickup del "
                      "camion, y la regla\n          lo esta cortando en el "
                      "mismo sitio)")

    # 2. ¿Las motos tienen silueta de moto?
    motos = [c for c in por_clase.get("motorcycle", []) if c["bbox_width"] and c["bbox_height"]]
    autos = [c for c in por_clase.get("car", []) if c["bbox_width"] and c["bbox_height"]]
    if len(motos) >= MINIMO_MOTOS and len(autos) >= 30:
        r_moto = st.median(c["bbox_width"] / c["bbox_height"] for c in motos)
        r_auto = st.median(c["bbox_width"] / c["bbox_height"] for c in autos)
        corte = (r_moto + r_auto) / 2
        anchas = sum(1 for c in motos if c["bbox_width"] / c["bbox_height"] > corte)
        print(f"\n  motos: ancho/alto {r_moto:.2f} contra {r_auto:.2f} del automovil")
        if r_moto >= r_auto * 0.9:
            print("  AVISO: la moto no sale mas angosta que el automovil. "
                  "O no son motos,\n         o esta camara no separa la silueta.")
        elif anchas:
            print(f"  AVISO: {anchas} de {len(motos)} tienen silueta de automovil "
                  f"(ancho/alto > {corte:.2f}).\n         Hoy no cambia el "
                  "entregable (moto y automovil son ambos livianos),\n         "
                  "pero si se entrega la moto aparte, sobran.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--proyecto", type=int, required=True)
    ap.add_argument("--hora", default=None,
                    help="solo los cruces de esta hora (HH), p. ej. 08")
    a = ap.parse_args()

    conn = traffic_db.get_connection()
    carriles = traffic_db.list_lanes(project_id=a.proyecto)
    if not carriles:
        sys.exit("Ese proyecto no tiene carriles")
    total = Counter()
    for c in carriles:
        cruces = cruces_del_carril(conn, c["id"])
        if a.hora:
            cruces = [x for x in conn.execute(
                """SELECT vehicle_type, bbox_height, bbox_width, confidence
                   FROM crossings WHERE lane_id = ?
                     AND substr(timestamp, 12, 2) = ?""", (c["id"], a.hora))]
            cruces = [dict(x) for x in cruces]
        informe_carril(c["name"], cruces)
        total.update(x["vehicle_type"] for x in cruces)
    print("\ntotal por clase de COCO:",
          ", ".join(f"{k} {v}" for k, v in total.most_common()))


if __name__ == "__main__":
    main()
