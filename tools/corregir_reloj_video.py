"""
Corrige la hora de lo ya contado en videos cuya cámara grabó a menos cuadros
por segundo de los que declara el archivo, SIN volver a detectar.

Antes de src/engine/reloj_video.py la hora de cada vehículo era
inicio + cuadro / fps declarado. En Gómez Morín (15 declarados, 10 grabados)
eso comprimía cada video de 10 min en sus primeros 6 min 44 s. Lo contado es
el mismo; lo que está mal es en qué minuto quedó cada vehículo.

Por video: lee el instante de cada cuadro del archivo (sin GPU, segundos a
640x360) y, si el ritmo real se aparta más de 5 % del guardado, vuelve a
poner la hora de:
  - crossings.timestamp (por su `cuadro` si lo tiene),
  - movimientos.timestamp (el cuadro se recupera de la hora vieja, ±0.5 s),
  - movimientos.recorrido["t"], que es de donde la matriz por trayectoria
    saca la hora de cada vehículo,
y guarda en video_jobs el fps real y quita el aviso de "archivo cortado" si
el video está completo.

    python tools/corregir_reloj_video.py --proyecto 26            # solo dice qué haría
    python tools/corregir_reloj_video.py --proyecto 26 --aplicar  # respalda la base y corrige

Después de aplicar hay que reiniciar la plataforma: la decisión por
trayectoria se guarda en memoria y su firma no ve un cambio de horas.
"""

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.engine.reloj_video import TOLERANCIA_FPS, tiempos_del_archivo  # noqa: E402
from src.storage import traffic_db  # noqa: E402

FORMATO = "%Y-%m-%d %H:%M:%S"


def _declarado(ruta):
    cap = cv2.VideoCapture(str(ruta))
    try:
        return cap.get(cv2.CAP_PROP_FPS) or 0, cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    finally:
        cap.release()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--proyecto', type=int, required=True)
    ap.add_argument('--aplicar', action='store_true')
    args = ap.parse_args()

    db = sqlite3.connect(str(traffic_db.DB_PATH), timeout=60)
    db.row_factory = sqlite3.Row
    if args.aplicar:
        respaldo = Path('data/respaldos') / (
            f"antes_reloj_p{args.proyecto}_{datetime.now():%Y-%m-%d_%H%M}.db")
        respaldo.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(respaldo)) as destino:
            db.backup(destino)
        print(f"Respaldo: {respaldo}")

    trabajos = db.execute(
        """SELECT id, original_name, stored_path, video_start_time, fps, aviso
             FROM video_jobs WHERE project_id = ? AND status = 'done'
                  AND video_start_time IS NOT NULL ORDER BY video_start_time""",
        (args.proyecto,)).fetchall()
    corregidos = 0
    for job in trabajos:
        fps_viejo = job['fps']
        if not fps_viejo or not Path(job['stored_path']).exists():
            continue
        fps_decl, cuadros_decl = _declarado(job['stored_path'])
        reloj = tiempos_del_archivo(job['stored_path'], fps_viejo)
        n = len(reloj)
        if not n or not reloj.duracion:
            continue
        fps_real = n / reloj.duracion
        if abs(fps_real - fps_viejo) <= TOLERANCIA_FPS * fps_viejo:
            continue
        corregidos += 1
        inicio = datetime.fromisoformat(job['video_start_time'])

        def nueva(cuadro):
            return (inicio + timedelta(seconds=reloj.segundos(cuadro))).strftime(FORMATO)

        def cuadro_de(ts):
            # La hora vieja es inicio + cuadro / fps_viejo truncada al segundo:
            # el cuadro cae en ese segundo, se toma su mitad.
            seg = (datetime.fromisoformat(ts) - inicio).total_seconds()
            return int((seg + 0.5) * fps_viejo)

        cambios_c, cambios_m = [], []
        for c in db.execute("SELECT id, timestamp, cuadro FROM crossings WHERE job_id = ?",
                            (job['id'],)):
            if c['timestamp']:
                cuadro = c['cuadro'] if c['cuadro'] is not None else cuadro_de(c['timestamp'])
                cambios_c.append((nueva(cuadro), c['id']))
        antes_fin = despues_fin = None
        for m in db.execute("SELECT id, timestamp, recorrido FROM movimientos WHERE job_id = ?",
                            (job['id'],)):
            rec = m['recorrido']
            if rec:
                rec = json.loads(rec)
                if rec.get('t'):
                    rec['t'] = [round(reloj.segundos(int(round(t * fps_viejo))), 2) for t in rec['t']]
                rec = json.dumps(rec, separators=(',', ':'))
            ts = nueva(cuadro_de(m['timestamp'])) if m['timestamp'] else None
            if m['timestamp'] and (antes_fin is None or m['timestamp'] > antes_fin):
                antes_fin, despues_fin = m['timestamp'], ts
            cambios_m.append((ts, rec, m['id']))

        aviso = job['aviso']
        completo = (not cuadros_decl or not fps_decl
                    or reloj.duracion >= 0.95 * cuadros_decl / fps_decl)
        if aviso and completo and 'Se leyeron' in aviso:
            aviso = re.sub(r"Se leyeron [^.]*?no se contó\.\s*", "", aviso).strip() or None
        print(f"{job['original_name']}: {fps_viejo:g} -> {fps_real:.2f} cuadros/s, "
              f"{reloj.duracion / 60:.1f} min, {len(cambios_c)} cruces, {len(cambios_m)} movimientos"
              + (f"; el último pasa de {antes_fin[11:]} a {despues_fin[11:]}" if antes_fin else ""))
        if args.aplicar:
            with db:
                db.executemany("UPDATE crossings SET timestamp = ? WHERE id = ?", cambios_c)
                db.executemany("UPDATE movimientos SET timestamp = ?, recorrido = ? WHERE id = ?",
                               cambios_m)
                db.execute("UPDATE video_jobs SET fps = ?, aviso = ? WHERE id = ?",
                           (fps_real, aviso, job['id']))
    print(f"{corregidos} de {len(trabajos)} videos con otro ritmo"
          + ("" if args.aplicar else " (no se cambió nada; --aplicar para corregir)"))


if __name__ == '__main__':
    main()
