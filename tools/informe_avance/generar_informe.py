# -*- coding: utf-8 -*-
"""
Informe de avance para la empresa: aforo por línea (Cd. Juárez) y aforo
direccional (Entrada y salida Altozano), escrito para quien no es técnico.

Las cifras de Juárez salen de los JSON de tools/exportar_comparacion.py
(corrido en el Jetson). Las del direccional son las medidas en esta sesión
con tools/od_por_trayectoria.py y comparar_od_real.py; están juntas en
DIRECCIONAL abajo para que no haya una cifra suelta en el texto.

Orden para regenerarlo (las fuentes viven en data/, que no va al repo):
  1. En el Jetson: tools/exportar_comparacion.py --proyecto 2 (ambos, y
     --zona "Calzada oriente" / "Calzada poniente") -> data/informe/juarez_*.json
  2. En el Jetson: tools/informe_avance/cuadros_juarez.py -> cuadros de día,
     hora pico y noche; copiarlos a data/informe/fuentes/juarez/
  3. Aquí: imagen_letrero.py e imagenes_razon.py (solo recortan y anotan
     imágenes y rastros ya extraídos; no procesan video)
  4. Aquí: generar_informe.py -> data/informe/Informe_aforo_vehicular_*.pdf,
     con los dos Excel adjuntos dentro
"""
import json
import math
import os
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from PIL import Image as PILImage

RAIZ = Path(__file__).resolve().parents[2]
DATOS = RAIZ / 'data' / 'informe'
SALIDA = DATOS / 'Informe_aforo_vehicular_2026-09-17.pdf'
EXCELS = [
    (RAIZ / 'data' / 'aforo_juarez_recontado.xlsx', 'Aforo_Cd_Juarez_19-ago-2026.xlsx'),
    (RAIZ / 'data' / 'aforo_entrada_altozano_trayectoria.xlsx',
     'Aforo_direccional_Entrada_y_salida_Altozano.xlsx'),
]

# --- Colores (paleta validada: azul, naranja, aqua; gris para la referencia)
AZUL = '#2a78d6'       # sistema / ahora
NARANJA = '#eb6834'    # antes
AQUA = '#1baf7a'       # segunda serie (calzada del fondo)
GRIS_REF = '#c9c7c0'   # conteo manual (referencia)
TINTA = '#1f1f1d'
TINTA_2 = '#52514e'
REJILLA = '#e6e4df'
FONDO_NOCHE = '#f1f0ec'
BIEN = '#0ca30c'
MAL = '#d03b3b'

plt.rcParams.update({
    'font.family': 'DejaVu Sans', 'font.size': 9, 'axes.edgecolor': REJILLA,
    'axes.labelcolor': TINTA_2, 'xtick.color': TINTA_2, 'ytick.color': TINTA_2,
    'axes.titlesize': 10.5, 'axes.titleweight': 'bold', 'axes.titlecolor': TINTA,
})


def miles(n):
    return f'{int(round(n)):,}'.replace(',', '\u00a0')


def ejes_limpios(ax, eje_y=True):
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    ax.spines['left'].set_visible(False)
    ax.spines['bottom'].set_color(REJILLA)
    if eje_y:
        ax.grid(axis='y', color=REJILLA, lw=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)


# =========================================================================
# Datos
# =========================================================================
def cargar(n):
    return json.load(open(DATOS / f'juarez_{n}.json', encoding='utf-8'))


J = {n: cargar(n) for n in ('ambos', 'cercana', 'fondo')}
MEDIBLES = [f'{h:02d}:00' for h in range(7, 20)]


def suma(n, horas):
    hs = [h for h in J[n]['horas'] if h['hora'] in horas]
    return sum(h['nuestro'] for h in hs), sum(h['manual'] for h in hs)


TOT = {n: suma(n, MEDIBLES) for n in J}


def por_volumen():
    hs = [h for h in J['ambos']['horas'] if h['hora'] in MEDIBLES]
    bajas = [h for h in hs if h['manual'] < 1600]
    altas = [h for h in hs if h['manual'] >= 2000]
    r = lambda g: sum(h['nuestro'] for h in g) / sum(h['manual'] for h in g)
    return r(bajas), len(bajas), r(altas), len(altas)


VOL = por_volumen()
COMP = J['ambos']['composicion']

DIRECCIONAL = {
    # tools/od_por_trayectoria.py, plantillas de los videos de 07:46 y 07:56
    # (otros videos del mismo aforo); 7:15 cubierto al 91 %, manual escalado.
    'cuartos': [('7:15 a 7:30', 193, 157, 198, '91 %'),
                ('7:30 a 7:45', 275, 189, 264, '100 %')],
    'total': (468, 346, 462),
    'movimientos': [
        # clave, descripción, manual, antes, ahora, GEH antes, GEH ahora
        ('2 → 3', 'Del arco (fraccionamiento) a la calle norte', 434, 334, 457, 7.4, 1.6),
        ('1 → 3', 'Del camino junto al canal a la calle norte', 14, 0, 0, 7.5, 7.5),
        ('3 → 1', 'De la calle norte al camino junto al canal', 13, 0, 0, 7.3, 7.3),
        ('3 → 2', 'De la calle norte al arco', 5, 5, 5, 0.1, 0.1),
        ('2 → 1', 'Del arco al camino junto al canal', 3, 0, 0, 3.4, 3.4),
    ],
    # comparar_od_real.py en el Jetson, proyecto 5 recontado, 7:30 a 7:45
    'plataforma_730': {'manual': 275, 'antes': 194, 'ahora': 266,
                       'principal_manual': 252, 'principal_ahora': 260, 'geh': 1.0},
    'decision': {'zonas': 609, 'trayectoria': 214, 'sin_decidir': 166},
}

ENCUADRE = [
    ('Entrada y salida Altozano 07:26', 'Bueno (78)', 'Sirvió', True),
    ('Entrada y salida Altozano 07:56', 'Regular (65)', 'Sirvió', True),
    ('Entrada y salida Altozano 06:56 (amanecer)', 'No recomendable (0)', 'No se ve nada a esa hora', True),
    ('Glorieta Altozano 07:14', 'No recomendable (39)', 'Falló', True),
    ('Altozano y Blvd Independencia 07:49', 'No recomendable (38)', 'Vehículos muy chicos', True),
    ('Fraccionamientos 07:26', 'Regular (51)', 'Sin conteo manual para comparar', None),
    ('Fraccionamientos 06:46', 'No recomendable (49)', 'Sin conteo manual para comparar', None),
    ('Blvd Independencia 17:04', 'Regular (74)', 'Falló: el puente tapa dos accesos', False),
]


# =========================================================================
# Gráficas
# =========================================================================
def grafica_juarez_horas():
    horas = J['ambos']['horas']
    etiquetas = [h['hora'][:2] for h in horas]
    x = range(len(horas))
    fig, ax = plt.subplots(figsize=(7.2, 3.3), dpi=200)
    # Noche sombreada: horas fuera del horario medible.
    for i, h in enumerate(horas):
        if h['hora'] not in MEDIBLES:
            ax.axvspan(i - 0.5, i + 0.5, color=FONDO_NOCHE, lw=0, zorder=0)
    ax.bar(x, [h['manual'] for h in horas], width=0.78, color=GRIS_REF,
           label='Conteo manual (la referencia)', zorder=2)
    ax.bar(x, [h['nuestro'] for h in horas], width=0.42, color=AZUL,
           label='Sistema de video', zorder=3)
    ax.set_xticks(list(x))
    ax.set_xticklabels(etiquetas)
    ax.set_xlabel('Hora del día (19 de agosto de 2026; faltan 00 y 01 h en el video)')
    ax.set_ylabel('Vehículos por hora')
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: miles(v)))
    ejes_limpios(ax)
    ax.set_xlim(-0.6, len(horas) - 0.4)
    top = max(h['manual'] for h in horas)
    ax.set_ylim(0, top * 1.18)
    i0 = etiquetas.index('07')
    i1 = etiquetas.index('19')
    ax.annotate('', xy=(i0 - 0.45, top * 1.10), xytext=(i1 + 0.45, top * 1.10),
                arrowprops=dict(arrowstyle='<->', color=TINTA_2, lw=1))
    ax.text((i0 + i1) / 2, top * 1.12, 'Horario medible: 07:00 a 20:00', ha='center',
            va='bottom', color=TINTA, fontsize=8.5)
    ax.text(1.5, top * 0.62, 'Noche:\nno medible', ha='center', color=TINTA_2, fontsize=8)
    ax.text(len(horas) - 2.5, top * 0.62, 'Noche:\nno medible', ha='center', color=TINTA_2,
            fontsize=8)
    ax.legend(frameon=False, loc='upper center', bbox_to_anchor=(0.5, -0.2), ncol=2, fontsize=8)
    ax.set_title('Vehículos por hora, ambos sentidos: sistema contra conteo manual', loc='left')
    fig.tight_layout()
    ruta = DATOS / 'g1_juarez_horas.png'
    fig.savefig(ruta)
    plt.close(fig)
    return ruta


def grafica_juarez_razon():
    fig, ax = plt.subplots(figsize=(7.2, 3.0), dpi=200)
    ax.axhspan(0.9, 1.1, color='#eef4fc', lw=0, zorder=0)
    ax.axhline(1.0, color=TINTA_2, lw=1, zorder=1)
    ax.text(12.45, 1.003, '1.00 = mismo número\nque el manual', color=TINTA_2, fontsize=7.5,
            va='bottom', ha='right')
    ax.text(-0.35, 1.075, 'franja de ±10 %', color=TINTA_2, fontsize=7.5, va='bottom', ha='left')
    for nombre, color, etiqueta in (('cercana', AZUL, 'Calzada cercana a la cámara'),
                                    ('fondo', AQUA, 'Calzada del fondo')):
        hs = [h for h in J[nombre]['horas'] if h['hora'] in MEDIBLES]
        ys = [h['nuestro'] / h['manual'] for h in hs]
        ax.plot(range(len(hs)), ys, color=color, lw=2, marker='o', ms=6,
                markeredgecolor='white', markeredgewidth=1.5, label=etiqueta, zorder=3)
    ax.set_xticks(range(len(MEDIBLES)))
    ax.set_xticklabels([m[:2] for m in MEDIBLES])
    ax.set_xlabel('Hora del día (solo el horario medible)')
    ax.set_ylabel('Razón (sistema ÷ manual)')
    ax.set_ylim(0.6, 1.15)
    ejes_limpios(ax)
    ax.legend(frameon=False, loc='upper center', bbox_to_anchor=(0.5, -0.24), ncol=2, fontsize=8)
    ax.set_title('Razón por hora: qué fracción del conteo manual capturó el sistema', loc='left')
    fig.tight_layout()
    ruta = DATOS / 'g2_juarez_razon.png'
    fig.savefig(ruta)
    plt.close(fig)
    return ruta


def grafica_altozano_cuartos():
    cuartos = DIRECCIONAL['cuartos']
    fig, ax = plt.subplots(figsize=(7.2, 3.0), dpi=200)
    ancho = 0.24
    series = [('Conteo manual (la referencia)', GRIS_REF, 1),
              ('Antes: por zonas', NARANJA, 2),
              ('Ahora: por recorrido', AZUL, 3)]
    for k, (etiqueta, color, idx) in enumerate(series):
        xs = [i + (k - 1) * (ancho + 0.02) for i in range(len(cuartos))]
        ys = [c[idx] for c in cuartos]
        ax.bar(xs, ys, width=ancho, color=color, label=etiqueta, zorder=2)
        for xx, yy in zip(xs, ys):
            ax.text(xx, yy + 5, miles(yy), ha='center', va='bottom', fontsize=8, color=TINTA)
    ax.set_xticks(range(len(cuartos)))
    ax.set_xticklabels([f'{c[0]}\n(video cubre {c[4]} del cuarto)' for c in cuartos])
    ax.set_ylabel('Vehículos en el cuarto de hora')
    ax.set_ylim(0, 330)
    ejes_limpios(ax)
    ax.legend(frameon=False, loc='upper left', fontsize=8)
    ax.set_title('Entrada y salida Altozano: vehículos por cuarto de hora', loc='left')
    fig.tight_layout()
    ruta = DATOS / 'g3_altozano_cuartos.png'
    fig.savefig(ruta)
    plt.close(fig)
    return ruta


def grafica_altozano_geh():
    movs = DIRECCIONAL['movimientos']
    fig, ax = plt.subplots(figsize=(7.2, 3.1), dpi=200)
    alto = 0.34
    ys = list(range(len(movs)))[::-1]
    ax.axvspan(0, 5, color='#eef8ee', lw=0, zorder=0)
    ax.axvline(5, color=TINTA_2, lw=1, zorder=1)
    ax.text(5.12, -0.62, 'límite: 5 (a la izquierda se acepta)', color=TINTA_2, fontsize=7.5,
            va='center')
    for k, (etiqueta, color, idx) in enumerate((('Antes: por zonas', NARANJA, 5),
                                                ('Ahora: por recorrido', AZUL, 6))):
        pos = [y + (0.5 - k) * (alto + 0.03) for y in ys]
        vals = [m[idx] for m in movs]
        ax.barh(pos, vals, height=alto, color=color, label=etiqueta, zorder=2)
        for p, v in zip(pos, vals):
            ax.text(v + 0.12, p, f'{v:.1f}', va='center', fontsize=7.5, color=TINTA)
    ax.set_yticks(ys)
    ax.set_yticklabels([f'{m[0]}  (manual: {m[2]})' for m in movs])
    ax.set_xlabel('GEH (entre más bajo, más parecido al conteo manual)')
    ax.set_xlim(0, 9.5)
    ax.set_ylim(-0.85, len(movs) - 0.45)
    ejes_limpios(ax, eje_y=False)
    ax.grid(axis='x', color=REJILLA, lw=0.8)
    ax.legend(frameon=False, loc='upper center', bbox_to_anchor=(0.5, -0.2), ncol=2, fontsize=8)
    ax.set_title('Entrada y salida Altozano: GEH de cada movimiento', loc='left')
    fig.tight_layout()
    ruta = DATOS / 'g4_altozano_geh.png'
    fig.savefig(ruta)
    plt.close(fig)
    return ruta


def imagen_letrero():
    """Un ejemplo real anotado (imagen_letrero.py, con los rastros de 07:26)."""
    return DATOS / 'i1_letrero.png'


# =========================================================================
# PDF
# =========================================================================
def construir():
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph,
                                    SimpleDocTemplate, Spacer, Table, TableStyle)

    carpeta = Path(matplotlib.get_data_path()) / 'fonts' / 'ttf'
    pdfmetrics.registerFont(TTFont('DV', str(carpeta / 'DejaVuSans.ttf')))
    pdfmetrics.registerFont(TTFont('DVB', str(carpeta / 'DejaVuSans-Bold.ttf')))
    pdfmetrics.registerFont(TTFont('DVI', str(carpeta / 'DejaVuSans-Oblique.ttf')))
    from reportlab.pdfbase.pdfmetrics import registerFontFamily
    registerFontFamily('DV', normal='DV', bold='DVB', italic='DVI', boldItalic='DVB')

    tinta = colors.HexColor(TINTA)
    gris = colors.HexColor(TINTA_2)
    base = dict(fontName='DV', textColor=tinta, leading=14, fontSize=10)
    E = {
        'titulo': ParagraphStyle('titulo', **{**base, 'fontName': 'DVB', 'fontSize': 21,
                                              'leading': 26, 'spaceAfter': 4}),
        'sub': ParagraphStyle('sub', **{**base, 'textColor': gris, 'fontSize': 10.5}),
        'h1': ParagraphStyle('h1', **{**base, 'fontName': 'DVB', 'fontSize': 15, 'leading': 19,
                                      'spaceBefore': 4, 'spaceAfter': 6}),
        'h2': ParagraphStyle('h2', **{**base, 'fontName': 'DVB', 'fontSize': 11.5,
                                      'leading': 15, 'spaceBefore': 10, 'spaceAfter': 4}),
        'p': ParagraphStyle('p', **{**base, 'spaceAfter': 6, 'alignment': TA_LEFT}),
        'nota': ParagraphStyle('nota', **{**base, 'fontSize': 8.5, 'leading': 11.5,
                                          'textColor': gris, 'spaceAfter': 6}),
        'caja': ParagraphStyle('caja', **{**base, 'fontSize': 9.5, 'leading': 13}),
        'celda': ParagraphStyle('celda', **{**base, 'fontSize': 8.5, 'leading': 11}),
        'celda_b': ParagraphStyle('celda_b', **{**base, 'fontName': 'DVB', 'fontSize': 8.5,
                                                'leading': 11}),
        'cifra': ParagraphStyle('cifra', **{**base, 'fontName': 'DVB', 'fontSize': 26,
                                            'leading': 30, 'textColor': colors.HexColor(AZUL)}),
    }

    def P(texto, estilo='p'):
        return Paragraph(texto, E[estilo])

    def caja(titulo, cuerpo, fondo='#f4f7fb', borde=AZUL):
        t = Table([[P(f'<b>{titulo}</b><br/>{cuerpo}', 'caja')]], colWidths=[16.6 * cm])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(fondo)),
            ('LINEBEFORE', (0, 0), (0, -1), 3, colors.HexColor(borde)),
            ('LEFTPADDING', (0, 0), (-1, -1), 10), ('RIGHTPADDING', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 7), ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        return t

    def tabla(filas, anchos, cabecera=True, alinear_der=()):
        datos = [[c if not isinstance(c, str) else P(c, 'celda_b' if (cabecera and i == 0)
                                                     else 'celda')
                  for c in fila] for i, fila in enumerate(filas)]
        t = Table(datos, colWidths=[a * cm for a in anchos], repeatRows=1 if cabecera else 0)
        estilo = [
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor(REJILLA)),
            ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]
        if cabecera:
            estilo += [('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f0ec')),
                       ('LINEBELOW', (0, 0), (-1, 0), 1, colors.HexColor(TINTA_2))]
        t.setStyle(TableStyle(estilo))
        return t

    def figura(ruta, ancho_cm=17.0):
        with PILImage.open(ruta) as im:
            w, h = im.size
        return Image(str(ruta), width=ancho_cm * cm, height=ancho_cm * cm * h / w)

    def razon(a, b):
        return f'{a / b:.2f}×'

    def foto(nombre, pie, titulo=None, ancho=17.0):
        bloque = ([P(titulo, 'h2')] if titulo else []) + [figura(DATOS / nombre, ancho),
                                                          Spacer(1, 3), P(pie, 'nota')]
        return KeepTogether(bloque)

    story = []

    # ---------------------------------------------------------------- portada
    story += [
        P('Informe de avance: aforo vehicular con video', 'titulo'),
        P('Resultados medidos contra conteos manuales hechos en campo · 17 de septiembre de 2026', 'sub'),
        Spacer(1, 14),
        P('Lo más importante', 'h1'),
    ]
    na, ma = TOT['ambos']
    nc, mc = TOT['cercana']
    tiles = [
        [P(razon(na, ma), 'cifra'), P(razon(nc, mc), 'cifra'),
         P(razon(DIRECCIONAL['total'][2], DIRECCIONAL['total'][0]), 'cifra')],
        [P(f'<b>Cd. Juárez, ambos sentidos</b><br/>De 07:00 a 20:00 el sistema contó '
           f'{miles(na)} vehículos; el conteo manual, {miles(ma)}.', 'caja'),
         P(f'<b>Cd. Juárez, calzada cercana</b><br/>Mismo horario: {miles(nc)} contra '
           f'{miles(mc)}. Prácticamente el mismo número.', 'caja'),
         P(f'<b>Aforo direccional, Entrada y salida Altozano</b><br/>'
           f'{DIRECCIONAL["total"][2]} vehículos contra {DIRECCIONAL["total"][0]} '
           f'(cuartos de 7:15 y 7:30).', 'caja')],
    ]
    t = Table(tiles, colWidths=[5.55 * cm] * 3)
    t.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f4f7fb')),
        ('LINEAFTER', (0, 0), (1, -1), 6, colors.white),
        ('LEFTPADDING', (0, 0), (-1, -1), 9), ('RIGHTPADDING', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, 0), 9), ('BOTTOMPADDING', (0, -1), (-1, -1), 10),
    ]))
    story += [t, Spacer(1, 6),
              P('Los tres números son la <b>razón</b>: lo que contó el sistema dividido entre lo '
                'que contó una persona en campo. <b>1.00×</b> quiere decir el mismo número; '
                '<b>0.95×</b> quiere decir que por cada 100 vehículos reales el sistema contó 95. '
                'En la página 2 están explicados todos los términos del informe.', 'nota'),
              Spacer(1, 4),
              P('Qué quiere decir', 'h2'),
              P('<b>De día, el conteo por línea ya es confiable.</b> En Cd. Juárez, durante las 13 '
                'horas de luz, el sistema capturó el 95 % de los vehículos, y en la calzada cercana '
                'a la cámara prácticamente todos. Además sigue el mismo "dibujo" del día que el '
                'conteo manual: sube y baja en las mismas horas.'),
              P('<b>El aforo direccional funciona cuando la cámara ve bien el cruce.</b> En Entrada '
                'y salida Altozano pasó de contar 74 de cada 100 vehículos a contar 99 de cada 100. '
                'En los cruces donde la cámara no ve los accesos (un puente que los tapa, una '
                'glorieta fuera de cuadro) no hay ajuste que lo arregle.'),
              P('<b>El límite ya no es el programa sino la cámara:</b> de noche la imagen se quema, '
                'y en los cruces grandes hace falta un buen ángulo o una segunda cámara.'),
              Spacer(1, 4),
              caja('Archivos que acompañan este informe',
                   'Los dos Excel con los conteos van adjuntos dentro de este PDF (en el visor, '
                   'ícono del clip o panel de "Archivos adjuntos") y también por separado: '
                   '<b>Aforo_Cd_Juarez_19-ago-2026.xlsx</b> y '
                   '<b>Aforo_direccional_Entrada_y_salida_Altozano.xlsx</b>. En la última página '
                   'se explica qué trae cada hoja.'),
              PageBreak()]

    # --------------------------------------------------------------- glosario
    story += [P('Cómo leer este informe', 'h1'),
              P('Estos son los términos que aparecen en las tablas y gráficas. Cada uno lleva un '
                'ejemplo con números de este mismo informe.', 'p')]
    glosario = [
        ('Conteo manual', 'Es la <b>referencia</b>: una persona en campo contó los vehículos por '
         'cuartos de hora. Todo lo que mide el sistema se compara contra él.'),
        ('Razón', 'Lo que contó el sistema <b>dividido entre</b> lo que contó el conteo manual. '
         '<b>1.00×</b> = el mismo número. <b>Menos de 1</b> = el sistema se quedó corto. '
         '<b>Más de 1</b> = contó de más. Ejemplo: 22 244 ÷ 23 431 = <b>0.95×</b>, o sea 95 de cada '
         '100 vehículos. La "×" se lee "veces".'),
        ('Horario medible', 'Las horas en las que la cámara permite contar bien. En Cd. Juárez son '
         'de 07:00 a 20:00. Fuera de ese horario la cifra del sistema no se debe usar.'),
        ('Calzada cercana y calzada del fondo', 'Cada sentido de la avenida. La cercana pasa junto a '
         'la cámara y los vehículos se ven grandes; en la del fondo se ven chicos, y por eso cuenta '
         'un poco menos.'),
        ('Cuarto de hora', 'El conteo se entrega en bloques de 15 minutos (7:15 a 7:30, 7:30 a '
         '7:45...), igual que el conteo manual.'),
        ('Acceso', 'Cada calle que llega al cruce. Se numeran igual que en el croquis de la '
         'empresa: 1, 2, 3...'),
        ('Movimiento (2 → 3)', 'Los vehículos que <b>entran</b> por el acceso 2 y <b>salen</b> por '
         'el 3. En los Excel de la empresa se escribe "2_3".'),
        ('Aforo direccional', 'El conteo que dice no solo cuántos vehículos pasaron, sino de dónde '
         'venían y a dónde fueron (vueltas a la izquierda, a la derecha, de frente y en U).'),
        ('GEH', 'La medida que se usa en estudios de tránsito para decidir si dos conteos se '
         'parecen lo suficiente. Toma en cuenta el tamaño: una diferencia de 10 vehículos es grave '
         'si el movimiento tiene 20, pero no si tiene 2 000. <b>Menos de 5 se acepta.</b> El '
         'criterio pide que al menos el <b>85 %</b> de los movimientos esté por debajo de 5. '
         'Ejemplo: 260 del sistema contra 252 del manual en un cuarto de hora da GEH 1.0, muy '
         'bueno. (Cálculo: con los flujos por hora M y C, GEH = raíz de 2(M − C)² ÷ (M + C).)'),
        ('Correlación (r)', 'Qué tanto se parece el "dibujo" de subidas y bajadas a lo largo del '
         'día entre el sistema y el conteo manual. +1 es idéntico y 0 es que no tienen nada que ver. '
         'En Cd. Juárez dio <b>r = +0.96</b>: el sistema marca las horas pico en las mismas horas.'),
        ('Tamaño del vehículo en píxeles', 'Qué tan grande se ve un vehículo en la imagen. El '
         'sistema trabaja con holgura desde unos 40 píxeles de alto; en la calzada del fondo de Cd. '
         'Juárez miden 14 a 17 y por eso ahí cuenta menos.'),
        ('Sin decidir', 'En el aforo direccional, vehículos de los que se vio tan poco que no se '
         'sabe a dónde iban. <b>No se reparten ni se inventan</b>: se declaran aparte.'),
    ]
    story.append(tabla([[P(f'<b>{a}</b>', 'celda'), P(b, 'celda')] for a, b in glosario],
                       [3.8, 13.0], cabecera=False))
    story.append(PageBreak())

    # --------------------------------------------------------------- Juárez
    nf, mf = TOT['fondo']
    story += [
        P('1. Aforo por línea: Cd. Juárez', 'h1'),
        P('Un día completo (19 de agosto de 2026) grabado en 135 videos de 10 minutos. El sistema '
          f'contó <b>{miles(23859)} vehículos</b> en las 24 horas y se comparó hora por hora contra '
          'el conteo manual del mismo día.'),
        P('Resultado en el horario medible (07:00 a 20:00)', 'h2'),
        tabla([
            ['Calzada', 'Sistema', 'Conteo manual', 'Razón', 'Qué significa'],
            ['Cercana a la cámara', miles(nc), miles(mc), razon(nc, mc),
             'Prácticamente el mismo número'],
            ['Del fondo', miles(nf), miles(mf), razon(nf, mf),
             '90 de cada 100: los vehículos se ven chicos'],
            ['<b>Ambos sentidos</b>', f'<b>{miles(na)}</b>', f'<b>{miles(ma)}</b>',
             f'<b>{razon(na, ma)}</b>', '<b>95 de cada 100 vehículos</b>'],
        ], [3.6, 2.4, 2.8, 1.9, 6.1]),
        P(f'Composición vehicular en ese horario: el sistema dio <b>{COMP["nuestro_A_pct"]} % '
          f'livianos y {COMP["nuestro_PES_pct"]} % pesados</b>; el conteo manual, '
          f'{COMP["manual_A_pct"]} % y {COMP["manual_PES_pct"]} %.', 'nota'),
        KeepTogether([
            P('Gráfica 1. Vehículos por hora', 'h2'),
            figura(grafica_juarez_horas()),
            caja('Cómo leer esta gráfica',
                 'Cada hora tiene dos barras. La <b>gris ancha</b> es lo que contó la persona en '
                 'campo; la <b>azul delgada</b>, lo que contó el sistema. Cuando la azul llega a la '
                 'altura de la gris, el sistema contó todos. De 07:00 a 19:00 casi siempre llega. '
                 'En las horas sombreadas (noche) la azul casi desaparece: la cámara no deja contar. '
                 'Ojo: las 05:00 son una hora pico del día (2 038 vehículos) y hoy no se pueden medir.'),
        ]),
        PageBreak(),
        KeepTogether([
            P('Gráfica 2. Razón por hora, por calzada', 'h2'),
            figura(grafica_juarez_razon()),
            caja('Cómo leer esta gráfica',
                 'Cada punto es la razón de una hora: lo que contó el sistema entre lo que contó '
                 'la persona. La <b>línea horizontal en 1.00</b> es "contó exactamente lo mismo"; '
                 'la <b>franja azul clara</b> marca ±10 % alrededor. Los puntos <b>azules</b> '
                 '(calzada cercana) van casi pegados a la línea todo el día. Los <b>verdes</b> '
                 '(calzada del fondo) bajan de 11:00 a 13:00 y, sobre todo, de 15:00 a 18:00, que es '
                 'cuando más tránsito hay: los vehículos del fondo, que ya se ven chicos, se tapan '
                 'entre sí. En su peor hora (15:00) el sistema contó 72 de cada 100.'),
        ]),
        P('Por qué la noche no se mide', 'h2'),
        P('No es por falta de luz, sino por <b>exceso</b>. De noche la cámara abre la exposición al '
          'máximo: la imagen sale el doble de brillante que de día, los faros se queman y cada '
          'vehículo en movimiento se vuelve una estela de luz. El programa no puede contar una '
          'estela. <b>Lo primero que hay que probar es forzar en la cámara el obturador rápido '
          '(modo nocturno)</b> y grabar diez minutos de noche para comprobarlo. Es gratis.'),
        foto('i2_juarez_dia_noche.png',
             'La misma cámara, el mismo tramo de la avenida. <b>Arriba</b>, a las 7:05: los vehículos '
             'se ven completos y el sistema los reconoce. <b>Abajo</b>, a las 21:01: las luminarias '
             'se ven como estrellas, el pavimento sale blanco y de los vehículos solo quedan rayas de '
             'luz de los faros. En los cuadros de noche que se revisaron el sistema reconoció entre 0 '
             'y 1 vehículo.', ancho=15.0),
        P('Qué más baja la exactitud', 'h2'),
        P(f'Con la avenida llena la exactitud baja. En las {VOL[1]} horas con menos de 1 600 '
          f'vehículos el sistema contó <b>{round(100 * VOL[0])} de cada 100</b>; en las {VOL[3]} horas '
          f'con 2 000 o más, <b>{round(100 * VOL[2])} de cada 100</b>. Es porque los vehículos se tapan '
          'entre sí desde este ángulo, sobre todo en la calzada del fondo. Se mejora subiendo la '
          'cámara o poniéndola más de frente a la avenida, no con el programa. <b>Por eso la '
          'exactitud se debe declarar por horario</b>: 0.95× es el promedio del día, no el de la '
          'hora pico.'),
        foto('i3_juarez_tamano.png',
             'Un cuadro de las 15:08, ampliado, en la parte de la imagen donde se cuenta. Cada caja es '
             'un vehículo que reconoció el sistema, con su alto en píxeles (qué tan grande se ve). En '
             'la <b>calzada cercana</b> (azul) miden 27 a 32 px; en la <b>calzada del fondo</b> '
             '(naranja), 16 px: la mitad. Con tan pocos puntos el sistema duda más, y por eso esa '
             'calzada queda en 0.90×. Las dos cajas azules encimadas muestran el otro problema: con '
             'la avenida llena, un vehículo tapa a otro.',
             'Por qué la calzada del fondo cuenta menos'),
        PageBreak(),
    ]

    # ----------------------------------------------------------- direccional
    d = DIRECCIONAL
    story += [
        P('2. Aforo direccional: Entrada y salida Altozano', 'h1'),
        P('Un aforo direccional dice, además de cuántos vehículos pasaron, <b>por qué calle '
          'entraron y por cuál salieron</b>. La empresa entregó el conteo manual de este cruce de '
          '6:45 a 7:45 del 8 de abril de 2025, con tres accesos numerados en el croquis: '
          '<b>1</b> = camino junto al canal, <b>2</b> = calle del fraccionamiento (la del arco) y '
          '<b>3</b> = calle al norte. Casi todo el tránsito hace el movimiento <b>2 → 3</b>: sale del '
          'fraccionamiento hacia el norte.'),
        P('Qué estaba fallando', 'h2'),
        P('<b>1. Un letrero de peatones tapa a los vehículos</b> justo después de salir del arco. El '
          'sistema los perdía de vista un momento, y al reaparecer ya no sabía que eran los mismos: '
          'quedaban como dos vehículos "a medias" y no se contaban.'),
        figura(imagen_letrero(), 17.0),
        P('Un vehículo real del video de las 7:26. En <b>naranja</b>, su recorrido desde el arco '
          'hasta que el letrero lo tapa; en <b>azul</b>, su recorrido después del letrero; la '
          'flecha blanca une los dos pedazos. Antes el sistema no sabía que eran el mismo vehículo; '
          'ahora sí. (El fondo es un cuadro del video: los autos estacionados son de otro '
          'momento.)', 'nota'),
        P('<b>2. Una zona mal dibujada inventaba movimientos.</b> La zona de un camino de terracería '
          'que el conteo manual no incluye alcanzaba el carril de los que salen del arco: 92 '
          'vehículos del movimiento principal quedaban registrados como si fueran a ese camino.'),
        P('Qué se cambió', 'h2'),
        P('Antes, el sistema decidía a dónde iba cada vehículo <b>solo por las zonas que pisaba</b>, '
          'y exigía verlo entrar y salir. Ahora decide por la <b>forma de su recorrido</b>: compara '
          'el camino que hizo cada vehículo con los caminos típicos de cada movimiento, y si se vio '
          'lo suficiente, sabe a dónde iba aunque algo lo haya tapado. Es el método que usaron los '
          'mejores equipos de la competencia internacional AI City Challenge 2021, también sobre '
          'equipos Jetson. Si del vehículo se vio muy poco, <b>queda "sin decidir" y no se '
          'inventa</b>.'),
        KeepTogether([
            P('Gráfica 3. Vehículos por cuarto de hora', 'h2'),
            figura(grafica_altozano_cuartos()),
            caja('Cómo leer esta gráfica',
                 'Para cada cuarto de hora hay tres barras: <b>gris</b>, lo que contó la persona; '
                 '<b>naranja</b>, lo que daba el sistema antes; <b>azul</b>, lo que da ahora. Lo '
                 'que importa es que la azul quede a la altura de la gris. Antes el sistema se '
                 'quedaba muy corto (157 de 193 y 189 de 275); ahora queda cerca en los dos cuartos. '
                 'El video de las 7:15 empieza a las 7:16:25, así que cubre el 91 % de ese cuarto; '
                 'para ese cuarto el número del manual se ajustó a esa parte.'),
        ]),
        Spacer(1, 4),
        tabla([
            ['', 'Conteo manual', 'Antes (por zonas)', 'Ahora (por recorrido)'],
            ['Total de los dos cuartos', str(d['total'][0]), f"{d['total'][1]} ({razon(d['total'][1], d['total'][0])})",
             f"<b>{d['total'][2]} ({razon(d['total'][2], d['total'][0])})</b>"],
            ['Movimientos con GEH menor a 5', '', '2 de 5', '<b>3 de 5</b>'],
        ], [5.8, 2.8, 3.8, 4.2]),
        Spacer(1, 6),
        caja('Para que la prueba fuera honesta',
             'Los "caminos típicos" con los que el sistema compara se aprendieron de <b>otros</b> '
             'videos del mismo cruce (los de 7:46 y 7:56, que no tienen conteo manual), no de los '
             'mismos que se comparan. Y en el equipo Jetson, ya con los videos reprocesados, el '
             f"cuarto de 7:30 dio <b>{d['plataforma_730']['ahora']} contra "
             f"{d['plataforma_730']['manual']}</b> (antes {d['plataforma_730']['antes']}).",
             fondo='#f3f8f3', borde=BIEN),
        KeepTogether([
            P('Gráfica 4. GEH de cada movimiento', 'h2'),
            figura(grafica_altozano_geh()),
            caja('Cómo leer esta gráfica',
                 'Cada renglón es un movimiento; entre paréntesis, cuántos vehículos lo hicieron '
                 'según el conteo manual. La barra es el <b>GEH</b>: entre más corta, más se parece al '
                 'conteo manual. Lo que queda dentro de la <b>zona verde</b> (menos de 5) se acepta. '
                 'El movimiento principal, <b>2 → 3</b>, pasó de 7.4 (no aceptable) a <b>1.6</b>. '
                 'Los movimientos <b>1 → 3</b> y <b>3 → 1</b> siguen fuera: el sistema no los '
                 'captura (ver abajo). Los de 3 → 2 y 2 → 1 pasan porque son tan pocos vehículos que '
                 'la diferencia es chica.'),
        ]),
        Spacer(1, 4),
        tabla([['Movimiento', 'Qué es', 'Manual', 'Antes', 'Ahora', 'GEH ahora', '¿Pasa?']] +
              [[f'<b>{m[0]}</b>', m[1], str(m[2]), str(m[3]), str(m[4]), f'{m[6]:.1f}',
                '<font color="%s"><b>Sí</b></font>' % BIEN if m[6] < 5 else
                '<font color="%s"><b>No</b></font>' % MAL] for m in d['movimientos']],
              [2.9, 5.0, 1.8, 1.5, 1.5, 2.0, 1.9]),
        P('Suma de los cuartos de 7:15 y 7:30. "¿Pasa?" = GEH menor a 5.', 'nota'),
        P('Lo que todavía no sale', 'h2'),
        P('Los movimientos <b>1 → 3</b> y <b>3 → 1</b> (unos 27 vehículos en la ventana) siguen en '
          'cero. Esos vehículos pasan por el camino junto al canal, al fondo de la imagen, donde se '
          'ven de unos 15 píxeles, y dan la vuelta en el mismo lugar que los del arco. Es un límite '
          'de la cámara. Por eso el criterio de la empresa (85 % de los movimientos con GEH menor a '
          '5) queda en 3 de 5: los que faltan son justo esos dos. En la hoja DIRECCIONAL del Excel, '
          f"de todo el estudio, {miles(d['decision']['zonas'])} vehículos se vieron entrar y salir, "
          f"{miles(d['decision']['trayectoria'])} se decidieron por la forma de su recorrido y "
          f"{miles(d['decision']['sin_decidir'])} quedaron sin decidir."),
        foto('i7_altozano_camino.png',
             'El camino del acceso 1 pasa al fondo, detrás del muro bajo, donde los vehículos se ven '
             'de unos 15 píxeles. Además, al dar la vuelta hacia la calle norte pasan por el mismo '
             'lugar que los que salen del arco, así que por su recorrido no se distinguen.'),
        Spacer(1, 10),
    ]

    # ------------------------------------------------------ otros direccionales
    story += [
        P('3. Los otros aforos direccionales', 'h1'),
        P('La empresa mandó videos de cinco aforos. Solo en uno la cámara permite un conteo '
          'direccional confiable. En los demás el problema no es el programa: es lo que la cámara '
          'alcanza a ver.'),
        tabla([
            ['Aforo', 'Resultado', 'Por qué'],
            ['<b>Entrada y salida Altozano</b>', '<font color="%s"><b>Confiable</b></font> (0.99×)' % BIEN,
             'La cámara ve los accesos; el letrero ya no afecta.'],
            ['Blvd. Independencia', '<font color="%s"><b>No confiable</b></font>' % MAL,
             'Es un paso a desnivel: el puente tapa dos accesos. Hacen falta dos cámaras, una a cada '
             'lado del puente, o una vista alta que vea las cuatro esquinas.'],
            ['Glorieta Altozano', '<font color="%s"><b>No confiable</b></font>' % MAL,
             'La cámara solo ve un tercio del tránsito: los dos movimientos más grandes pasan fuera '
             'de la imagen.'],
            ['Altozano y Blvd. Independencia', '<font color="%s"><b>No confiable</b></font>' % MAL,
             'Video de baja resolución (640×360): a lo lejos los vehículos miden 10 a 21 píxeles.'],
            ['Fraccionamientos', 'Sin comparar',
             'Los videos no cubren el horario del conteo manual.'],
        ], [4.4, 3.2, 9.0]),
        Spacer(1, 6),
        P('Para saber por qué, conviene mirar la imagen de cada cámara. En las dos primeras, cada '
          '<b>punto naranja</b> marca dónde el sistema dejó de ver a un vehículo <b>sin saber a dónde '
          'iba</b>. En una buena cámara esos puntos casi no existen, o quedan en las orillas de la '
          'imagen, por donde de verdad salen los vehículos.'),
        foto('i4_blvd_puente.png',
             'Diez minutos de video (17:04). Los vehículos se pierden en medio del cruce, a la salida de '
             'debajo del puente y en la lateral de la derecha. El puente y sus columnas tapan justo el '
             'lugar donde cada vehículo decide si sigue de frente o da vuelta a la lateral del otro '
             'lado, así que ningún ajuste permite saber a dónde fue. Además, la esquina superior '
             'derecha de la imagen la tapa el propio lente. <b>Solución: dos cámaras, una a cada lado '
             'del puente, o una más alta que vea las cuatro esquinas.</b>',
             'Blvd. Independencia: el puente tapa el cruce'),
        foto('i5_glorieta.png',
             'Diez minutos de video (7:14). Los vehículos se pierden a media imagen: detrás de los '
             'arbustos y los autos estacionados de la izquierda, y del lado derecho, donde el camino '
             'sale del cuadro. Esta cámara mira al Blvd. Altozano; la glorieta y los dos movimientos '
             'más grandes del conteo manual (los que van y vienen de Blvd. Independencia, más de 3 000 '
             'vehículos por hora) pasan fuera de la imagen. <b>Si el vehículo no aparece en el video, '
             'no hay forma de contarlo.</b>',
             'Glorieta Altozano: el cruce queda fuera del cuadro'),
        foto('i6_altozano_blvd_chico.png',
             'Los números amarillos son el alto de cada vehículo en píxeles. Este video se grabó a '
             'baja resolución (640×360), y a lo lejos los vehículos miden 10 a 21 píxeles: son manchas '
             'de pocos puntos. Solo el que va cerca (42 px) se ve con claridad. <b>Solución: grabar a '
             '1280×720 o más, como en los otros aforos.</b>',
             'Altozano y Blvd. Independencia: vehículos demasiado chicos'),
        P('Lo que sí se puede entregar según el tipo de cruce', 'h2'),
        P('• <b>Cruce plano con las calles a la vista:</b> matriz de movimientos (de dónde a dónde).<br/>'
          '• <b>Cualquier cámara que vea completa cada calle:</b> cuántos vehículos entraron y '
          'salieron por cada acceso, aunque no se sepa a dónde fueron.<br/>'
          '• <b>Paso a desnivel con una sola cámara:</b> nada confiable.'),
        Spacer(1, 10),
        P('4. Revisión del encuadre antes de procesar', 'h1'),
        P('Descubrir que una cámara no sirve contando cuesta horas de proceso. Por eso, al subir un '
          'video a la plataforma, el botón <b>"Revisar encuadre"</b> lo califica en uno o dos '
          'minutos: mide qué tan grandes y nítidos se ven los vehículos, si la imagen está quemada y '
          'si se alcanza a ver por dónde entran y salen. Dice <b>bueno, regular o no recomendable</b>, '
          'la exactitud que se puede esperar y <b>qué cambiar de la cámara</b>.'),
        P('Se probó con los aforos cuyo resultado real ya se conocía:'),
        tabla([['Video', 'Calificación', 'Qué pasó en realidad', '¿Acertó?']] +
              [[a, b, c, '<font color="%s"><b>Sí</b></font>' % BIEN if ok is True else
                ('<font color="%s"><b>No</b></font>' % MAL if ok is False else '—')]
               for a, b, c, ok in ENCUADRE],
              [5.6, 3.8, 5.2, 2.0]),
        P('Acertó en 5 de los 6 videos que se pueden verificar. <b>No detecta el caso del puente</b> '
          '(Blvd. Independencia salió "regular"): en un aforo direccional hay que confirmar a ojo que '
          'se vean completos todos los accesos. La calificación <b>avisa, no autoriza</b>.', 'nota'),
        PageBreak(),
    ]

    # ------------------------------------------------------------- qué sigue
    story += [
        P('5. Qué sigue y qué pedir', 'h1'),
        P('Lo que más ayudaría a mejorar los resultados depende de la forma de grabar, no del '
          'programa:'),
        tabla([
            ['Qué pedir', 'Para qué'],
            ['<b>Forzar el obturador rápido de la cámara de noche</b> y grabar 10 minutos',
             'Es lo único que podría recuperar las horas de noche, incluida la hora pico de las '
             '05:00 en Cd. Juárez. No cuesta nada probarlo.'],
            ['<b>El video de las 7:06 de Entrada y salida Altozano</b>',
             'Faltan esos 10 minutos: con ellos se podría comparar otro cuarto de hora completo y '
             'la validación sería más firme.'],
            ['<b>Un aforo direccional en un cruce plano</b>, con las calles a la vista',
             'Para comprobar el método nuevo en otra intersección, no solo en una.'],
            ['<b>Grabar un minuto de prueba</b> antes de cada aforo y pasarlo por "Revisar encuadre"',
             'Para no gastar un día de grabación y horas de proceso en una cámara mal puesta.'],
            ['En cruces grandes o con puente, <b>subir la cámara o poner dos</b>',
             'Con la vía llena los vehículos se tapan entre sí; y un puente esconde calles enteras.'],
        ], [7.0, 9.6]),
        Spacer(1, 12),
        P('Anexo: qué trae cada Excel', 'h1'),
        tabla([
            ['Archivo y hoja', 'Qué contiene'],
            ['<b>Aforo_Cd_Juarez_19-ago-2026.xlsx</b><br/>Hoja "TOTALES (est)"',
             'Vehículos por hora del día, en el formato de la empresa: calzada oriente (la cercana), '
             'calzada poniente (la del fondo) y ambos sentidos. <b>Trae las 24 horas, pero solo '
             'las de 07:00 a 20:00 son confiables</b>; las de la noche salen muy por debajo de lo '
             'real.'],
            ['Hoja "(EST) (15MIN)"', 'Los mismos conteos por cuarto de hora, por calzada.'],
            ['Hoja "METODO"', 'De dónde salen los datos: fechas, número de vehículos, modelo de '
             'detección y cómo se cuenta.'],
            ['<b>Aforo_direccional_Entrada_y_salida_<br/>Altozano.xlsx</b><br/>Hoja "DIRECCIONAL"',
             'Matriz de movimientos de todo el estudio (fila = por dónde entró, columna = por dónde '
             'salió), movimientos por cuarto de hora, volumen por acceso y la nota de cuántos '
             'vehículos se decidieron por su recorrido y cuántos quedaron sin decidir.'],
            ['Hoja "METODO"', 'De dónde salen los datos.'],
        ], [7.4, 9.2]),
        Spacer(1, 6),
        P('Importante al leer el Excel direccional: los nombres de las zonas son los de la cámara, '
          'no los números del croquis. <b>Arco = acceso 2</b>, <b>Izquierda y Abajo = acceso 3</b>, '
          '<b>Fondo izq = acceso 1</b>, y <b>Derecha</b> es un camino de terracería que el conteo '
          'manual no incluye. En Cd. Juárez, <b>calzada oriente es la cercana</b> a la cámara y '
          '<b>calzada poniente la del fondo</b>.', 'nota'),
    ]

    def pie(canvas, doc):
        canvas.saveState()
        canvas.setFont('DV', 7.5)
        canvas.setFillColor(gris)
        canvas.drawString(2.2 * cm, 1.2 * cm, 'Aforo vehicular con video · Informe de avance · '
                                              '17 de septiembre de 2026')
        canvas.drawRightString(letter[0] - 2.2 * cm, 1.2 * cm, f'Página {doc.page}')
        canvas.restoreState()

    temporal = DATOS / '_sin_adjuntos.pdf'
    doc = SimpleDocTemplate(str(temporal), pagesize=letter, leftMargin=2.2 * cm,
                            rightMargin=2.2 * cm, topMargin=1.8 * cm, bottomMargin=2.0 * cm,
                            title='Informe de avance: aforo vehicular con video',
                            author='Plataforma de aforo vehicular')
    doc.build(story, onFirstPage=pie, onLaterPages=pie)

    # Los Excel van adjuntos dentro del PDF.
    from pypdf import PdfReader, PdfWriter
    lector = PdfReader(str(temporal))
    escritor = PdfWriter()
    escritor.append(lector)
    for origen, nombre in EXCELS:
        escritor.add_attachment(nombre, origen.read_bytes())
    escritor.add_metadata({'/Title': 'Informe de avance: aforo vehicular con video'})
    with open(SALIDA, 'wb') as fh:
        escritor.write(fh)
    temporal.unlink()
    print(SALIDA, len(lector.pages), 'páginas')


if __name__ == '__main__':
    construir()
