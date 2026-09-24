"""
Revisa la clase de los pesados sobre el recorte de cada uno y la guarda en
`crossings.clase_revisada`, que gana sobre la regla del alto.

Por qué hace falta, medido en el aforo frontal de Cd. Juárez (19-sep-2026):

- **De lado, YOLO llama `truck` a los autobuses de personal.** En la calzada
  que viene hacia la cámara el vehículo se ve de lado y 4 de cada 5 `truck`
  en la banda del autobús eran autobuses: caían en C. B salía 141 en ese
  sentido y 259 en el otro, cuando esos autobuses van y vuelven.
- **El tractocamión (T-S) no tiene clase en COCO**, y es una columna del
  formato de la empresa. La regla de forma lo encuentra con 10 de 10 de
  precisión pero se le escapan ~4 de 10 (pipas y plataformas, de caja baja).

Un modelo de visión sí los distingue sobre el recorte: contra etiquetas
hechas a ojo dio autobús 69/71 y tractocamión 25/26 (ver
configs/nvidia_api.yaml, rol `clasificacion`). No se usa al contar —el
catálogo de la API cambia (el 24-sep, 3 de 7 modelos de visión ya no
existían o no respondían) y el Jetson no debe depender de internet—: es una
REVISIÓN posterior, reanudable, que además deja etiquetas para entrenar un
clasificador local.

Tres pasos:

    # 1. Recortar los pesados (usa la GPU; no con la cola trabajando)
    python tools/recortes_sin_posicion.py --proyecto 7 \\
        --desde "2026-09-19 00:00" --hasta "2026-09-20 00:00" --salida data/pesados
    # 2. Etiquetar (API de NVIDIA; reanudable, guarda etiquetas.json)
    python tools/revisar_pesados.py etiquetar --recortes data/pesados
    # 3. Ver cómo cambia la composición, y escribir con --aplicar
    python tools/revisar_pesados.py aplicar --recortes data/pesados [--aplicar]

**Antes de aplicar, mirar una muestra de las etiquetas** (`hoja`), sobre
todo los T-S y los autobuses que eran `truck`. Una sola condición de luz no
valida nada: el modelo se probó de día (13 y 18 h) y de noche con pocos casos.

Recontar un video borra sus cruces y con ellos la revisión.
"""

import argparse
import json
import os
import re
import sys
from collections import Counter

import cv2
import numpy as np

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

PROMPT = (
    "This is a crop from a traffic camera. Classify the main vehicle in the center "
    "into exactly one category:\n"
    "BUS = passenger bus, school bus, coach or minibus\n"
    "TRUCK = single-unit truck with the cargo body on its own chassis: box truck, "
    "delivery truck, garbage truck, dump truck, tanker truck, flatbed truck\n"
    "TRACTOR = semi-tractor (truck tractor) driving alone, without any trailer\n"
    "SEMI = semi-tractor pulling a semi-trailer (dry van, reefer, container, flatbed, "
    "tank or dump trailer), or a trailer seen from behind\n"
    "CAR = car, SUV, van or pickup truck\n"
    "Reply with only the category word.")

# A la taxonomía de la empresa. El tractor sin caja es clase PROPIA: el
# formato A, B, C, T-S, T-S-R no tiene columna para él y la empresa decidió
# contarlo aparte (24-sep-2026). En el aforo frontal es un 20 % de los
# pesados de un sentido: tractores de patio que mueven cajas entre
# maquiladoras. El contador de ejes lo registra como 3A-SU (camión).
# T-S incluye T-S-R: con esta cámara no se distinguió ningún doble remolque.
A_SCT = {"BUS": "B", "TRUCK": "C", "TRACTOR": "TRACTOR", "SEMI": "T-S", "CAR": "A"}


def _cargar(ruta, omision):
    try:
        with open(ruta, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return omision


def _clave_de_env():
    """NVIDIA_API_KEY del .env del repo si no esta en el entorno (en la PC de
    desarrollo; en el Jetson la pone docker compose)."""
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
    _clave_de_env()
    from src.ai import nvidia_client
    indice = _cargar(os.path.join(a.recortes, "indice.json"), [])
    ruta_etq = os.path.join(a.recortes, "etiquetas.json")
    etiquetas = _cargar(ruta_etq, {})
    pendientes = [e for e in indice
                  if etiquetas.get(e["archivo"], "?") in ("?", "ERROR")]
    print(f"{len(indice)} recortes, {len(pendientes)} por etiquetar")
    for i, e in enumerate(pendientes):
        img = cv2.imread(os.path.join(a.recortes, e["archivo"]))
        if img is None:
            continue
        # Medido así: el lado mayor a 448 px y JPEG al 90.
        h, w = img.shape[:2]
        esc = 448 / max(h, w)
        img = cv2.resize(img, (int(w * esc), int(h * esc)), interpolation=cv2.INTER_CUBIC)
        try:
            # 30 s y no mas: la respuesta normal tarda 3-12 s, y cuando la API
            # se satura deja la conexion colgada; con 75 s el lote bajo a un
            # recorte cada 90 s.
            txt = nvidia_client.vision(PROMPT, img, max_tokens=1024, rol="clasificacion",
                                       timeout_s=30, calidad_jpeg=90)
            enc = re.findall(r"\b(BUS|TRUCK|TRACTOR|SEMI|CAR)\b", txt.upper())
            etiquetas[e["archivo"]] = enc[-1] if enc else "?"
        except Exception as ex:  # la API falla de vez en cuando; se reintenta en otra pasada
            etiquetas[e["archivo"]] = "ERROR"
            print(f"  {e['archivo']}: {type(ex).__name__}", flush=True)
        if i % 25 == 24 or i == len(pendientes) - 1:
            with open(ruta_etq, "w", encoding="utf-8") as fh:
                json.dump(etiquetas, fh, indent=0)
            print(f"  {i + 1}/{len(pendientes)}", flush=True)
    print(Counter(etiquetas.values()))


def aplicar(a):
    from src.storage import traffic_db
    indice = {e["archivo"]: e for e in _cargar(os.path.join(a.recortes, "indice.json"), [])}
    etiquetas = _cargar(os.path.join(a.recortes, "etiquetas.json"), {})
    cambios = {indice[f]["cruce"]: A_SCT[v] for f, v in etiquetas.items()
               if f in indice and v in A_SCT}
    sin = sum(1 for v in etiquetas.values() if v not in A_SCT)
    if not cambios:
        sys.exit("No hay etiquetas que aplicar")
    conn = traffic_db.get_connection()
    ids = list(cambios)
    marcas = ",".join("?" * len(ids))
    existen = {r[0] for r in conn.execute(
        f"SELECT id FROM crossings WHERE id IN ({marcas})", ids)}
    if len(existen) < len(ids):
        print(f"AVISO: {len(ids) - len(existen)} cruces ya no existen (¿se recontó?); se omiten")
    cambios = {i: c for i, c in cambios.items() if i in existen}
    if not cambios:
        sys.exit("Ninguno de esos cruces existe ya en la base")
    ids = list(cambios)

    antes = _suma_por_clase(traffic_db, conn, ids[0])
    # En seco no se escribe nada: la misma lectura del reporte, con las
    # clases revisadas puestas en memoria.
    despues = _suma_por_clase(traffic_db, conn, ids[0], revision=cambios)
    print(f"{len(cambios)} cruces con clase revisada, {sin} sin respuesta del modelo "
          f"(se quedan con la regla)")
    print("Etiquetas:", dict(Counter(cambios.values())))
    if a.aplicar:
        conn.executemany("UPDATE crossings SET clase_revisada=?, clase_revisada_por=? "
                         "WHERE id=?", [(c, a.fuente, i) for i, c in cambios.items()])
        conn.commit()
    print(f"\n{'carril':<28}{'clase':>8}{'antes':>8}{'después':>9}")
    for k in sorted(set(antes) | set(despues)):
        if antes[k] != despues[k] or k[1] in ("B", "C", "T-S", "TRACTOR"):
            print(f"{k[0]:<28}{k[1]:>8}{antes[k]:>8}{despues[k]:>9}")
    print("\nESCRITO en la base." if a.aplicar else
          "\nNo se escribió nada. Revisar la hoja y repetir con --aplicar.")


def _suma_por_clase(traffic_db, conn, un_cruce, revision=None):
    pid = conn.execute("SELECT l.project_id FROM crossings c JOIN lane_configs l "
                       "ON l.id=c.lane_id WHERE c.id=?", (un_cruce,)).fetchone()[0]
    r = traffic_db.get_interval_counts(pid, 60, revision=revision)
    s = Counter()
    for l in r["lanes"]:
        for iv in l["intervals"]:
            for k, v in iv["by_vehicle_type"].items():
                s[(l["lane_name"], k)] += v.get("in", 0) + v.get("out", 0)
    return s


def hoja(a):
    """Hoja de recortes con lo que dijo el modelo, para revisarlo a ojo."""
    indice = {e["archivo"]: e for e in _cargar(os.path.join(a.recortes, "indice.json"), [])}
    etiquetas = _cargar(os.path.join(a.recortes, "etiquetas.json"), {})
    elegidos = [f for f, v in sorted(etiquetas.items())
                if f in indice and (not a.etiqueta or v == a.etiqueta)
                and (not a.clase or indice[f]["clase"] == a.clase)]
    if a.maximo:
        paso = max(1, len(elegidos) // a.maximo)
        elegidos = elegidos[::paso][:a.maximo]
    celdas = []
    for f in elegidos:
        img = cv2.imread(os.path.join(a.recortes, f))
        if img is None:
            continue
        e = 260 / max(img.shape[:2])
        img = cv2.resize(img, (int(img.shape[1] * e), int(img.shape[0] * e)))
        cel = np.full((282, 260, 3), 255, np.uint8)
        cel[22:22 + img.shape[0], :img.shape[1]] = img
        ind = indice[f]
        cv2.putText(cel, f"#{len(celdas)} {etiquetas[f]} {ind['clase'][:5]} {ind['alto_rel']:.2f}",
                    (3, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
        celdas.append(cel)
    if not celdas:
        sys.exit("Nada que mostrar")
    while len(celdas) % 6:
        celdas.append(np.full_like(celdas[0], 255))
    cv2.imwrite(a.salida, np.vstack([np.hstack(celdas[i:i + 6])
                                     for i in range(0, len(celdas), 6)]))
    print(f"{len(elegidos)} recortes en {a.salida}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="paso", required=True)
    e = sub.add_parser("etiquetar")
    e.add_argument("--recortes", required=True)
    p = sub.add_parser("aplicar")
    p.add_argument("--recortes", required=True)
    p.add_argument("--fuente", default="vlm:nemotron-3-nano-omni",
                   help="quién revisó; se guarda con cada cruce")
    p.add_argument("--aplicar", action="store_true")
    h = sub.add_parser("hoja")
    h.add_argument("--recortes", required=True)
    h.add_argument("--etiqueta", default=None, help="solo esta etiqueta (BUS, SEMI...)")
    h.add_argument("--clase", default=None, help="solo esta clase de COCO (truck, bus)")
    h.add_argument("--maximo", type=int, default=36)
    h.add_argument("--salida", required=True)
    a = ap.parse_args()
    {"etiquetar": etiquetar, "aplicar": aplicar, "hoja": hoja}[a.paso](a)


if __name__ == "__main__":
    main()
