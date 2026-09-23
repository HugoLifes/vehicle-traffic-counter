"""
Pegar los segmentos de un minuto en tramos mas largos, sin perder la hora.

POR QUE, y por que NO por las razones obvias. Medido sobre 52 videos ya
contados del aforo frontal, contando los cruces por segundo dentro de cada
archivo:

    segundo 0 de cada video    48 % de los cruces normales
    segundo 1                  76 %
    segundo 2 en adelante      normal

El vehiculo que va cruzando la linea justo cuando empieza el archivo **no se
cuenta**: el rastreador necesita ver la caja unos cuadros antes de la linea
para registrar el cruce, y al empezar el archivo ese pasado no existe. Sale
**alrededor del 1 %** del aforo, y siempre hacia abajo. Con 730 archivos de
un minuto ese 1 % se paga 730 veces; en tramos de 10 minutos se paga 73.

Lo que unir los segmentos **NO** arregla, tambien medido:

  · **No acelera el proceso.** La cola no tiene un segundo muerto entre
    videos (el `finished_at` de uno es el `started_at` del siguiente), asi
    que no hay costo fijo por archivo que ahorrar. El trabajo es por cuadro.
  · **No ahorra disco.** Los mismos bytes en menos archivos. Lo que llena el
    disco es el video ANOTADO (31.3 MB por minuto contra 16 del archivo de
    la camara), y eso se apaga por proyecto con `video_anotado`.

EL RIESGO, que es serio y por eso esta herramienta es tan desconfiada. La
hora de cada cruce sale de la hora de inicio del archivo mas el numero de
cuadro. Si se pegan segmentos y **falta uno en medio**, todo lo que sigue
queda corrido por un minuto y nadie se entera: los cuartos de hora del
reporte salen mal sin un solo error en el log. En este mismo material ya hay
un archivo cortado (el de las 12:25, que no abre), asi que el riesgo no es
teorico.

Por eso:

  1. Solo se pegan minutos **consecutivos**. En cuanto falta uno, se cierra
     el tramo y empieza otro.
  2. Cada segmento tiene que **durar lo que dice** (60 s ± tolerancia). Uno
     corto corre todo lo que va detras.
  3. Al terminar se **comprueba la duracion** del tramo contra la suma de
     sus partes. Si no cuadra, el tramo se descarta.
  4. El nombre del tramo es el del primer segmento, que es de donde la
     plataforma saca la hora.

No se re-codifica: `ffmpeg -c copy` copia los flujos tal cual, asi que es
rapido y no pierde calidad. Y **nunca borra los originales.**

    python tools/unir_segmentos.py --entrada data/nuevos/20260919/12 \\
        --salida data/nuevos/unidos --minutos 10
    python tools/unir_segmentos.py --entrada data/nuevos/20260919 \\
        --salida data/nuevos/unidos --minutos 10 --recursivo
"""

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

# La hora sale del NOMBRE, nunca de la leyenda de la camara: en este
# material el OSD se atraso cerca de un mes a partir de las 12:25 y los
# videos siguen completos.
PATRON_HORA = re.compile(r"(\d{2})[-_:](\d{2})[-_:](\d{2})")

# Un segmento que no dura lo que dice corre a todos los que van detras.
TOLERANCIA_S = 1.5


def ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def duracion(ruta):
    """Segundos del archivo, o None si no abre."""
    # imageio_ffmpeg trae ffmpeg pero no ffprobe; si el sistema tiene uno,
    # es mucho mas rapido que abrir el archivo con OpenCV.
    from shutil import which
    exe = which("ffprobe") or ""
    if exe:
        r = subprocess.run([exe, "-v", "error", "-show_entries", "format=duration",
                            "-of", "json", ruta], capture_output=True, text=True)
        if r.returncode == 0:
            try:
                return float(json.loads(r.stdout)["format"]["duration"])
            except (KeyError, ValueError):
                pass
    # Sin ffprobe: OpenCV, que ya es dependencia del proyecto.
    import cv2
    cap = cv2.VideoCapture(ruta)
    if not cap.isOpened():
        return None
    fps = cap.get(cv2.CAP_PROP_FPS) or 0
    n = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    cap.release()
    return (n / fps) if fps > 0 and n > 0 else None


def hora_de(nombre):
    m = PATRON_HORA.search(os.path.basename(nombre))
    if not m:
        return None
    h, mi, s = (int(x) for x in m.groups())
    if h > 23 or mi > 59 or s > 59:
        return None
    return dt.timedelta(hours=h, minutes=mi, seconds=s)


def segmentos(entrada, recursivo):
    exts = (".mp4", ".mkv", ".avi", ".mov")
    rutas = []
    for raiz, _, archivos in os.walk(entrada):
        for a in archivos:
            if a.lower().endswith(exts):
                rutas.append(os.path.join(raiz, a))
        if not recursivo:
            break
    con_hora = [(hora_de(r), r) for r in rutas]
    sin_hora = [r for h, r in con_hora if h is None]
    if sin_hora:
        print(f"  {len(sin_hora)} archivos sin hora en el nombre, se omiten "
              f"(p. ej. {os.path.basename(sin_hora[0])})")
    return sorted((h, r) for h, r in con_hora if h is not None)


def tramos(lista, minutos, verbose=True):
    """Parte la lista en rachas de minutos consecutivos y de buena duracion."""
    salida, actual, fin_esperado = [], [], None
    for hora, ruta in lista:
        d = duracion(ruta)
        if d is None:
            if verbose:
                print(f"  {os.path.basename(ruta)}: no abre, corta el tramo")
            if actual:
                salida.append(actual)
            actual, fin_esperado = [], None
            continue
        hueco = (fin_esperado is not None
                 and abs((hora - fin_esperado).total_seconds()) > TOLERANCIA_S)
        lleno = bool(actual) and sum(x[2] for x in actual) >= minutos * 60
        if hueco and verbose:
            print(f"  hueco de {(hora - fin_esperado).total_seconds():.0f} s "
                  f"antes de {os.path.basename(ruta)}: corta el tramo")
        if actual and (hueco or lleno):
            salida.append(actual)
            actual = []
        actual.append((hora, ruta, d))
        fin_esperado = hora + dt.timedelta(seconds=d)
    if actual:
        salida.append(actual)
    return salida


def unir(tramo, carpeta_salida):
    primero = tramo[0][1]
    destino = os.path.join(carpeta_salida, os.path.basename(primero))
    esperado = sum(x[2] for x in tramo)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                     encoding="utf-8") as lista:
        for _, ruta, _ in tramo:
            lista.write(f"file '{os.path.abspath(ruta)}'\n")
        nombre_lista = lista.name
    try:
        r = subprocess.run(
            [ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", nombre_lista,
             "-c", "copy", destino],
            capture_output=True, text=True)
    finally:
        os.unlink(nombre_lista)
    if r.returncode != 0:
        return None, f"ffmpeg falló: {r.stderr[-200:]}"
    real = duracion(destino)
    # El candado que importa: si el tramo no dura lo que suman sus partes,
    # las horas de todo lo que va detras del hueco saldrian corridas.
    if real is None or abs(real - esperado) > TOLERANCIA_S:
        os.unlink(destino)
        return None, (f"dura {real:.1f} s y sus partes suman {esperado:.1f}: "
                      "se descarta para no correr las horas")
    return destino, None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--entrada", required=True)
    ap.add_argument("--salida", required=True)
    ap.add_argument("--minutos", type=int, default=10,
                    help="largo objetivo de cada tramo (10 por omisión)")
    ap.add_argument("--recursivo", action="store_true",
                    help="bajar a las subcarpetas (una por hora)")
    ap.add_argument("--simular", action="store_true",
                    help="decir qué haría sin escribir nada")
    a = ap.parse_args()

    lista = segmentos(a.entrada, a.recursivo)
    if not lista:
        sys.exit("No hay videos con hora en el nombre en esa carpeta")
    print(f"{len(lista)} segmentos, de {lista[0][0]} a {lista[-1][0]}")

    grupos = tramos(lista, a.minutos)
    print(f"{len(grupos)} tramos")
    if a.simular:
        for g in grupos:
            print(f"  {os.path.basename(g[0][1])}  {len(g)} partes  "
                  f"{sum(x[2] for x in g) / 60:.1f} min")
        cortes_antes, cortes_despues = len(lista), len(grupos)
        print(f"\ncortes de archivo: {cortes_antes} -> {cortes_despues} "
              f"({100 * (1 - cortes_despues / cortes_antes):.0f} % menos)")
        return

    os.makedirs(a.salida, exist_ok=True)
    hechos, fallos = 0, 0
    for g in grupos:
        destino, error = unir(g, a.salida)
        if error:
            print(f"  {os.path.basename(g[0][1])}: {error}")
            fallos += 1
        else:
            print(f"  {os.path.basename(destino)}  {len(g)} partes  "
                  f"{sum(x[2] for x in g) / 60:.1f} min")
            hechos += 1
    print(f"\n{hechos} tramos escritos en {a.salida}, {fallos} descartados")
    print("Los archivos originales NO se tocaron.")


if __name__ == "__main__":
    main()
