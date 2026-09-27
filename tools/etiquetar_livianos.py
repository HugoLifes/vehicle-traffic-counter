#!/usr/bin/env python3
"""
Etiqueta recortes de vehículos livianos en automóvil, camioneta o pickup con
un modelo de visión, para entrenar el clasificador propio.

Es el mismo camino que ya funcionó con los pesados (`revisar_pesados.py`):
un modelo de visión de la API de NVIDIA pone la etiqueta, se revisa una
muestra a ojo, y con las etiquetas se entrena un modelo chico que corre en
el equipo sin internet (`entrenar_clasificador.py`). El modelo de visión no
se usa al contar: el catálogo de la API cambia sin aviso.

Contra etiquetas hechas a ojo, en livianos dio 60 de 60 a las 18 h y 72 de
73 a las 13 h (auto, camioneta, pickup, moto, pesado). COCO no sirve para
esto: su `car` ya trae SUV y minivans, y su `truck` mide el ángulo (1.2 % de
los livianos que vienen hacia la cámara contra 7.6 % de los que se alejan).

    # 1. recortes de día, repartidos en varias horas (usa la GPU)
    python tools/recortes_sin_posicion.py --proyecto 7 --clases car truck \\
        --alto-rel-min 0 --desde "2026-09-19 12:10" --hasta "2026-09-19 12:25" \\
        --salida data/nuevos/livianos/v_1210
    # 2. etiquetar (reanudable; guarda etiquetas.json junto a los recortes)
    python tools/etiquetar_livianos.py etiquetar --recortes data/nuevos/livianos/v_1210
    # 3. armar el conjunto por clase y hora para entrenar
    python tools/etiquetar_livianos.py conjunto --recortes data/nuevos/livianos/v_* \\
        --salida data/nuevos/clasif_livianos
    # 4. hoja para revisar a ojo una muestra de cada etiqueta
    python tools/etiquetar_livianos.py hoja --recortes data/nuevos/livianos/v_1210 \\
        --etiqueta PICKUP --salida data/nuevos/livianos/hoja_pickup.jpg
"""
import argparse
import glob
import json
import os
import random
import re
import shutil
import sys
from collections import Counter

import cv2
import numpy as np

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

PROMPT = (
    "This is a crop from a traffic camera. Classify the main vehicle in the center "
    "into exactly one category:\n"
    "AUTO = passenger car: sedan, hatchback, coupe, compact or station wagon\n"
    "CAMIONETA = SUV, crossover, minivan or passenger van\n"
    "PICKUP = pickup truck with an open cargo bed (with or without a cover)\n"
    "MOTO = motorcycle or scooter\n"
    "PESADO = bus, truck, tractor or anything bigger than a van\n"
    "Reply with only the category word.")
CLASES = ("AUTO", "CAMIONETA", "PICKUP", "MOTO", "PESADO")


def _cargar(ruta, omision):
    try:
        with open(ruta, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return omision


def _clave_de_env():
    if os.environ.get("NVIDIA_API_KEY"):
        return
    try:
        with open(os.path.join(RAIZ, ".env"), encoding="utf-8") as fh:
            for linea in fh:
                if linea.startswith("NVIDIA_API_KEY="):
                    os.environ["NVIDIA_API_KEY"] = linea.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass


def etiquetar(a):
    """Con --seguir vuelve a leer el indice mientras los recortes siguen
    llegando (recortes_sin_posicion.py lo guarda despues de cada video), y
    termina cuando lleva 15 min sin recortes nuevos."""
    import time
    quieto = 0
    while True:
        hechos = _etiquetar_una_pasada(a)
        if not a.seguir:
            return
        quieto = 0 if hechos else quieto + 1
        if quieto >= 8:
            return
        time.sleep(120)


def _etiquetar_una_pasada(a):
    _clave_de_env()
    from src.ai import nvidia_client
    total = 0
    for carpeta in a.recortes:
        indice = _cargar(os.path.join(carpeta, "indice.json"), [])
        # Una muestra fija por numero de cruce: repartida en todas las horas
        # y la misma en cada pasada.
        indice = [e for e in indice if e["cruce"] % a.cada == 0]
        ruta_etq = os.path.join(carpeta, "etiquetas.json")
        etiquetas = _cargar(ruta_etq, {})
        pendientes = [e for e in indice if etiquetas.get(e["archivo"], "?") in ("?", "ERROR")]
        total += len(pendientes)
        print(f"{carpeta}: {len(indice)} recortes, {len(pendientes)} por etiquetar", flush=True)
        for i, e in enumerate(pendientes):
            img = cv2.imread(os.path.join(carpeta, e["archivo"]))
            if img is None:
                continue
            h, w = img.shape[:2]
            esc = 448 / max(h, w)
            img = cv2.resize(img, (int(w * esc), int(h * esc)), interpolation=cv2.INTER_CUBIC)
            try:
                txt = nvidia_client.vision(PROMPT, img, max_tokens=1024, rol="clasificacion",
                                           timeout_s=30, calidad_jpeg=90)
                enc = re.findall(r"\b(" + "|".join(CLASES) + r")\b", txt.upper())
                etiquetas[e["archivo"]] = enc[-1] if enc else "?"
            except Exception as ex:  # la API falla a ratos; otra pasada lo reintenta
                etiquetas[e["archivo"]] = "ERROR"
                print(f"  {e['archivo']}: {type(ex).__name__}", flush=True)
            if i % 25 == 24 or i == len(pendientes) - 1:
                with open(ruta_etq, "w", encoding="utf-8") as fh:
                    json.dump(etiquetas, fh, indent=0)
                print(f"  {i + 1}/{len(pendientes)}  {dict(Counter(etiquetas.values()))}", flush=True)
    return total


def conjunto(a):
    """Una carpeta por clase, con la hora en el nombre para que
    entrenar_clasificador.py separe por hora."""
    shutil.rmtree(a.salida, ignore_errors=True)
    cuenta = Counter()
    for carpeta in a.recortes:
        indice = {e["archivo"]: e for e in _cargar(os.path.join(carpeta, "indice.json"), [])}
        for archivo, etq in _cargar(os.path.join(carpeta, "etiquetas.json"), {}).items():
            if etq not in ("AUTO", "CAMIONETA", "PICKUP") or archivo not in indice:
                continue
            e = indice[archivo]
            destino = os.path.join(a.salida, etq)
            os.makedirs(destino, exist_ok=True)
            shutil.copy(os.path.join(carpeta, archivo),
                        os.path.join(destino, f"{e['cruce']}_c{e['carril']}_{e['hora'][11:13]}h.jpg"))
            cuenta[etq] += 1
    print(dict(cuenta))


def aplicar(a):
    """Subtipo de cada liviano ya contado, con el modelo propio, sobre sus
    recortes. Escribe crossings.subtipo_modelo y prob_subtipo; no toca la
    clase ni el conteo. Al leer, el subtipo solo cuenta si el cruce quedo en
    A (ver get_interval_counts)."""
    from src.engine.clasificador_pesados import SUBTIPOS_A, ClasificadorPesados
    from src.storage import traffic_db
    modelo = ClasificadorPesados(a.modelo)
    filas = []
    for carpeta in a.recortes:
        for e in _cargar(os.path.join(carpeta, "indice.json"), []):
            img = cv2.imread(os.path.join(carpeta, e["archivo"]))
            if img is None:
                continue
            clase, p = modelo.clasificar_recorte(img)
            if clase in SUBTIPOS_A:
                filas.append((clase, round(p, 4), e["cruce"]))
    conn = traffic_db.get_connection()
    conn.executemany("UPDATE crossings SET subtipo_modelo = ?, prob_subtipo = ? WHERE id = ?",
                     filas)
    conn.commit()
    print(f"{len(filas)} cruces con subtipo: {dict(Counter(f[0] for f in filas))}")


def hoja(a):
    celdas = []
    for carpeta in a.recortes:
        for archivo, etq in _cargar(os.path.join(carpeta, "etiquetas.json"), {}).items():
            if etq == a.etiqueta:
                celdas.append(os.path.join(carpeta, archivo))
    random.seed(0)
    random.shuffle(celdas)
    imgs = []
    for ruta in celdas[:a.maximo]:
        img = cv2.imread(ruta)
        if img is None:
            continue
        h, w = img.shape[:2]
        esc = 200 / max(h, w)
        img = cv2.resize(img, (int(w * esc), int(h * esc)))
        cel = np.full((224, 224, 3), 255, np.uint8)
        cel[(224 - img.shape[0]) // 2:(224 - img.shape[0]) // 2 + img.shape[0],
            (224 - img.shape[1]) // 2:(224 - img.shape[1]) // 2 + img.shape[1]] = img
        cv2.putText(cel, os.path.basename(ruta)[:18], (3, 12), cv2.FONT_HERSHEY_SIMPLEX,
                    0.35, (0, 0, 0), 1)
        imgs.append(cel)
    if not imgs:
        sys.exit("No hay recortes con esa etiqueta")
    while len(imgs) % 8:
        imgs.append(np.full_like(imgs[0], 255))
    cv2.imwrite(a.salida, np.vstack([np.hstack(imgs[i:i + 8]) for i in range(0, len(imgs), 8)]),
                [cv2.IMWRITE_JPEG_QUALITY, 85])
    print(f"{len(celdas)} con {a.etiqueta}; hoja con {min(len(celdas), a.maximo)} -> {a.salida}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="accion", required=True)
    e = sub.add_parser("etiquetar")
    e.add_argument("--recortes", nargs="+", required=True)
    e.add_argument("--cada", type=int, default=1,
                   help="etiquetar solo los cruces cuyo numero es multiplo de esto")
    e.add_argument("--seguir", action="store_true",
                   help="seguir leyendo el indice mientras llegan recortes")
    c = sub.add_parser("conjunto")
    c.add_argument("--recortes", nargs="+", required=True)
    c.add_argument("--salida", required=True)
    ap_ = sub.add_parser("aplicar")
    ap_.add_argument("--recortes", nargs="+", required=True)
    ap_.add_argument("--modelo", required=True)
    h = sub.add_parser("hoja")
    h.add_argument("--recortes", nargs="+", required=True)
    h.add_argument("--etiqueta", required=True)
    h.add_argument("--maximo", type=int, default=48)
    h.add_argument("--salida", required=True)
    a = ap.parse_args()
    a.recortes = [r for patron in a.recortes for r in sorted(glob.glob(patron))] or a.recortes
    {"etiquetar": etiquetar, "conjunto": conjunto, "aplicar": aplicar,
     "hoja": hoja}[a.accion](a)


if __name__ == "__main__":
    main()
