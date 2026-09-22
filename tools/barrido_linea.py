"""
Imagen de barrido de la línea de conteo: contar a ojo sin usar el detector.

Se extrae la franja de píxeles que cae SOBRE la línea en cada cuadro y se
apilan una tras otra en el tiempo. Cada vehículo que cruza deja una mancha, y
los cruces que registró el sistema se marcan encima. Lo que queda a la vista
es lo único que importa para la razón:

  · mancha sin marca  -> vehículo que el sistema NO contó
  · marca sin mancha  -> conteo de más

Existe porque de un aforo nuevo casi nunca hay conteo manual de campo, y sin
referencia no hay razón que reportar. Esta imagen ES la referencia: sale del
video crudo, no del detector ni del rastreador, así que un fallo de detección
no puede esconderse en ella.

    python tools/barrido_linea.py --video V.mp4 --linea 200,960,980,960 \\
        --job 166 --salida data/barrido.png

Con `--job` se leen de la base los cruces de ese video (todas sus líneas, o
solo la del carril con `--carril`) y se marcan sobre el barrido.
"""

import argparse
import json
import os
import sys

import cv2
import numpy as np

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

# Alto de cada tira de tiempo en la imagen final. Con tiras más cortas caben
# más segundos por renglón pero el vehículo se vuelve un rayón sin forma.
SEGUNDOS_POR_TIRA = 15.0

# Contador de rayas sobre el barrido: un lazo virtual. El fondo es la mediana
# de cada renglón en el tiempo (el pavimento vacío), y lo que se despega de
# él es un vehículo. No usa YOLO ni el rastreador, así que sirve de segunda
# opinión sobre el conteo.
UMBRAL_FONDO = 22        # niveles de gris que hay que despegarse del fondo
MIN_AREA = 140           # píxeles de la mancha (posición x tiempo)
MIN_ALTO = 18            # cuánto ocupa a lo ancho de la línea
MIN_DURACION = 3         # cuadros


def muestrear(frame, a, b, muestras, grosor):
    """Píxeles del cuadro a lo largo del segmento a-b, promediando `grosor`
    píxeles a cada lado en perpendicular (el vehículo no es una línea)."""
    (x1, y1), (x2, y2) = a, b
    t = np.linspace(0, 1, muestras)
    xs = x1 + (x2 - x1) * t
    ys = y1 + (y2 - y1) * t
    largo = max(1e-6, np.hypot(x2 - x1, y2 - y1))
    nx, ny = -(y2 - y1) / largo, (x2 - x1) / largo   # normal unitaria
    acumulado = np.zeros((muestras, 3), np.float32)
    n = 0
    for d in range(-grosor, grosor + 1):
        px = np.clip((xs + nx * d).astype(np.int32), 0, frame.shape[1] - 1)
        py = np.clip((ys + ny * d).astype(np.int32), 0, frame.shape[0] - 1)
        acumulado += frame[py, px].astype(np.float32)
        n += 1
    return (acumulado / n).astype(np.uint8)


def contar_rayas(barrido):
    """Manchas del barrido que parecen vehículos: (fila, columna, alto, ancho).

    El fondo se estima con la mediana temporal de cada renglón, que es el
    pavimento vacío; un vehículo es una región conectada que se despega de
    él. Es el mismo principio de un lazo virtual, sobre la imagen que ya
    tenemos.
    """
    gris = cv2.cvtColor(barrido, cv2.COLOR_BGR2GRAY).astype(np.int16)
    fondo = np.median(gris, axis=1, keepdims=True)
    dif = np.abs(gris - fondo).astype(np.uint8)
    _, mascara = cv2.threshold(dif, UMBRAL_FONDO, 255, cv2.THRESH_BINARY)
    mascara = cv2.morphologyEx(mascara, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mascara = cv2.morphologyEx(mascara, cv2.MORPH_CLOSE, np.ones((9, 5), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(mascara, 8)
    manchas = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area >= MIN_AREA and h >= MIN_ALTO and w >= MIN_DURACION:
            manchas.append((y, x, h, w))
    return sorted(manchas, key=lambda m: m[1]), mascara


def cruces_del_video(job_id, carril=None):
    """{cuadro: [(nombre_del_carril, direccion)]} de lo que contó el sistema."""
    from src.storage import traffic_db
    import datetime as dt
    job = traffic_db.get_video_job(job_id)
    if job is None or not job.get('video_start_time'):
        return {}, None
    inicio = dt.datetime.fromisoformat(job['video_start_time'])
    fps = job.get('fps') or 20.0
    conn = traffic_db.get_connection()
    filas = conn.execute(
        """SELECT c.timestamp, c.direction, c.bbox_height, l.name, l.id
           FROM crossings c JOIN lane_configs l ON l.id = c.lane_id
           WHERE c.job_id = ?""", (job_id,)).fetchall()
    por_cuadro = {}
    for f in filas:
        if carril is not None and f['id'] != carril:
            continue
        t = dt.datetime.fromisoformat(f['timestamp'])
        cuadro = int((t - inicio).total_seconds() * fps)
        por_cuadro.setdefault(cuadro, []).append((f['name'], f['direction'], f['bbox_height']))
    return por_cuadro, job


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--video', required=True)
    ap.add_argument('--linea', required=True, help='x1,y1,x2,y2 de la línea de conteo')
    ap.add_argument('--job', type=int, default=None, help='marcar los cruces de este video')
    ap.add_argument('--carril', type=int, default=None, help='solo los cruces de este carril')
    ap.add_argument('--grosor', type=int, default=6, help='píxeles a cada lado de la línea')
    ap.add_argument('--muestras', type=int, default=260, help='alto de la tira, en píxeles')
    ap.add_argument('--desde', type=float, default=0, help='segundo inicial')
    ap.add_argument('--segundos', type=float, default=0, help='0 = todo el video')
    ap.add_argument('--contar', action='store_true',
                    help='contar las rayas del barrido (lazo virtual, sin YOLO) y dibujarlas')
    ap.add_argument('--salida', required=True)
    a = ap.parse_args()

    x1, y1, x2, y2 = (float(v) for v in a.linea.split(','))
    cap = cv2.VideoCapture(a.video)
    if not cap.isOpened():
        sys.exit(f'No se pudo abrir {a.video}')
    fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
    if a.desde:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(a.desde * fps))
    tope = int(a.segundos * fps) if a.segundos else 10 ** 9

    columnas, n = [], 0
    while n < tope:
        ok, f = cap.read()
        if not ok:
            break
        columnas.append(muestrear(f, (x1, y1), (x2, y2), a.muestras, a.grosor))
        n += 1
    cap.release()
    if not columnas:
        sys.exit('No se leyó ningún cuadro')

    barrido = np.stack(columnas, axis=1)          # (muestras, cuadros, 3)
    manchas = []
    if a.contar:
        manchas, _ = contar_rayas(barrido)
    marcas = {}
    if a.job:
        marcas, _ = cruces_del_video(a.job, a.carril)

    # Se parte en tiras de pocos segundos, una debajo de otra, para que cada
    # vehículo se vea con forma en vez de quedar aplastado.
    por_tira = int(SEGUNDOS_POR_TIRA * fps)
    tiras = []
    desplazamiento = int(a.desde * fps)
    for i in range(0, barrido.shape[1], por_tira):
        tira = barrido[:, i:i + por_tira].copy()
        if tira.shape[1] < por_tira:
            tira = np.pad(tira, ((0, 0), (0, por_tira - tira.shape[1]), (0, 0)))
        # Rayas del lazo virtual: el recuadro de cada vehículo detectado sin
        # YOLO, para poder comparar mancha por mancha.
        for (my, mx, mh, mw) in manchas:
            c = mx - i
            if -mw < c < tira.shape[1]:
                cv2.rectangle(tira, (max(0, c), my), (min(tira.shape[1] - 1, c + mw), my + mh),
                              (255, 255, 255), 1)
        # Marcas del sistema: una línea vertical por cruce, con la hora y el
        # alto de la caja, para poder revisar uno por uno.
        for cuadro, lista in marcas.items():
            c = cuadro - desplazamiento - i
            if 0 <= c < tira.shape[1]:
                for k, (nombre, direccion, alto) in enumerate(lista):
                    col = (60, 220, 60) if direccion == 'in' else (60, 160, 255)
                    cv2.line(tira, (c, 0), (c, tira.shape[0]), col, 1)
                    cv2.putText(tira, f'{alto or 0:.0f}', (c + 2, 14 + 14 * k),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.4, col, 1)
        etiqueta = np.zeros((tira.shape[0], 90, 3), np.uint8)
        t0 = a.desde + i / fps
        cv2.putText(etiqueta, f'{int(t0 // 60):02d}:{t0 % 60:04.1f}', (4, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(etiqueta, f'+{SEGUNDOS_POR_TIRA:.0f}s', (4, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (160, 160, 160), 1)
        tiras.append(np.hstack([etiqueta, tira]))
        tiras.append(np.full((6, tiras[-1].shape[1], 3), 40, np.uint8))

    salida = np.vstack(tiras)
    os.makedirs(os.path.dirname(a.salida) or '.', exist_ok=True)
    cv2.imwrite(a.salida, salida)
    print(json.dumps({'cuadros': n, 'fps': round(fps, 1), 'tiras': len(tiras) // 2,
                      'rayas': len(manchas) if a.contar else None,
                      'cruces_marcados': sum(len(v) for v in marcas.values()),
                      'salida': a.salida, 'tamaño': list(salida.shape[1::-1])},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
