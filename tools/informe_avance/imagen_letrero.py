# -*- coding: utf-8 -*-
"""Un ejemplo real, grande y anotado, de un vehículo partido por el letrero."""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import patheffects
from PIL import Image

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / 'tools'))
from od_por_trayectoria import registros_de_video   # noqa: E402

ruta = RAIZ / 'data' / 'od' / 'tray' / 'ALTOZANO_VENTANA__07-26-25_2a.json'
accesos = [{'id': i + 1, 'name': d['nombre'], 'kind': 'acceso', 'points': d['puntos']}
           for i, d in enumerate(json.load(open(RAIZ / 'data' / 'od' / 'accesos_entrada_altozano.json',
                                                encoding='utf-8')))]
id_de = {a['name']: a['id'] for a in accesos}
regs, _ = registros_de_video(str(ruta), accesos)

# A: sale del arco y muere tapado por el letrero. B: nace del otro lado poco
# después y llega a la izquierda. Se elige uno que se pierda entre medio y un
# segundo y medio, el de recorridos más largos, para que se vea.
mejor = None
for a in regs:
    if a['org'] != id_de['Arco'] or a['dst'] == id_de['Izquierda']:
        continue
    fa = a['puntos'][-1]
    if not (840 <= fa[1] <= 960):
        continue
    for b in regs:
        if b['org'] is not None or b['dst'] != id_de['Izquierda']:
            continue
        ib = b['puntos'][0]
        hueco = b['t0'] - a['t1']
        if 0.5 <= hueco <= 1.5 and 700 <= ib[1] < fa[1] and abs(ib[2] - fa[2]) < 60:
            largo = min(a['t1'] - a['t0'], b['t1'] - b['t0'])
            if mejor is None or largo > mejor[1]:
                mejor = (hueco, largo, a, b)
hueco, _, A, B = mejor
print(f'hueco {hueco:.2f} s')

fondo = Image.open(str(ruta).replace('.json', '.jpg')).convert('RGB')
y0, y1 = 250, 720
fig, ax = plt.subplots(figsize=(7.2, 7.2 * (y1 - y0) / 1280), dpi=220)
ax.imshow(fondo.crop((0, y0, 1280, y1)))
ax.axis('off')
fig.subplots_adjust(0, 0, 1, 1)

contorno = [patheffects.Stroke(linewidth=6.5, foreground='white'), patheffects.Normal()]
for reg, color in ((A, '#eb6834'), (B, '#2a78d6')):
    ax.plot([p[1] for p in reg['puntos']], [p[2] - y0 for p in reg['puntos']], color=color,
            lw=3.5, solid_capstyle='round', path_effects=contorno)
fa, ib = A['puntos'][-1], B['puntos'][0]
ax.annotate('', xy=(ib[1], ib[2] - y0), xytext=(fa[1], fa[2] - y0),
            arrowprops=dict(arrowstyle='->', color='white', lw=2, linestyle=(0, (2, 2))))

caja = dict(boxstyle='round,pad=0.35', fc='white', ec='none', alpha=0.93)
estilo = dict(fontsize=8.5, color='#1f1f1d', bbox=caja)
a0 = A['puntos'][0]
ax.text(a0[1] - 20, a0[2] - y0 + 62, '1. Sale del arco', ha='center', **estilo)
ax.text(fa[1] + 10, fa[2] - y0 - 120, f'2. El letrero lo tapa\n(se pierde {hueco:.1f} s)',
        ha='left', **estilo)
ax.text(ib[1] - 30, ib[2] - y0 + 110, '3. Reaparece del otro lado:\nes el mismo vehículo',
        ha='right', **estilo)
bf = B['puntos'][-1]
ax.text(bf[1] + 20, bf[2] - y0 - 70, '4. Sigue hacia la calle norte (acceso 3)', ha='left',
        **estilo)
salida = RAIZ / 'data' / 'informe' / 'i1_letrero.png'
fig.savefig(salida)
print(salida)
