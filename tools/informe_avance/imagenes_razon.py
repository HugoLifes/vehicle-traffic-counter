# -*- coding: utf-8 -*-
"""
Imágenes anotadas de POR QUÉ algunos aforos no salen tan altos. Todas son
cuadros reales de los videos (extraídos en el Jetson) o mapas hechos con los
rastros reales; aquí solo se recortan y se anotan.
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import patheffects
from matplotlib.patches import Rectangle
from PIL import Image

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / 'tools'))
from od_por_trayectoria import registros_de_video   # noqa: E402

F = RAIZ / 'data' / 'informe' / 'fuentes'
SAL = RAIZ / 'data' / 'informe'
AZUL, NARANJA, TINTA = '#2a78d6', '#eb6834', '#1f1f1d'
CAJA = dict(boxstyle='round,pad=0.35', fc='white', ec='none', alpha=0.93)
TXT = dict(fontsize=8.5, color=TINTA, bbox=CAJA)
BORDE = [patheffects.Stroke(linewidth=3.5, foreground='white'), patheffects.Normal()]


def lienzo(img, ancho_in=7.2):
    w, h = img.size
    fig, ax = plt.subplots(figsize=(ancho_in, ancho_in * h / w), dpi=220)
    ax.imshow(img)
    ax.axis('off')
    fig.subplots_adjust(0, 0, 1, 1)
    return fig, ax


def flecha(ax, desde, hasta, color='white'):
    ax.annotate('', xy=hasta, xytext=desde,
                arrowprops=dict(arrowstyle='->', color=color, lw=2.2,
                                path_effects=[patheffects.Stroke(linewidth=4.5, foreground=TINTA),
                                              patheffects.Normal()]))


# --- Juárez: de día contra de noche --------------------------------------
def juarez_dia_noche():
    y0, y1, esc = 120, 250, 2
    dia = Image.open(F / 'juarez' / 'dia_335.png').crop((0, y0, 640, y1))
    noche = Image.open(F / 'juarez' / 'noche_065.png').crop((0, y0, 640, y1))
    hoja = Image.new('RGB', (640, 2 * (y1 - y0) + 6), 'white')
    hoja.paste(dia, (0, 0))
    hoja.paste(noche, (0, y1 - y0 + 6))
    hoja = hoja.resize((hoja.width * esc, hoja.height * esc), Image.LANCZOS)
    fig, ax = lienzo(hoja)
    alto = (y1 - y0) * esc
    ax.text(12, 16, 'De día, 7:05: cada vehículo se ve completo', va='top', **TXT)
    ax.text(12, alto + 12 + 16, 'De noche, 21:01: el alumbrado y los faros queman la imagen', va='top',
            **TXT)
    ax.text(700, alto + 12 + 196, 'los vehículos quedan como rayas de luz', va='center', **TXT)
    flecha(ax, (690, alto + 12 + 196), (330, alto + 12 + 118))
    fig.savefig(SAL / 'i2_juarez_dia_noche.png')
    plt.close(fig)


# --- Juárez: tamaño en la calzada cercana contra la del fondo -------------
def juarez_tamano():
    """Donde está la línea de conteo (derecha del cuadro): cada vehículo con su
    calzada según las zonas reales del proyecto, no según su tamaño."""
    from src.engine.zones import _contiene
    zonas = {z['name']: z['points'] for z in json.load(open(F / 'juarez' / 'zonas.json'))}
    x0, y0, x1, y1, esc = 240, 150, 640, 226, 3
    img = Image.open(F / 'juarez' / 'pico_470.png').crop((x0, y0, x1, y1))
    img = img.resize((img.width * esc, img.height * esc), Image.LANCZOS)
    dets = json.load(open(F / 'juarez' / 'pico.json'))['pico_470']
    fig, ax = lienzo(img)
    for d in dets:
        bx1, by1, bx2, by2 = d['bbox']
        cx = (bx1 + bx2) / 2
        if cx < x0:
            continue
        cercana = _contiene(zonas['Calzada oriente'], cx, by2)
        color = AZUL if cercana else NARANJA
        ax.add_patch(Rectangle(((bx1 - x0) * esc, (by1 - y0) * esc), (bx2 - bx1) * esc,
                               (by2 - by1) * esc, fill=False, ec=color, lw=2.4))
        ax.text((bx2 - x0) * esc + 6, (by1 - y0) * esc, f'{by2 - by1:.0f} px', fontsize=9,
                color='white', va='top', fontweight='bold',
                path_effects=[patheffects.withStroke(linewidth=2.5, foreground=TINTA)])
    ax.text(8, img.height - 8, 'Azul: calzada cercana   ·   Naranja: calzada del fondo',
            va='bottom', **TXT)
    fig.savefig(SAL / 'i3_juarez_tamano.png')
    plt.close(fig)


# --- Mapas de dónde se pierden los vehículos -------------------------------
def perdidos(tray, accesos_json):
    """Último punto de cada vehículo que se perdió SIN llegar a un acceso de
    salida. Los que salen por la orilla del cuadro son salidas de verdad."""
    accesos = [{'id': i + 1, 'name': d['nombre'], 'kind': 'acceso', 'points': d['puntos']}
               for i, d in enumerate(json.load(open(accesos_json, encoding='utf-8')))]
    regs, _ = registros_de_video(str(tray), accesos)
    return [r['puntos'][-1][1:3] for r in regs if r['dst'] is None and r['t1'] - r['t0'] >= 1.0]


def puntos(ax, img, pts, y0):
    ax.scatter([p[0] for p in pts], [p[1] - y0 for p in pts], s=8, color=NARANJA, alpha=0.6,
               linewidths=0)
    ax.set_xlim(0, img.width)
    ax.set_ylim(img.height, 0)


def blvd_puente():
    y0 = 300
    img = Image.open(F / 'BLVD_IND_VENTANA__17-04-54_2a.jpg').convert('RGB').crop((0, y0, 1280, 720))
    pts = perdidos(F / 'BLVD_IND_VENTANA__17-04-54_2a.json', F / 'accesos_blvd_ind.json')
    fig, ax = lienzo(img)
    puntos(ax, img, pts, y0)
    ax.text(470, 40, 'Puente elevado', ha='center', **TXT)
    ax.text(640, 360, 'Cada punto naranja es un vehículo que el sistema perdió de vista sin saber '
                      'a dónde iba.', ha='center', va='center', **TXT)
    ax.text(1265, 20, 'El lente tapa\nesta esquina', ha='right', va='top', **TXT)
    fig.savefig(SAL / 'i4_blvd_puente.png')
    plt.close(fig)
    return len(pts)


def glorieta():
    y0 = 330
    img = Image.open(F / 'GLORIETA_07-14-09_2a.jpg').convert('RGB').crop((0, y0, 1280, 720))
    pts = perdidos(F / 'GLORIETA_VENTANA__07-14-09_2a.json', F / 'accesos_glorieta.json')
    fig, ax = lienzo(img)
    puntos(ax, img, pts, y0)
    ax.text(640, 25, 'Cada punto naranja es un vehículo que el sistema perdió de vista sin saber '
                     'a dónde iba.', ha='center', va='top', **TXT)
    ax.text(250, 250, 'Estacionamiento con\nautos quietos', ha='center', va='center', **TXT)
    fig.savefig(SAL / 'i5_glorieta.png')
    plt.close(fig)
    return len(pts)


# --- Altozano y Blvd Independencia: video de baja resolución --------------
def altozano_blvd_chico():
    img = Image.open(F / 'AFORO_ALTOZANO_Y_BLVD_INDEPENDENCIA.png').convert('RGB')
    img = img.crop((340, 300, 1280, 540))
    fig, ax = lienzo(img)
    ax.text(10, 12, 'Cada número amarillo es el alto del vehículo en píxeles', va='top', **TXT)
    ax.text(930, 228, 'Video de 640×360: lejos, los vehículos miden 10 a 21 px;\n'
                      'el sistema necesita unos 40 px para trabajar con holgura', ha='right',
            va='bottom', **TXT)
    fig.savefig(SAL / 'i6_altozano_blvd_chico.png')
    plt.close(fig)


# --- Entrada y salida Altozano: el camino del acceso 1 --------------------
def altozano_camino():
    img = Image.open(RAIZ / 'data' / 'od' / 'tray' / 'ALTOZANO_VENTANA__07-26-25_2a.jpg').convert('RGB')
    x0, y0 = 250, 360
    img = img.crop((x0, y0, 1280, 600))
    fig, ax = lienzo(img)
    ax.text(20, 200, 'Camino junto al canal (acceso 1): aquí los vehículos\n'
                     'se ven de unos 15 px y dan la vuelta en el mismo\n'
                     'lugar que el tránsito que sale del arco', va='center', **TXT)
    flecha(ax, (300, 150), (420 - x0 + 200, 440 - y0))
    ax.text(960, 20, 'Arco (acceso 2)', ha='right', va='top', **TXT)
    fig.savefig(SAL / 'i7_altozano_camino.png')
    plt.close(fig)


if __name__ == '__main__':
    juarez_dia_noche()
    juarez_tamano()
    print('Blvd Ind, vehículos perdidos:', blvd_puente())
    print('Glorieta, vehículos perdidos:', glorieta())
    altozano_blvd_chico()
    altozano_camino()
    print('listo')
