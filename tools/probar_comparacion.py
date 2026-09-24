"""
Prueba de punta a punta de `comparar_aforo_real.py`, sobre un proyecto real
y ANTES de que llegue el conteo manual de la empresa.

Fabrica un conteo manual con el formato exacto que manda la empresa (dos
hojas, "Hr/Mov", bloques AM y PM, clases A B C T-S T-S-R, la fecha en el
titulo) a partir de los cruces del propio proyecto, con errores CONOCIDOS
metidos a proposito. Despues corre la herramienta y comprueba que los
encuentra:

  · el reloj corrido 3 minutos      -> tiene que avisar "3 min adelantado";
  · un sentido contado al 0.93x y el otro al 0.98x -> esas razones;
  · sin motocicletas en el conteo   -> la razon "sin motocicletas" es la buena;
  · sentidos escritos NTE-SUR       -> el lector tiene que reconocerlos.

Y que se NIEGA a comparar el proyecto contra el conteo de otro dia.

Sirve para no descubrir un fallo de la herramienta el dia que llegan los
datos buenos:

    python tools/probar_comparacion.py --proyecto 7 --salida data/prueba_comparacion

La primera version de esta prueba encontro que 7 videos de 58 s tiraban en
silencio sus cuartos de hora, y que el aviso de reloj gritaba lobo sobre un
aforo sin desfase.
"""

import argparse
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

DESFASE_MIN = 3             # la grabadora va 3 min adelantada
RAZON = (0.93, 0.98)        # lo que el sistema "captura" de cada sentido
SENTIDOS = ("NTE-SUR", "SUR-NTE")


def etiqueta(minuto):
    def hhmm(m):
        h, mi = divmod(m % 1440, 60)
        ap = "AM" if h < 12 else "PM"
        h12 = h % 12 or 12
        return f"{h12}:{mi:02d} {ap}"
    return f"{hhmm(minuto)} - {hhmm(minuto + 15)}"


def fabricar(bd, proyecto, carpeta):
    import sqlite3
    import statistics
    import openpyxl

    con = sqlite3.connect(f"file:{bd}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    zonas = [r["name"] for r in con.execute(
        "select distinct z.name from crossings x join zones z on z.id=x.zone_id "
        "join video_jobs v on v.id=x.job_id where v.project_id=? order by 1",
        (proyecto,))]
    if len(zonas) != 2:
        sys.exit(f"La prueba necesita un proyecto de dos calzadas; este tiene {zonas}")
    fecha = con.execute("select min(video_start_time) from video_jobs where "
                        "project_id=?", (proyecto,)).fetchone()[0][:10]

    # Umbral de pesado por calzada, como la regla: 1.58 x el automovil mediano.
    umbral = {}
    for z in zonas:
        altos = [r[0] for r in con.execute(
            "select x.bbox_height from crossings x join zones z on z.id=x.zone_id "
            "where z.name=? and x.vehicle_type='car' and x.bbox_height is not null", (z,))]
        umbral[z] = 1.58 * statistics.median(altos)

    # {sentido: {cuarto: {clase: n}}}, en hora VERDADERA: la grabadora va
    # DESFASE_MIN adelantada, asi que lo que su archivo dice 12:03 paso a las 12:00.
    conteo = {s: defaultdict(lambda: defaultdict(float)) for s in SENTIDOS}
    alterna = 0
    for r in con.execute(
            "select z.name zona, x.timestamp ts, x.vehicle_type vt, x.bbox_height h "
            "from crossings x join zones z on z.id=x.zone_id "
            "join video_jobs v on v.id=x.job_id where v.project_id=?", (proyecto,)):
        if r["vt"] == "motorcycle":
            continue                       # la empresa no las cuenta
        i = zonas.index(r["zona"])
        minuto = int(r["ts"][11:13]) * 60 + int(r["ts"][14:16]) - DESFASE_MIN
        if r["vt"] == "bus":
            clase = "B"
        elif r["vt"] == "truck" and (r["h"] or 0) > umbral[r["zona"]]:
            alterna += 1
            clase = "C" if alterna % 2 else "T-S"
        else:
            clase = "A"
        # El sistema captura RAZON[i]: el conteo "real" tiene 1/RAZON[i].
        conteo[SENTIDOS[i]][(minuto // 15) * 15][clase] += 1 / RAZON[i]
    con.close()

    libro = openpyxl.Workbook()
    libro.remove(libro.active)
    titulo = f"CRUCE DE PRUEBA {int(fecha[8:])}-SEPTIEMBRE-{fecha[:4]}"
    for s in SENTIDOS:
        h = libro.create_sheet(s)
        for col0 in (2, 9):               # bloque AM en B, bloque PM en I
            h.cell(3, col0, titulo)
            h.cell(4, col0, "Hr/Mov")
            h.cell(4, col0 + 1, s)
            for i, c in enumerate(("A", "B", "C", "T-S", "T-S-R"), start=1):
                h.cell(5, col0 + i, c)
        for k in range(48):
            for col0, base in ((2, 0), (9, 720)):
                m = base + 15 * k
                h.cell(6 + k, col0, etiqueta(m))
                for i, c in enumerate(("A", "B", "C", "T-S", "T-S-R"), start=1):
                    h.cell(6 + k, col0 + i, round(conteo[s][m][c]))
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / "conteo_manual_prueba.xlsx"
    libro.save(ruta)
    return ruta, zonas


def correr(args):
    r = subprocess.run([sys.executable, str(RAIZ / "tools" / "comparar_aforo_real.py")]
                       + args, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--proyecto", type=int, required=True)
    ap.add_argument("--bd", default=str(RAIZ / "data" / "traffic.db"))
    ap.add_argument("--salida", default=str(RAIZ / "data" / "prueba_comparacion"))
    a = ap.parse_args()

    ruta, zonas = fabricar(a.bd, a.proyecto, Path(a.salida))
    print(f"conteo de prueba: {ruta}")
    fallos = 0

    codigo, texto = correr(["--proyecto", str(a.proyecto), "--bd", a.bd,
                            "--referencias", a.salida])
    print(texto)

    def comprobar(ok, que):
        nonlocal fallos
        print(("ok   " if ok else "MAL  ") + que)
        fallos += 0 if ok else 1

    comprobar(codigo == 0, "la herramienta corre sobre el proyecto")
    comprobar("nte-sur" in texto and "sur-nte" in texto,
              "reconoce sentidos escritos NTE-SUR")
    comprobar(re.search(r"reloj del video parece ir 3 min adelantado", texto) is not None,
              f"encuentra el reloj corrido {DESFASE_MIN} min")
    # La razon que hay que recuperar es la de "sin motos": el conteo de
    # prueba no las trae, igual que el de la empresa. Con el reloj corrido
    # algunos vehiculos caen en el cuarto vecino, asi que sale cerca, no
    # exacta; la tolerancia es estrecha a proposito, porque la primera version
    # de esta prueba (0.03) dejo pasar un 3 % de motos metidas en la razon.
    for z, razon in zip(zonas, RAZON):
        m = re.search(rf"{re.escape(z)}\s+\d+\s+\d+\s+[\d.]+x\s+([\d.]+)x", texto)
        comprobar(m is not None and abs(float(m.group(1)) - razon) <= 0.015,
                  f"razon sin motos de {z}: {m.group(1) if m else '?'}x "
                  f"(se metio {razon}x)")
    m = re.search(r"AMBOS SENTIDOS\s+\d+\s+\d+\s+[\d.]+x\s+([\d.]+)x", texto)
    esperada = sum(RAZON) / 2
    comprobar(m is not None and abs(float(m.group(1)) - esperada) <= 0.015,
              f"ambos sentidos sin motos: {m.group(1) if m else '?'}x "
              f"(cerca de {esperada:.3f}x)")
    comprobar("Composicion por clase" in texto and "B autobus" in texto,
              "compara las clases MOTO / A / B / C contra A B C T-S T-S-R")

    # Contra el conteo del 19-ago tiene que negarse.
    codigo2, texto2 = correr(["--proyecto", str(a.proyecto), "--bd", a.bd])
    comprobar(codigo2 != 0 and "No se comparan dias distintos" in texto2,
              "se niega a comparar contra el conteo de otro dia")

    print(f"\n{fallos} fallos")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
