#!/usr/bin/env python3
"""
Prueba de aceptación del sistema: un comando que dice si todo funciona.

Es lo que se corre al entregar, después de cada actualización y cuando algo
"se ve raro". Junta lo que antes vivía en una docena de herramientas y en la
cabeza de quien las escribió:

1. **Regresiones sin GPU.** Cada una reproduce un defecto que ya costó conteos
   (clase congelada, rastros partidos, dobles conteos, filas en blanco leídas
   como cero...). Si una falla, un cambio reintrodujo ese defecto.
2. **Exactitud contra un conteo de campo**, si se le da uno: la razón total y
   el GEH por cuarto de hora contra criterios explícitos, no a ojo. Con
   `--od-proyecto`, también el aforo direccional contra su conteo manual.
3. **Salud del equipo**: base íntegra, respaldo reciente, disco, modelo, GPU,
   API y videos con error en la cola.

    # en el Jetson, dentro del contenedor
    python3 tools/prueba_aceptacion.py
    python3 tools/prueba_aceptacion.py --proyecto 7 \\
        --referencias data/nuevos/aforo_frontal_manual \\
        --od-proyecto 5 --od-manual "referencias/aforo_direccional/AFORO ENTRADA Y SALIDA ALTOZANO.xlsx" \\
        --od-asignacion "Arco=2,Fondo izq=1,Izquierda=3,Abajo=3,Derecha=x"

Sale con código 0 solo si todo lo obligatorio pasa. Los avisos no reprueban:
dicen algo que conviene atender (por ejemplo, un respaldo de hace tres días).
"""
import argparse
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

REGRESIONES = [
    ("Clasificación vehicular", "probar_clasificacion.py"),
    ("Rastreador y contador", "probar_rastreador.py"),
    ("Conteo por trayectoria", "probar_conteo_trayectoria.py"),
    ("Diagnóstico de encuadre", "probar_diagnostico_encuadre.py"),
    ("Perfil de detección por proyecto", "probar_perfil_deteccion.py"),
    ("Velocidad por tramo", "probar_velocidad.py"),
]

resultados = []          # (grupo, nombre, estado, detalle)


def anotar(grupo, nombre, estado, detalle=""):
    resultados.append((grupo, nombre, estado, detalle))
    marca = {"PASA": "PASA ", "FALLA": "FALLA", "AVISO": "AVISO"}[estado]
    print(f"  [{marca}] {nombre}" + (f" — {detalle}" if detalle else ""), flush=True)


def correr(args, timeout=900):
    r = subprocess.run([sys.executable] + args, capture_output=True, text=True,
                       timeout=timeout, cwd=RAIZ)
    return r.returncode, r.stdout + r.stderr


def regresiones():
    print("\n1. Regresiones (sin GPU)")
    for nombre, archivo in REGRESIONES:
        codigo, salida = correr([str(RAIZ / "tools" / archivo)])
        # El resumen ("N casos, 0 fallos") es la ultima linea con "fallo";
        # los avisos del registro llegan por otra via y no cuentan.
        ultima = next((l.strip() for l in reversed(salida.splitlines()) if "fallo" in l),
                      next((l.strip() for l in reversed(salida.splitlines()) if l.strip()), ""))
        anotar("regresiones", nombre, "PASA" if codigo == 0 else "FALLA", ultima)


def exactitud(proyecto, referencias, razon_min, razon_max, geh_min):
    print(f"\n2. Exactitud contra el conteo de campo (proyecto {proyecto})")
    codigo, salida = correr([str(RAIZ / "tools" / "probar_comparacion.py"),
                             "--proyecto", str(proyecto),
                             "--salida", str(RAIZ / "data" / "prueba_comparacion")])
    fallos = re.search(r"(\d+) fallos", salida)
    anotar("exactitud", "Herramienta de comparación (conteos fabricados con errores conocidos)",
           "PASA" if codigo == 0 else "FALLA", f"{fallos.group(0) if fallos else 'sin resumen'}")
    if not referencias:
        anotar("exactitud", "Comparación contra conteo de campo", "AVISO",
               "no se dio --referencias; no se midió la exactitud")
        return
    codigo, salida = correr([str(RAIZ / "tools" / "comparar_aforo_real.py"),
                             "--proyecto", str(proyecto), "--referencias", referencias])
    if codigo != 0:
        anotar("exactitud", "Comparación contra conteo de campo", "FALLA",
               salida.strip().splitlines()[-1] if salida.strip() else "sin salida")
        return
    total = re.search(r"AMBOS SENTIDOS\s+(\d+)\s+(\d+)\s+([\d.]+)x", salida)
    if total:
        razon = float(total.group(3))
        ok = razon_min <= razon <= razon_max
        anotar("exactitud", "Razón total contra el conteo de campo", "PASA" if ok else "FALLA",
               f"{razon:.2f}x ({total.group(1)} contra {total.group(2)}); se pide "
               f"{razon_min:.2f}–{razon_max:.2f}")
    for zona, ok_q, n_q in re.findall(r"^(.+?) <-> \S+: GEH < 5 en (\d+) de (\d+) cuartos",
                                      salida, re.M):
        frac = int(ok_q) / int(n_q)
        anotar("exactitud", f"GEH por cuarto de hora, {zona.strip()}",
               "PASA" if frac >= geh_min else "FALLA",
               f"{ok_q} de {n_q} ({100 * frac:.0f} %); se pide {100 * geh_min:.0f} %")


def exactitud_direccional(proyecto, manual, asignacion, razon_min, razon_max):
    """El aforo direccional contra su conteo manual, por el mismo camino que
    el informe (comparar_od_real.py lee get_matriz_od). Se piden la razón del
    total y que el movimiento principal cuadre (GEH < 5): con un solo cuarto
    de hora comparable, pedir el 85 % de los movimientos chicos sería medir
    el ruido de 9 o 10 vehículos."""
    print(f"\n2b. Aforo direccional contra el conteo manual (proyecto {proyecto})")
    args = [str(RAIZ / "tools" / "comparar_od_real.py"), "--proyecto", str(proyecto),
            "--manual", manual]
    if asignacion:
        args += ["--asignacion", asignacion]
    codigo, salida = correr(args)
    total = re.search(r"^TOTAL\s+(\d+)\s+(\d+)", salida, re.M)
    if codigo != 0 or not total:
        anotar("exactitud", "Direccional contra el conteo manual", "FALLA",
               salida.strip().splitlines()[-1] if salida.strip() else "sin salida")
        return
    n, m = int(total.group(1)), int(total.group(2))
    razon = n / m if m else 0.0
    anotar("exactitud", "Direccional, total de movimientos", "PASA" if razon_min <= razon <= razon_max
           else "FALLA", f"{razon:.2f}x ({n} contra {m}); se pide {razon_min:.2f}–{razon_max:.2f}")
    movs = [(mov, int(a), int(b), float(g)) for mov, a, b, g in
            re.findall(r"^(\w+_\w+)\s+(\d+)\s+(\d+)\s+\S+\s+([\d.]+)", salida, re.M)]
    if movs:
        mov, a, b, g = max(movs, key=lambda x: x[2])
        anotar("exactitud", f"Direccional, movimiento principal ({mov})",
               "PASA" if g < 5 else "FALLA", f"{a} contra {b}, GEH {g:.1f}; se pide menor que 5")


def salud(max_horas_respaldo, min_disco):
    print("\n3. Salud del equipo")
    from src.storage import respaldos, traffic_db
    bd = Path(traffic_db.DB_PATH)
    try:
        con = sqlite3.connect(f"file:{bd}?mode=ro", uri=True, timeout=30)
        estado = con.execute("PRAGMA quick_check").fetchone()[0]
        errores = con.execute("select count(*) from video_jobs where status='error'").fetchone()[0]
        cola = con.execute("select count(*) from video_jobs where status in ('queued','processing')"
                           ).fetchone()[0]
        con.close()
        anotar("salud", "Base de datos íntegra", "PASA" if estado == "ok" else "FALLA", estado)
        anotar("salud", "Videos con error en la cola", "PASA" if errores == 0 else "AVISO",
               f"{errores} con error, {cola} esperando")
    except Exception as e:
        anotar("salud", "Base de datos íntegra", "FALLA", str(e))

    existentes = respaldos.listar()
    if not existentes:
        anotar("salud", "Respaldo de la base", "AVISO",
               "todavía no hay respaldos (se hacen solos al arrancar la plataforma)")
    else:
        horas = (time.time() - existentes[-1].stat().st_mtime) / 3600
        anotar("salud", "Respaldo de la base", "PASA" if horas <= max_horas_respaldo else "AVISO",
               f"el último tiene {horas:.0f} h; hay {len(existentes)}")

    uso = shutil.disk_usage(bd.parent)
    libre = uso.free / uso.total
    anotar("salud", "Espacio en disco", "PASA" if libre >= min_disco else "FALLA",
           f"{100 * libre:.0f} % libre ({uso.free / 1e9:.0f} GB)")

    try:
        import yaml
        cfg = yaml.safe_load(open(RAIZ / "configs" / "platform.yaml", encoding="utf-8"))
        modelo = RAIZ / cfg.get("model_path", "")
        anotar("salud", "Modelo del detector", "PASA" if modelo.exists() else "FALLA",
               str(modelo.relative_to(RAIZ)))
    except Exception as e:
        anotar("salud", "Modelo del detector", "FALLA", str(e))

    # Un clasificador del perfil que falta no detiene el conteo (el procesador
    # cae a la regla del alto), pero solo lo dice en el registro del
    # contenedor: pasa al copiar un proyecto a otro equipo sin `models/`.
    try:
        import json as _json
        faltan = []
        con = sqlite3.connect(f"file:{bd}?mode=ro", uri=True, timeout=30)
        for pid, perfil in con.execute(
                "select id, perfil_deteccion from projects where perfil_deteccion is not null"):
            try:
                datos = _json.loads(perfil) if perfil else {}
            except ValueError:
                faltan.append(f"proyecto {pid}: perfil ilegible")
                continue
            for clave in ("modelo", "clasificador_pesados", "clasificador_livianos"):
                ruta = datos.get(clave)
                if ruta and not (RAIZ / ruta).exists():
                    faltan.append(f"proyecto {pid}: {ruta}")
        con.close()
        anotar("salud", "Modelos de los perfiles", "AVISO" if faltan else "PASA",
               "; ".join(faltan) if faltan else "todos en el equipo")
    except Exception as e:
        anotar("salud", "Modelos de los perfiles", "AVISO", str(e))

    try:
        import torch
        gpu = torch.cuda.is_available()
        anotar("salud", "GPU disponible", "PASA" if gpu else "AVISO",
               torch.cuda.get_device_name(0) if gpu else "sin CUDA: contaría en CPU, muy lento")
    except Exception as e:
        anotar("salud", "GPU disponible", "AVISO", f"sin torch ({e})")

    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:8080/api/status", timeout=5)
        anotar("salud", "La plataforma responde", "PASA", "http://localhost:8080")
    except Exception as e:
        anotar("salud", "La plataforma responde", "AVISO", f"no respondió ({e.__class__.__name__})")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--proyecto", type=int, help="proyecto a medir contra un conteo de campo")
    ap.add_argument("--referencias", help="carpeta con el conteo de campo de ese proyecto")
    ap.add_argument("--razon-min", type=float, default=0.95)
    ap.add_argument("--razon-max", type=float, default=1.05)
    ap.add_argument("--geh-min", type=float, default=0.85,
                    help="fracción de cuartos de hora con GEH < 5 (criterio usual: 85 %%)")
    ap.add_argument("--od-proyecto", type=int, help="proyecto direccional a medir")
    ap.add_argument("--od-manual", help="Excel del conteo manual direccional")
    ap.add_argument("--od-asignacion", help="acceso=número fijado por geometría")
    ap.add_argument("--od-razon-min", type=float, default=0.90)
    ap.add_argument("--od-razon-max", type=float, default=1.10)
    ap.add_argument("--respaldo-horas", type=float, default=48)
    ap.add_argument("--disco-min", type=float, default=0.15)
    ap.add_argument("--sin-salud", action="store_true",
                    help="omitir la salud del equipo (p. ej. en la PC de desarrollo)")
    a = ap.parse_args()

    print("Prueba de aceptación del aforo vehicular")
    regresiones()
    if a.proyecto:
        exactitud(a.proyecto, a.referencias, a.razon_min, a.razon_max, a.geh_min)
    if a.od_proyecto and a.od_manual:
        exactitud_direccional(a.od_proyecto, a.od_manual, a.od_asignacion,
                              a.od_razon_min, a.od_razon_max)
    if not a.sin_salud:
        salud(a.respaldo_horas, a.disco_min)

    fallas = [r for r in resultados if r[2] == "FALLA"]
    avisos = [r for r in resultados if r[2] == "AVISO"]
    print(f"\n{len(resultados) - len(fallas) - len(avisos)} pasan, {len(avisos)} avisos, "
          f"{len(fallas)} fallas")
    print("RESULTADO: " + ("ACEPTADO" if not fallas else "NO ACEPTADO"))
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())
