#!/usr/bin/env python3
"""
Compara lo que cuenta el sistema contra un aforo real medido en campo.

Esta es la unica herramienta que da una cifra de exactitud *absoluta*. Todo
lo demas que se ha medido en el proyecto es relativo ("cuenta un 43 % mas
que antes"), y un informe de aforo tiene que declarar una exactitud.

La referencia son los reportes del contador de ejes de la estacion
"Miguel de la madrid" del 19-ago-2026, uno por sentido, en
referencias/aforo_real/.

AVISO sobre la referencia, que cambia como se lee el resultado: cada archivo
declara "Number of Lanes : 1", con un contador distinto por sentido (serie
19079 y 140084). El tubo mide UN carril; la camara ve la calzada completa.
Donde la calzada tenga mas de un carril, lo nuestro debe salir *por encima*
del tubo sin que eso sea un error. Por eso se reporta la razon y no un
"porcentaje de acierto" a secas.

Uso:
    python tools/comparar_aforo_real.py --proyecto 11
    python tools/comparar_aforo_real.py --proyecto 11 --salida data/comparacion.csv
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
REFERENCIAS = RAIZ / "referencias" / "aforo_real"
BD = RAIZ / "data" / "traffic.db"


def leer_contador(ruta: Path) -> tuple[str, str, dict[int, float]]:
    """Devuelve (sentido, fecha, {minuto_del_dia: vehiculos}) de un reporte.

    Dos detalles del formato que costaron descubrir:

    1. La columna del total se RECORRE entre bloques de pagina (c23 en el
       primero, c22 en los siguientes). Se toma la ultima celda numerica de
       la fila, que el propio archivo garantiza que es la suma de las clases.
    2. Despues de los datos viene un resumen que repite los totales; hay que
       cortar ahi o todo se cuenta dos veces.
    """
    import xlrd  # solo aqui: el .xls viejo no lo lee openpyxl

    hoja = xlrd.open_workbook(str(ruta)).sheet_by_index(0)

    def texto(fila: int) -> str:
        return " ".join(str(hoja.cell_value(fila, c)) for c in range(hoja.ncols))

    sentido, fecha, corte = ruta.stem, "", hoja.nrows
    for r in range(hoja.nrows):
        linea = texto(r)
        if "Info Line 1" in linea:
            partes = [
                str(hoja.cell_value(r, c)).strip()
                for c in range(hoja.ncols)
                if str(hoja.cell_value(r, c)).strip()
            ]
            if len(partes) > 1:
                sentido = partes[1]
        if not fecha and "Data From:" in linea:
            fecha = linea.split("From:")[1].split("-", 1)[1].strip()[:10]
        if "Axle Data Summary" in linea:
            corte = r
            break

    por_minuto: dict[int, float] = {}
    for r in range(20, corte):
        fila = [hoja.cell_value(r, c) for c in range(hoja.ncols)]
        hora = fila[2]
        if not (isinstance(hora, float) and 0.0 <= hora < 1.0):
            continue
        minuto = round(hora * 24 * 60)
        if minuto % 15:
            continue
        numeros = [v for c, v in enumerate(fila) if c > 2 and isinstance(v, float)]
        if numeros:
            # Asignar y no acumular: las paginas no se solapan, pero el
            # resumen si repetiria los valores si no se hubiera cortado.
            por_minuto[minuto] = numeros[-1]
    return sentido, fecha, por_minuto


def cargar_referencia(carpeta: Path) -> dict[str, dict[int, float]]:
    archivos = sorted(carpeta.glob("*.xls"))
    if not archivos:
        sys.exit(f"No hay reportes .xls en {carpeta}")
    real: dict[str, dict[int, float]] = {}
    for ruta in archivos:
        sentido, fecha, datos = leer_contador(ruta)
        print(
            f"  {ruta.name}: sentido {sentido}, {fecha}, "
            f"{len(datos)}/96 cuartos de hora, {int(sum(datos.values()))} vehiculos"
        )
        real[sentido] = datos
    return real


def diagnosticar_sin_cruces(bd: Path, proyecto: int) -> str:
    """Un proyecto sin cruces casi siempre es un proyecto que todavia no ha
    contado, no un error. Se dice cual es el caso y que sigue, en vez de
    dejar al usuario mirando un "no tiene cruces"."""
    con = _conectar_ro(bd)
    estados = dict(
        con.execute(
            "select status, count(*) from video_jobs where project_id=? group by status",
            (proyecto,),
        ).fetchall()
    )
    con.close()
    if not estados:
        return f"El proyecto {proyecto} no tiene videos."
    resumen = ", ".join(f"{n} {e}" for e, n in sorted(estados.items()))
    if estados.get("awaiting_calibration"):
        return (
            f"El proyecto {proyecto} todavia no ha contado nada ({resumen}).\n"
            "Revisa el encuadre en la plataforma y presiona 'Empezar conteo'.\n"
            "Vuelve a correr esto cuando los videos esten en 'listo'."
        )
    if estados.get("queued") or estados.get("processing"):
        return f"El proyecto {proyecto} sigue contando ({resumen}). Espera a que termine."
    return f"El proyecto {proyecto} no tiene cruces ({resumen})."


def _conectar_ro(bd: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{bd}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def cargar_nuestro(bd: Path, proyecto: int) -> tuple[dict[str, dict[int, int]], set[int]]:
    """Cruces del proyecto por calzada y cuarto de hora, y los minutos que el
    video realmente cubre: sin eso se compara contra horas no grabadas."""
    con = _conectar_ro(bd)

    # Solo los videos YA CONTADOS. Con la cola a medias, incluir los que
    # faltan hace creer que el video cubre tres horas cuando solo se han
    # contado veinte minutos, y entonces se comparan nuestros veinte
    # minutos contra tres horas de tubo: el resultado sale por los suelos
    # sin que nada este mal. Se acepta tambien un video sin cruces si ya
    # esta 'done', porque un tramo vacio de madrugada es un dato valido.
    cubiertos: set[int] = set()
    for r in con.execute(
        "select v.video_start_time t, v.total_frames f, v.fps from video_jobs v "
        "where v.project_id=? and v.video_start_time is not null "
        "  and (v.status = 'done' "
        "       or exists (select 1 from crossings x where x.job_id = v.id))",
        (proyecto,),
    ):
        h, m, _ = map(int, r["t"][11:].split(":"))
        dur = int((r["f"] or 0) / (r["fps"] or 15) / 60)
        cubiertos.update(range(h * 60 + m, h * 60 + m + dur))

    nuestro: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for r in con.execute(
        "select z.name zona, x.timestamp ts from crossings x "
        "join video_jobs v on v.id=x.job_id left join zones z on z.id=x.zone_id "
        "where v.project_id=?",
        (proyecto,),
    ):
        minuto = int(r["ts"][11:13]) * 60 + int(r["ts"][14:16])
        nuestro[r["zona"] or "sin zona"][(minuto // 15) * 15] += 1
    con.close()
    return {k: dict(v) for k, v in nuestro.items()}, cubiertos


def _correlacion(a, b):
    """None cuando no se puede calcular: con pocos intervalos, o cuando una
    de las dos series es constante, la correlacion no esta definida."""
    if len(a) < 3:
        return None
    try:
        return statistics.correlation(a, b)
    except statistics.StatisticsError:
        return None


def emparejar(real, nuestro, bins):
    """Ata cada calzada nuestra al sentido real con el que su perfil temporal
    correlaciona mas.

    Se hace por los datos y no por el nombre porque "Calzada poniente" es
    ambiguo: puede ser la calzada del lado poniente o la que lleva al
    poniente, y equivocarse invierte la comparacion entera.

    El emparejamiento es UNO A UNO. Antes cada calzada elegia su mejor
    sentido por separado, y con pocos intervalos —cuando la correlacion no
    se puede calcular y todas empatan— las dos calzadas se quedaban con el
    mismo sentido: el informe mostraba el mismo "real" dos veces y los
    porcentajes no sumaban 100.
    """
    puntajes = []
    for zona, datos in nuestro.items():
        v = [datos.get(b, 0) for b in bins]
        for sentido, d in real.items():
            c = _correlacion([d.get(b, 0) for b in bins], v)
            puntajes.append((c if c is not None else -2.0, c, zona, sentido))

    pares, zonas_por_atar, sentidos_libres = {}, set(nuestro), set(real)
    for _, c, zona, sentido in sorted(puntajes, key=lambda p: -p[0]):
        if zona in zonas_por_atar and sentido in sentidos_libres:
            pares[zona] = (sentido, c)
            zonas_por_atar.discard(zona)
            sentidos_libres.discard(sentido)
    # Si sobran calzadas (mas calzadas que sentidos) quedan sin pareja.
    for zona in zonas_por_atar:
        pares[zona] = (None, None)
    return pares


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--proyecto", type=int, required=True)
    p.add_argument("--referencias", type=Path, default=REFERENCIAS)
    p.add_argument("--bd", type=Path, default=BD)
    p.add_argument("--salida", type=Path, help="CSV con el detalle por cuarto de hora")
    a = p.parse_args()

    print("Aforo real de referencia:")
    real = cargar_referencia(a.referencias)
    nuestro, cubiertos = cargar_nuestro(a.bd, a.proyecto)
    if not nuestro:
        sys.exit(diagnosticar_sin_cruces(a.bd, a.proyecto))

    # Solo los cuartos de hora cubiertos ENTEROS por el video: uno a medias
    # compara 15 minutos de tubo contra 2 de camara y ensucia el resultado.
    bins = sorted(
        b for b in range(0, 24 * 60, 15) if all(m in cubiertos for m in range(b, b + 15))
    )
    if not bins:
        sys.exit("El video no cubre ningun cuarto de hora completo.")
    print(
        f"\nVentana comparable: {bins[0] // 60:02d}:{bins[0] % 60:02d} a "
        f"{(bins[-1] + 15) // 60:02d}:{(bins[-1] + 15) % 60:02d}  "
        f"({len(bins)} cuartos de hora)"
    )

    pares = emparejar(real, nuestro, bins)
    print("\nCalzada nuestra -> sentido real (emparejado por correlacion del perfil):")
    for zona, (sentido, r) in sorted(pares.items()):
        marca = f"r = {r:+.2f}" if r is not None else "r no calculable"
        print(f"  {zona:<20} -> {str(sentido):<12} {marca}")
    if len(bins) < 4:
        print(f"  AVISO: solo {len(bins)} cuartos de hora contados. Con tan pocos, el")
        print("  emparejamiento calzada-sentido no es fiable; puede estar invertido.")

    print("\n=== Totales en la ventana comparable ===")
    print(f"{'calzada':<20}{'nuestro':>10}{'real':>10}{'razon':>9}")
    tn = tr = 0
    for zona, (sentido, _) in sorted(pares.items()):
        n = sum(nuestro[zona].get(b, 0) for b in bins)
        rr = sum(real[sentido].get(b, 0) for b in bins) if sentido else 0
        tn, tr = tn + n, tr + rr
        razon = f"{n / rr:.2f}x" if rr else "-"
        print(f"{zona:<20}{n:>10}{int(rr):>10}{razon:>9}")
    if tr:
        print(f"{'AMBOS SENTIDOS':<20}{tn:>10}{int(tr):>10}{tn / tr:>8.2f}x")

    print("\n=== Reparto entre sentidos ===")
    reparto_real = " / ".join(
        f"{100 * sum(real[s].get(b, 0) for b in bins) / tr:.0f}% {s}" for s in sorted(real)
    )
    reparto_nuestro = " / ".join(
        f"{100 * sum(nuestro[z].get(b, 0) for b in bins) / tn:.0f}% {z}"
        for z in sorted(nuestro)
    )
    print(f"  real:    {reparto_real}")
    print(f"  nuestro: {reparto_nuestro}")

    sr = [sum(d.get(b, 0) for d in real.values()) for b in bins]
    sn = [sum(d.get(b, 0) for d in nuestro.values()) for b in bins]
    print(
        f"\nCorrelacion del perfil temporal (ambos sentidos): "
        f"r = {statistics.correlation(sr, sn):+.2f}"
    )
    print("  r alto con razon lejos de 1 = el detector si ve el transito real,")
    print("  pero la escala esta mal. r bajo = no lo esta viendo.")

    if a.salida:
        a.salida.parent.mkdir(parents=True, exist_ok=True)
        with open(a.salida, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            zonas = sorted(nuestro)
            w.writerow(
                ["hora"]
                + [f"real_{pares[z][0]}" for z in zonas]
                + [f"nuestro_{z}" for z in zonas]
            )
            for b in bins:
                w.writerow(
                    [f"{b // 60:02d}:{b % 60:02d}"]
                    + [int(real[pares[z][0]].get(b, 0)) for z in zonas]
                    + [nuestro[z].get(b, 0) for z in zonas]
                )
        print(f"\nDetalle por cuarto de hora en {a.salida}")


if __name__ == "__main__":
    main()
