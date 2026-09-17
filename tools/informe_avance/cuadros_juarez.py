"""Cuadros de Cd. Juárez para el informe (de día, hora pico y de noche), con
las detecciones del modelo de producción. Corre en el contenedor del Jetson (decodifica video y usa la GPU; nunca en la
PC de desarrollo):
    docker compose -f docker-compose.jetson.yml exec -T -e PYTHONPATH=/app         aforo-vehicular python3 tools/informe_avance/cuadros_juarez.py
"""
import json
import os
import sqlite3

import cv2
import yaml

from src.detector import VehicleDetector

cfg = yaml.safe_load(open('configs/platform.yaml', encoding='utf-8'))
det = VehicleDetector(cfg.get('model_path', 'models/yolov8s.pt'), cfg.get('confidence_threshold', 0.25),
                      cfg.get('iou_threshold', 0.5), cfg.get('input_size', 1280), 'auto')
det.set_detection_band(None)
c = sqlite3.connect('file:data/traffic.db?mode=ro', uri=True)
salida = 'data/od/informe/juarez'
os.makedirs(salida, exist_ok=True)
zonas = [dict(zip(('name', 'points'), (r[0], json.loads(r[1]))))
         for r in c.execute("select name, points_json from zones where project_id=2")]
json.dump(zonas, open(f'{salida}/zonas.json', 'w'), ensure_ascii=False)
for job, etiqueta in ((2, 'dia'), (89, 'pico'), (26, 'noche')):
    ruta = c.execute('select stored_path from video_jobs where id=?', (job,)).fetchone()[0]
    cap = cv2.VideoCapture(ruta)
    fps = cap.get(cv2.CAP_PROP_FPS) or 15
    todo = {}
    for s in range(20, 600, 45):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(s * fps))
        ok, f = cap.read()
        if not ok:
            continue
        nombre = f'{etiqueta}_{s:03d}'
        cv2.imwrite(f'{salida}/{nombre}.png', f)
        dets, _ = det.detect(f)
        todo[nombre] = [{'bbox': [round(v, 1) for v in d['bbox']], 'conf': round(d['confidence'], 2),
                         'clase': d['class_name']} for d in dets]
    json.dump(todo, open(f'{salida}/{etiqueta}.json', 'w'))
    print(etiqueta, len(todo), 'cuadros', ruta)
