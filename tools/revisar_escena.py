"""¿Qué videos del aforo frontal miran de verdad a la vía?

Los primeros minutos están grabados dentro del carro del instalador. Se
compara un cuadro de cada video contra uno de la escena buena (12-24) por
correlación sobre una miniatura en gris: barato, sin GPU, y no depende del
detector.
"""
import cv2
import glob
import json
import numpy as np

REF = 'data/nuevos/20260919/12/24.mp4'  # cámbiese por un video donde la cámara ya esté montada


def mini(ruta, seg=5):
    cap = cv2.VideoCapture(ruta)
    if not cap.isOpened():
        return None
    fps = cap.get(cv2.CAP_PROP_FPS) or 20
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(seg * fps))
    ok, f = cap.read()
    if not ok:
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        ok, f = cap.read()
    cap.release()
    if not ok:
        return None
    g = cv2.cvtColor(cv2.resize(f, (64, 36)), cv2.COLOR_BGR2GRAY).astype(np.float32)
    return (g - g.mean()) / (g.std() + 1e-6)


ref = mini(REF)
salida = {}
for ruta in sorted(glob.glob('data/nuevos/20260919/*/*.mp4')):
    m = mini(ruta)
    salida[ruta] = None if m is None else round(float((ref * m).mean()), 3)
    print(ruta, salida[ruta], flush=True)
json.dump(salida, open('data/nuevos/escena.json', 'w'), indent=1)
buenos = [k for k, v in salida.items() if v is not None and v >= 0.5]
print('##### FIN ESCENA', len(buenos), 'parecidos a la vía de', len(salida))
