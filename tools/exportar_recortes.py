"""
Sacar el recorte de cada vehiculo contado, para etiquetarlo y entrenar.

Es el primer paso para separar automovil de camioneta, que es lo unico de la
taxonomia de la empresa que el detector no puede dar: COCO no tiene la clase
"pickup", y su etiqueta `truck` resulto medir el ANGULO y no el vehiculo
(1.2 % de los livianos en la calzada que va hacia la camara contra 7.6 % en
la que se aleja, misma via y mismo dia). Eso no se arregla con un umbral;
hace falta un modelo que conozca la clase, y para eso hacen falta ejemplos
de ESTA camara, en SU angulo y a SU escala.

No usa GPU: lee el video, busca el cuadro exacto del cruce y recorta. Puede
correr mientras la cola cuenta.

    python tools/exportar_recortes.py --proyecto 7 --salida data/recortes \\
        --maximo 2000

Deja los recortes en `<salida>/sin_clasificar/`, con el nombre
`<id>_<clase>_<alto>x<ancho>_<hora>.jpg`. Para etiquetar, se mueven a
`<salida>/auto/` y `<salida>/camioneta/` — que es exactamente la forma que
espera `ImageFolder` de torchvision, asi que el entrenamiento los lee sin
convertir nada.

REPARTE POR HORA A PROPOSITO. Este proyecto ya se quemo una vez con eso: el
modelo de vision dio 36 de 36 a mediodia y 28 de 40 a las 07:00, porque con
el sol bajo los vehiculos blancos salen lavados. Un conjunto de
entrenamiento tomado de una sola franja horaria ensena a clasificar esa
franja. Por omision toma la misma cantidad de cada hora disponible.
"""

import argparse
import csv
import os
import sys
from collections import defaultdict

import cv2

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from src.storage import traffic_db   # noqa: E402

# Margen alrededor de la caja, en fracciones de su tamaño. El detector corta
# justo en el vehiculo y el clasificador necesita algo de contexto: la caja
# de la pickup, las llantas, donde acaba el cofre.
MARGEN = 0.25


def cruces(proyecto, clases, maximo, por_hora):
    conn = traffic_db.get_connection()
    filas = [dict(r) for r in conn.execute(
        f"""SELECT c.id, c.job_id, c.lane_id, c.vehicle_type, c.bbox_height,
                   c.bbox_width, c.bbox_x, c.bbox_y, c.cuadro, c.confidence,
                   c.timestamp, v.stored_path, v.original_name
            FROM crossings c JOIN video_jobs v ON v.id = c.job_id
            WHERE v.project_id = ? AND c.bbox_x IS NOT NULL
              AND c.cuadro IS NOT NULL
              AND c.vehicle_type IN ({','.join('?' * len(clases))})
            ORDER BY c.id""",
        [proyecto] + list(clases))]
    if not filas:
        return []
    if not por_hora:
        return filas[:maximo] if maximo else filas

    # Mismo numero de cada hora: un conjunto de una sola franja horaria
    # ensena a clasificar esa franja y nada mas.
    grupos = defaultdict(list)
    for f in filas:
        grupos[(f["timestamp"] or "  ")[11:13]].append(f)
    cupo = max(1, (maximo or len(filas)) // max(1, len(grupos)))
    salida = []
    for h in sorted(grupos):
        g = grupos[h]
        # Repartidos dentro de la hora, no los primeros: el transito y la luz
        # cambian dentro de una misma hora.
        paso = max(1, len(g) // cupo)
        salida += g[::paso][:cupo]
    return salida


def recortar(img, f):
    x, y = f["bbox_x"], f["bbox_y"]
    w, h = f["bbox_width"], f["bbox_height"]
    if not w or not h:
        return None
    mx, my = int(w * MARGEN), int(h * MARGEN)
    x0, y0 = max(0, x - mx), max(0, y - my)
    x1, y1 = min(img.shape[1], x + w + mx), min(img.shape[0], y + h + my)
    if x1 - x0 < 16 or y1 - y0 < 16:
        return None
    return img[y0:y1, x0:x1]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--proyecto", type=int, required=True)
    ap.add_argument("--salida", required=True)
    ap.add_argument("--clases", default="car,truck",
                    help="clases de COCO a recortar (por omisión las livianas, "
                         "que son las que hay que separar en auto y camioneta)")
    ap.add_argument("--maximo", type=int, default=None)
    ap.add_argument("--sin-repartir", action="store_true",
                    help="NO repartir por hora (no recomendado; ver el encabezado)")
    a = ap.parse_args()

    clases = tuple(x.strip() for x in a.clases.split(",") if x.strip())
    filas = cruces(a.proyecto, clases, a.maximo, not a.sin_repartir)
    if not filas:
        sys.exit("No hay cruces con la caja guardada. Solo los videos contados "
                 "despues del 23-sep-2026 la tienen; los de antes hay que "
                 "volver a contarlos.")

    destino = os.path.join(a.salida, "sin_clasificar")
    os.makedirs(destino, exist_ok=True)

    # Un video a la vez, y sus cuadros en orden: abrir y buscar es lo caro.
    por_video = defaultdict(list)
    for f in filas:
        por_video[f["job_id"]].append(f)

    escritos, sin_cuadro = 0, 0
    manifiesto = os.path.join(a.salida, "recortes.csv")
    with open(manifiesto, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["archivo", "cruce_id", "job", "carril", "clase_coco",
                    "alto", "ancho", "razon", "confianza", "hora"])
        for job_id, grupo in sorted(por_video.items()):
            cap = cv2.VideoCapture(grupo[0]["stored_path"])
            if not cap.isOpened():
                continue
            for f in sorted(grupo, key=lambda x: x["cuadro"]):
                cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(f["cuadro"])))
                ok, img = cap.read()
                if not ok:
                    sin_cuadro += 1
                    continue
                r = recortar(img, f)
                if r is None:
                    continue
                hora = (f["timestamp"] or "")[11:13]
                nombre = (f"{f['id']}_{f['vehicle_type']}_"
                          f"{f['bbox_height']}x{f['bbox_width']}_{hora}h.jpg")
                cv2.imwrite(os.path.join(destino, nombre), r)
                w.writerow([nombre, f["id"], job_id, f["lane_id"],
                            f["vehicle_type"], f["bbox_height"], f["bbox_width"],
                            round(f["bbox_width"] / f["bbox_height"], 2)
                            if f["bbox_height"] else "",
                            round(f["confidence"] or 0, 2), hora])
                escritos += 1
            cap.release()
            print(f"  video {job_id}: {len(grupo)} cruces", flush=True)

    print(f"\n{escritos} recortes en {destino}")
    if sin_cuadro:
        print(f"{sin_cuadro} cruces cuyo cuadro no se pudo leer")
    print(f"manifiesto: {manifiesto}")
    print("\nPara etiquetar, mover los archivos a:")
    print(f"  {os.path.join(a.salida, 'auto')}")
    print(f"  {os.path.join(a.salida, 'camioneta')}")
    por_hora = defaultdict(int)
    for f in filas:
        por_hora[(f["timestamp"] or "  ")[11:13]] += 1
    print("\nreparto por hora: " +
          ", ".join(f"{h}h {n}" for h, n in sorted(por_hora.items())))


if __name__ == "__main__":
    main()
