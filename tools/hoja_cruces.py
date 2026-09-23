"""
Hoja con el cuadro exacto de CADA cruce contado, para revisarlos uno por uno.

Un total que cuadra no dice si se contó dos veces el mismo vehículo. Esta
hoja sí: cada recorte muestra el instante en que el sistema registró el
cruce, con el rastro, el alto de la caja y la confianza. Dos recortes
seguidos con el mismo vehículo son un doble conteo, y así se encontraron
los tres defectos que lo causaban en la cámara nueva de Cd. Juárez.

    python tools/hoja_cruces.py --job 173 --carril 8 --salida data/hoja.png

Se complementa con `barrido_linea.py`: la hoja enseña lo que SÍ se contó
(conteos de más) y el barrido, lo que pasó por la línea (conteos de menos).
"""

import argparse
import datetime as dt
import os
import sys

import cv2
import numpy as np

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from src.storage import traffic_db   # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--job', type=int, required=True)
    ap.add_argument('--carril', type=int, required=True, help='id del carril (lane_configs)')
    ap.add_argument('--columnas', type=int, default=3)
    ap.add_argument('--clase', default=None,
                    help='solo los cruces de esta clase (car, truck, bus, motorcycle)')
    ap.add_argument('--maximo', type=int, default=None, help='tope de recortes')
    # Para mirar UN grupo de la silueta. `silueta_clases.py` dice dónde se
    # parten los `truck` en dos poblaciones (la troca y el camión de
    # verdad); esto recorta sólo las de un lado del corte, que es la única
    # forma de comprobar que el corte separa lo que se cree.
    ap.add_argument('--alto-min', type=float, default=None,
                    help='solo cruces con la caja de al menos este alto')
    ap.add_argument('--alto-max', type=float, default=None,
                    help='solo cruces con la caja de a lo más este alto')
    ap.add_argument('--alto-banda', type=int, default=400,
                    help='píxeles arriba y abajo de la línea que se recortan')
    # Con la camara de 2560x1440 el recorte de un carril entero mide mas de
    # 1000 px y al encogerlo a 390 no se distingue una moto de un peaton:
    # asi se dio por buena una hoja donde no se veia nada.
    ap.add_argument('--celda', type=int, default=390,
                    help='ancho en px de cada recorte de la hoja')
    ap.add_argument('--salida', required=True)
    a = ap.parse_args()

    job = traffic_db.get_video_job(a.job)
    if job is None or not job.get('video_start_time'):
        sys.exit('El video no existe o no tiene hora de inicio')
    carriles = {c['id']: c for c in traffic_db.list_lanes(project_id=job['project_id'])}
    if a.carril not in carriles:
        sys.exit(f'El carril {a.carril} no es de este proyecto')
    puntos = carriles[a.carril]['points']
    y_linea = (puntos[0][1] + puntos[1][1]) / 2
    x0 = max(0, min(p[0] for p in puntos) - 80)
    x1 = max(p[0] for p in puntos) + 80

    inicio = dt.datetime.fromisoformat(job['video_start_time'])
    fps = job.get('fps') or 20.0
    conn = traffic_db.get_connection()
    consulta = ("""SELECT timestamp, track_id, direction, vehicle_type,
                          bbox_height, bbox_width, bbox_x, bbox_y, cuadro,
                          confidence
                   FROM crossings WHERE job_id = ? AND lane_id = ?""")
    parametros = [a.job, a.carril]
    if a.clase:
        consulta += ' AND vehicle_type = ?'
        parametros.append(a.clase)
    if a.alto_min is not None:
        consulta += ' AND bbox_height >= ?'
        parametros.append(a.alto_min)
    if a.alto_max is not None:
        consulta += ' AND bbox_height <= ?'
        parametros.append(a.alto_max)
    filas = conn.execute(consulta + ' ORDER BY timestamp', parametros).fetchall()
    if a.maximo:
        filas = filas[:a.maximo]
    if not filas:
        sys.exit('Ese video no registró cruces en ese carril')

    cap = cv2.VideoCapture(job['stored_path'])
    if not cap.isOpened():
        sys.exit(f"No se pudo abrir {job['stored_path']}")
    # El alto de la celda sigue la proporcion del recorte, para no deformar
    # al vehiculo: una caja estirada cambia justo la razon ancho/alto que
    # sirve para distinguir una moto de un automovil.
    ancho_r = a.celda
    alto_r = max(40, int(ancho_r * a.alto_banda / max(1.0, min(x1, 10 ** 6) - x0)))
    recortes = []
    for f in filas:
        # El numero de cuadro es exacto; el timestamp solo llega al segundo,
        # y a 20 cuadros por segundo eso deja 20 cuadros de margen. Con la
        # camara de 2560x1440 el vehiculo recorre cientos de pixeles en ese
        # tiempo y el recorte salia vacio. Se usa el cuadro cuando esta.
        if f['cuadro'] is not None:
            n = int(f['cuadro'])
        else:
            n = int((dt.datetime.fromisoformat(f['timestamp']) - inicio).total_seconds() * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, n))
        ok, img = cap.read()
        if not ok:
            continue
        y0 = max(0, int(y_linea - a.alto_banda / 2))
        y1 = min(img.shape[0], int(y_linea + a.alto_banda / 2))
        r = cv2.resize(img[y0:y1, int(x0):int(min(x1, img.shape[1]))], (ancho_r, alto_r))
        cv2.putText(r, f"{n / fps:.1f}s {f['vehicle_type']} "
                       f"{f['bbox_height'] or 0}x{f['bbox_width'] or 0}px "
                       f"{f['confidence'] or 0:.2f}", (5, 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
        y_rel = int((y_linea - y0) / (y1 - y0) * alto_r)
        cv2.line(r, (0, y_rel), (ancho_r, y_rel), (0, 0, 255), 1)
        recortes.append(r)
    cap.release()

    while len(recortes) % a.columnas:
        recortes.append(np.zeros_like(recortes[0]))
    hoja = np.vstack([np.hstack(recortes[i:i + a.columnas])
                      for i in range(0, len(recortes), a.columnas)])
    os.makedirs(os.path.dirname(a.salida) or '.', exist_ok=True)
    cv2.imwrite(a.salida, hoja)
    print(f'{len(filas)} cruces -> {a.salida}')


if __name__ == '__main__':
    main()
