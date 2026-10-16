"""
Mide `dobles_contencion` (pedazo y vehículo entero contados dos veces en una
línea) SIN GPU y SIN escribir en la base, con las detecciones ya guardadas.

Recuenta las líneas de un proyecto como producción (rastreador propio, umbral
por sentido, zonas, quitar_anidadas, pedazos de pesado), con y sin la opción,
y lo pone junto a lo guardado en la base para la misma ventana. La columna
"sin" tiene que reproducir "guardado"; si no, la emulación no es fiel y la
comparación no vale (las detecciones guardadas pueden no llevar la franja).

Además escribe la lista de cruces quitados, para mirarlos a ojo en sus
recortes antes de creer el número:

    python3 tools/medir_dobles_contencion.py --proyecto 27 \
        --detecciones data/fr/det_08_*.json --desde 06:45 --hasta 07:45

Las detecciones salen de `extraer_trayectorias.py --guardar-detecciones`:
{"video", "fps", "ancho", "alto", "conf_minima", "d": [[[x1,y1,x2,y2,conf,clase]...] por cuadro]}.
"""

import argparse
import copy
import csv
import glob
import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

RAIZ = Path.cwd() if (Path.cwd() / 'src').is_dir() else Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src.engine import perfil_deteccion                           # noqa: E402
from src.engine.lanes import build_lane_counters                  # noqa: E402
from src.engine.zones import filter_detections, load_zones, zone_for_bbox  # noqa: E402
from src.storage import traffic_db                                # noqa: E402
from src.tracker import VehicleTracker                            # noqa: E402

BD = RAIZ / 'data' / 'traffic.db'
CLASES = {2: 'car', 3: 'motorcycle', 5: 'bus', 7: 'truck'}
SENTIDO = {'in': 'entra', 'out': 'sale'}


def _bd():
    return sqlite3.connect(f'file:{BD}?mode=ro', uri=True)


def _job_de(con, proyecto, video):
    nombre = os.path.basename(video)
    for jid, ruta, original, inicio in con.execute(
            "select id, stored_path, original_name, video_start_time from video_jobs "
            "where project_id = ?", (proyecto,)):
        if os.path.basename(ruta or '') == nombre or (original or '').endswith(nombre):
            return {'id': jid, 'stored_path': ruta, 'original_name': original,
                    'video_start_time': inicio, 'project_id': proyecto}
    return None


def contar(det, job, perfil, zonas, dobles, cfg_trk, desde, hasta):
    """{(numero, sentido): n} en la ventana, y la lista de quitados."""
    alto, ancho, fps = det['alto'], det['ancho'], det['fps'] or 15.0
    contadores, meta = build_lane_counters(job.get('source_label') or 'sin-nombre',
                                           alto, ancho, project_id=job['project_id'])
    for c in contadores.values():
        c.dobles_contencion = dobles
    numero = {lid: traffic_db.numero_de_acceso(m.get('name') or '') for lid, m in meta.items()}

    def nuevo():
        return VehicleTracker(max_age=cfg_trk.get('max_age', 30),
                              min_hits=cfg_trk.get('min_hits', 3),
                              iou_threshold=cfg_trk.get('iou_threshold', 0.3), config=cfg_trk)

    # Igual que video_job_processor: un rastreador por umbral de sentido y
    # una copia del contador de la línea para ese sentido.
    por_sentido = {}
    for lid in meta:
        reglas = perfil.get('umbral_linea_sentido', {}).get(str(numero[lid]))
        if reglas:
            por_sentido[lid] = {('in' if d == 'entra' else 'out'): u for d, u in reglas.items()}
    rastreadores_u = {u: nuevo() for dirs in por_sentido.values() for u in dirs.values()}
    contadores_u = {(lid, d): (u, copy.deepcopy(contadores[lid]))
                    for lid, dirs in por_sentido.items() for d, u in dirs.items()}
    tracker = nuevo()
    umbral_linea = perfil.get('umbral_linea', 0.25)
    pedazos = (perfil_deteccion.PedazosDePesado()
               if perfil.get('quitar_pedazos_de_pesado') else None)
    anidadas = perfil.get('quitar_anidadas')

    inicio = datetime.fromisoformat(job['video_start_time'])
    cuenta = defaultdict(int)
    quitados = []
    vistos_antes = {id(c): 0 for c in list(contadores.values()) + [c for _, c in contadores_u.values()]}

    for n, cuadro in enumerate(det['d']):
        t = inicio + timedelta(seconds=n / fps)
        en_ventana = desde <= t.strftime('%H:%M') < hasta
        crudas = [{'bbox': list(d[:4]), 'confidence': d[4], 'class_id': int(d[5]),
                   'class_name': CLASES.get(int(d[5]), 'car')} for d in cuadro]

        tracks_u = {}
        for u, r in rastreadores_u.items():
            du = filter_detections(zonas, [d for d in crudas if d['confidence'] >= u])
            if anidadas:
                du = perfil_deteccion.quitar_anidadas(du, anidadas)
            tracks_u[u] = r.update(du)

        dets = [d for d in crudas if d['confidence'] >= umbral_linea]
        dets = perfil_deteccion.filtrar_por_clase(dets, perfil, umbral_linea)
        dets = filter_detections(zonas, dets)
        if anidadas:
            dets = perfil_deteccion.quitar_anidadas(dets, anidadas)
        tracks = tracker.update(dets)
        if pedazos is not None:
            pedazos.observar(tracks)

        for lid, contador in contadores.items():
            zona = meta[lid].get('zone_id')
            vistos = [x for x in tracks if zone_for_bbox(zonas, x['bbox']) == zona] \
                if zona and zonas else tracks
            r = contador.update(vistos)
            fuentes = [r['in'] + r['out']]
            usados = [contador]
            if lid in por_sentido:
                fuentes = [[c for c in fuentes[0] if c['direction'] not in por_sentido[lid]]]
                for d in por_sentido[lid]:
                    u, cu = contadores_u[(lid, d)]
                    vu = tracks_u[u]
                    if zona and zonas:
                        vu = [x for x in vu if zone_for_bbox(zonas, x['bbox']) == zona]
                    fuentes.append(cu.update(vu)[d])
                    usados.append(cu)
            for lista in fuentes:
                for c in lista:
                    if pedazos is not None and pedazos.es_pedazo(c['track_id']):
                        continue
                    if en_ventana:
                        cuenta[(numero[lid], SENTIDO.get(c['direction'], c['direction']))] += 1
            # Los que el arreglo quitó en este cuadro.
            for cu in usados:
                nuevos = cu.dobles_quitados[vistos_antes[id(cu)]:]
                vistos_antes[id(cu)] = len(cu.dobles_quitados)
                for rastro, otro in nuevos:
                    if en_ventana:
                        quitados.append({'video': job['original_name'], 'cuadro': n,
                                         'hora': t.strftime('%H:%M:%S'), 'linea': numero[lid],
                                         'rastro': rastro, 'pedazo_de': otro})
    return cuenta, quitados


def guardado(con, jobs, desde, hasta):
    cuenta = defaultdict(int)
    marcas = ','.join('?' * len(jobs))
    for nombre, direccion, ts in con.execute(
            f"select l.name, x.direction, x.timestamp from crossings x "
            f"join lane_configs l on l.id = x.lane_id where x.job_id in ({marcas})", jobs):
        if ts and desde <= ts[11:16] < hasta:
            cuenta[(traffic_db.numero_de_acceso(nombre or ''),
                    SENTIDO.get(direccion, direccion))] += 1
    return cuenta


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--proyecto', type=int, required=True)
    ap.add_argument('--detecciones', nargs='+', required=True)
    ap.add_argument('--desde', default='06:45')
    ap.add_argument('--hasta', default='07:45')
    ap.add_argument('--salida', default='data/fr/dobles_quitados.csv')
    a = ap.parse_args()

    import yaml
    cfg = yaml.safe_load(open(RAIZ / 'configs' / 'platform.yaml', encoding='utf-8')) or {}
    con = _bd()
    fila = con.execute("select perfil_deteccion from projects where id = ?", (a.proyecto,)).fetchone()
    perfil = perfil_deteccion.leer({'id': a.proyecto, 'perfil_deteccion': fila[0] if fila else None})
    perfil['umbral_linea'] = cfg.get('confidence_threshold', 0.25)
    dobles = perfil.get('dobles_contencion') or {'cuadros': 9, 'contencion': 0.7, 'edad_max': 20}
    zonas = load_zones(a.proyecto)

    rutas = sorted(r for patron in a.detecciones for r in glob.glob(patron))
    total = {'sin': defaultdict(int), 'con': defaultdict(int)}
    quitados, jobs = [], []
    for ruta in rutas:
        det = json.load(open(ruta, encoding='utf-8'))
        job = _job_de(con, a.proyecto, det['video'])
        if not job:
            print(f'{ruta}: su video no está en el proyecto {a.proyecto}; se omite')
            continue
        jobs.append(job['id'])
        for nombre, opcion in (('sin', None), ('con', dobles)):
            cuenta, q = contar(det, job, perfil, zonas, opcion, cfg.get('tracker', {}),
                               a.desde, a.hasta)
            for k, v in cuenta.items():
                total[nombre][k] += v
            if opcion:
                quitados += q
        print(f'{os.path.basename(ruta)} listo (job {job["id"]})', flush=True)

    base = guardado(con, jobs, a.desde, a.hasta) if jobs else {}
    claves = sorted(set(base) | set(total['sin']) | set(total['con']), key=str)
    print(f'\nVentana {a.desde}-{a.hasta}, dobles_contencion = {dobles}\n')
    print(f'{"línea · sentido":<18}{"guardado":>10}{"sin":>8}{"con":>8}{"quitados":>10}')
    for k in claves:
        s, c = total['sin'][k], total['con'][k]
        print(f'{f"{k[0]} · {k[1]}":<18}{base.get(k, 0):>10}{s:>8}{c:>8}{s - c:>10}')

    with open(RAIZ / a.salida, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['video', 'cuadro', 'hora', 'linea', 'rastro', 'pedazo_de'])
        w.writeheader()
        w.writerows(quitados)
    print(f'\n{len(quitados)} quitados -> {a.salida} (mirarlos a ojo antes de creer el número)')


if __name__ == '__main__':
    main()
