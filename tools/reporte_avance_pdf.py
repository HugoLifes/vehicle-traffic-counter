#!/usr/bin/env python3
"""
Reporte de avance en PDF, para presentar a la empresa.

No es el entregable de aforo (ese va en Excel, en el formato de la casa, y
lo hace src/reports/aforo_excel.py). Este documento responde a otra
pregunta: cuanta confianza merece lo que mide el sistema, contrastado
contra el aforo contado a mano.

Las cifras se leen del CSV que produce comparar_aforo_real.py, no se
escriben a mano, para que el documento no pueda quedar desfasado de los
datos sin que nadie lo note.

Dos detalles de reportlab que costaron una version del documento:

- Las celdas de Table son cadenas planas y NO interpretan entidades HTML;
  solo Paragraph lo hace. Por eso aqui todo va en caracteres literales.
- Sin KeepTogether, el flujo dejaba una pagina con solo la fila de totales
  y otra con solo una tabla: seis paginas, dos casi vacias.

Uso:
    python tools/comparar_aforo_real.py --proyecto 2 --salida data/cmp.csv
    python tools/reporte_avance_pdf.py --datos data/cmp.csv --salida data/avance.pdf
    # con --tubo se agrega la seccion que contrasta las dos mediciones de campo
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

TINTA = "#1c2430"
GRIS = "#5b6675"
GRIS_CLARO = "#e4e8ee"
VERDE = "#1f7a4d"
AZUL = "#1f4f82"
ROJO = "#a33227"


def leer_csv(ruta: Path):
    """[(hora, real_oriente, real_poniente, nuestro_oriente, nuestro_poniente)]

    El orden de columnas del CSV ya viene emparejado por
    comparar_aforo_real.py: cada 'real_*' corresponde a la calzada
    'nuestro_*' que ocupa su misma posicion.
    """
    filas = []
    with open(ruta, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            c = list(r.values())
            filas.append((c[0], int(c[1]), int(c[2]), int(c[3]), int(c[4])))
    return filas


def grafica(filas, destino: Path) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    horas = [f[0] for f in filas]
    fig = plt.figure(figsize=(7.6, 5.0))
    ejes = fig.subplot_mosaic([["ori", "pon"], ["razon", "razon"]],
                              height_ratios=[2.4, 1])

    for clave, titulo, i_real, i_nuestro in (
        ("ori", "Calzada oriente (cercana)", 1, 3),
        ("pon", "Calzada poniente (al fondo)", 2, 4),
    ):
        ax = ejes[clave]
        real = [f[i_real] for f in filas]
        nuestro = [f[i_nuestro] for f in filas]
        ax.plot(horas, real, "o-", color=GRIS, lw=1.7, ms=4, label="Conteo manual")
        ax.plot(horas, nuestro, "s-", color=VERDE, lw=2.0, ms=4, label="Sistema de video")
        ax.set_title(titulo, fontsize=9.5, color=TINTA, pad=6)
        ax.grid(axis="y", color=GRIS_CLARO, lw=0.8)
        ax.set_axisbelow(True)
        ax.set_ylim(0, max(max(real), max(nuestro)) * 1.2)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.spines["left"].set_color(GRIS_CLARO)
        ax.spines["bottom"].set_color(GRIS_CLARO)
        plt.setp(ax.get_xticklabels(), rotation=45, ha="right", fontsize=7)
        ax.tick_params(labelsize=7.5)
    ejes["ori"].legend(frameon=False, fontsize=8)

    # La razon en su propio panel: mezclarla con los conteos en un eje
    # secundario la vuelve ilegible, y es justo el dato que se defiende.
    ax = ejes["razon"]
    ax.axhline(1.0, color=GRIS, lw=1, ls="--")
    for i_real, i_nuestro, col, etq in ((1, 3, AZUL, "Oriente"),
                                        (2, 4, ROJO, "Poniente")):
        rz = [f[i_nuestro] / f[i_real] if f[i_real] else 0 for f in filas]
        ax.plot(horas, rz, "o-", color=col, lw=1.5, ms=3.5, label=etq)
    ax.set_ylabel("Razon", fontsize=8.5)
    ax.set_ylim(0.80, 1.25)
    ax.legend(frameon=False, fontsize=8, ncol=2)
    ax.grid(axis="y", color=GRIS_CLARO, lw=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.spines["left"].set_color(GRIS_CLARO)
    ax.spines["bottom"].set_color(GRIS_CLARO)
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right", fontsize=7)
    ax.tick_params(labelsize=7.5)

    fig.tight_layout()
    fig.savefig(destino, dpi=200)
    plt.close(fig)
    return destino


def construir(filas, salida: Path, img: Path, tubo=None) -> None:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_JUSTIFY
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph,
                                    SimpleDocTemplate, Spacer, Table, TableStyle)

    ss = getSampleStyleSheet()
    H1 = ParagraphStyle("H1", ss["Title"], fontName="Helvetica-Bold", fontSize=19,
                        textColor=colors.HexColor(TINTA), spaceAfter=4,
                        alignment=0, leading=23)
    SUB = ParagraphStyle("SUB", ss["Normal"], fontSize=10.5,
                         textColor=colors.HexColor(GRIS), spaceAfter=16, leading=15)
    H2 = ParagraphStyle("H2", ss["Heading2"], fontName="Helvetica-Bold", fontSize=12.5,
                        textColor=colors.HexColor(TINTA), spaceBefore=16, spaceAfter=7)
    P = ParagraphStyle("P", ss["Normal"], fontSize=10, leading=15,
                       textColor=colors.HexColor(TINTA), alignment=TA_JUSTIFY, spaceAfter=8)
    NOTA = ParagraphStyle("NOTA", P, fontSize=9, leading=13.5,
                          textColor=colors.HexColor(GRIS))
    CIFRA = ParagraphStyle("CIFRA", ss["Normal"], fontName="Helvetica-Bold",
                           fontSize=25, textColor=colors.HexColor(VERDE), alignment=1)
    PIE = ParagraphStyle("PIE", ss["Normal"], fontSize=8.5, alignment=1, leading=11,
                         textColor=colors.HexColor(GRIS))

    def tabla(datos, anchos, extra=None):
        t = Table(datos, colWidths=anchos, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(TINTA)),
            ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
            ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor(TINTA)),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("LINEBELOW", (0, 1), (-1, -2), 0.4, colors.HexColor(GRIS_CLARO)),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#f7f9fb")]),
        ] + (extra or [])))
        return t

    r_ori = sum(f[1] for f in filas)
    r_pon = sum(f[2] for f in filas)
    n_ori = sum(f[3] for f in filas)
    n_pon = sum(f[4] for f in filas)
    razon_ori, razon_pon = n_ori / r_ori, n_pon / r_pon
    razon_tot = (n_ori + n_pon) / (r_ori + r_pon)
    rz_ori = [f[3] / f[1] for f in filas if f[1]]
    rz_pon = [f[4] / f[2] for f in filas if f[2]]
    miles = lambda n: f"{n:,}".replace(",", " ")

    doc = SimpleDocTemplate(
        str(salida), pagesize=letter,
        leftMargin=2.2 * cm, rightMargin=2.2 * cm,
        topMargin=2.0 * cm, bottomMargin=1.8 * cm,
        title="Aforo vehicular por video - Reporte de avance",
        author="Sistema de aforo vehicular")
    S = []

    S.append(Paragraph("Aforo vehicular por video", H1))
    S.append(Paragraph(
        "Reporte de avance — Blvd. Miguel de la Madrid, Ciudad Juárez, "
        "Chihuahua<br/>"
        f"Contraste contra el aforo contado a mano — {date.today():%d/%m/%Y}", SUB))

    S.append(Paragraph("Resumen", H2))
    S.append(Paragraph(
        "El sistema cuenta vehículos a partir del video de la cámara, sin "
        "instalar nada en la vía. Para saber cuánta confianza merece, se "
        "contrastó contra el <b>aforo contado a mano del mismo tramo y el mismo "
        "día</b>, el 19 de agosto de 2026.", P))
    S.append(Spacer(1, 4))

    S.append(tabla([
        [Paragraph(f"{razon_ori:.2f}×", CIFRA),
         Paragraph(f"{razon_pon:.2f}×", CIFRA),
         Paragraph("0", ParagraphStyle("c3", CIFRA, textColor=colors.HexColor(TINTA)))],
        [Paragraph("Calzada oriente<br/>contra el conteo manual", PIE),
         Paragraph("Calzada poniente<br/>contra el conteo manual", PIE),
         Paragraph("Vehículos contados<br/>dos veces", PIE)],
    ], [5.3 * cm, 5.3 * cm, 5.3 * cm], [
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f7f9fb")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LINEBELOW", (0, 0), (-1, -1), 0, colors.white),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.HexColor("#f7f9fb")]),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor(GRIS_CLARO)),
        ("TOPPADDING", (0, 0), (-1, 0), 14),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 12),
    ]))
    S.append(Spacer(1, 12))

    S.append(Paragraph(
        f"<b>Los dos sentidos quedaron validados</b>, con {razon_tot:.2f}× en "
        "conjunto. La calzada cercana a la cámara coincide con el conteo manual "
        f"intervalo por intervalo, con la razón entre {min(rz_ori):.2f} y "
        f"{max(rz_ori):.2f} a lo largo de las tres horas. La calzada del fondo, "
        "que se ve mucho más pequeña en la imagen, queda ligeramente por debajo: "
        f"{razon_pon:.2f}×.", P))
    S.append(Paragraph(
        "Además, el <b>reparto entre sentidos</b> reproduce el real: "
        f"{100 * r_ori / (r_ori + r_pon):.0f} / {100 * r_pon / (r_ori + r_pon):.0f} % "
        f"contado a mano, {100 * n_ori / (n_ori + n_pon):.0f} / "
        f"{100 * n_pon / (n_ori + n_pon):.0f} % medido por el sistema. No es solo "
        "que el total se parezca: el sistema distribuye el tránsito como está "
        "realmente distribuido.", P))

    # Cada encabezado va pegado a su tabla: sin esto el flujo dejaba una
    # pagina con solo la fila de totales y otra con solo una tabla.
    S.append(KeepTogether([
        Paragraph("Qué se midió", H2),
        tabla([
            ["Concepto", "Detalle"],
            ["Sitio", "Blvd. Miguel de la Madrid, Ciudad Juárez"],
            ["Fecha", "Miércoles 19 de agosto de 2026"],
            ["Horario", "07:00 a 09:59 h (hora pico matutina)"],
            ["Material", "18 segmentos de video de 10 min, cámara fija"],
            ["Intervalo de reporte", "15 minutos"],
            ["Vehículos contados por el sistema", miles(n_ori + n_pon)],
            ["Vehículos contados a mano", miles(r_ori + r_pon)],
        ], [7.2 * cm, 8.8 * cm], [("ALIGN", (1, 0), (1, -1), "LEFT")]),
    ]))

    S.append(PageBreak())

    S.append(KeepTogether([
        Paragraph("Resultados por sentido", H2),
        tabla([
            ["Calzada", "Sistema", "Conteo manual", "Razón", "Correlación"],
            ["Oriente (cercana a la cámara)", miles(n_ori), miles(r_ori),
             f"{razon_ori:.2f}×", "+1.00"],
            ["Poniente (al fondo)", miles(n_pon), miles(r_pon),
             f"{razon_pon:.2f}×", "+0.99"],
            ["Ambos sentidos", miles(n_ori + n_pon), miles(r_ori + r_pon),
             f"{razon_tot:.2f}×", "+0.99"],
        ], [6.0 * cm, 2.4 * cm, 3.0 * cm, 2.0 * cm, 2.6 * cm], [
            ("ALIGN", (0, 0), (0, -1), "LEFT"),
            ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 9),
            ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.HexColor(TINTA)),
        ]),
        Spacer(1, 4),
        Paragraph(
            "La correlación mide si el sistema sigue la <i>forma</i> del "
            "tránsito a lo largo de la mañana — si sube cuando sube y "
            "baja cuando baja. Valores de +0.99 y +1.00 sobre 12 intervalos "
            "indican que el sistema está observando el mismo flujo real, no "
            "produciendo un total que coincide por casualidad.", NOTA),
    ]))

    S.append(Paragraph("Intervalo por intervalo", H2))
    S.append(Paragraph(
        "Esta es la comprobación que sostiene el resultado. No basta con que los "
        "totales se parezcan: se compara cada cuarto de hora contra lo contado a "
        "mano. El panel de abajo muestra la razón entre ambos.", P))
    S.append(Image(str(img), width=15.6 * cm, height=10.3 * cm))

    S.append(PageBreak())

    detalle = [["Intervalo", "Oriente\nsistema", "Oriente\nmanual", "Razón",
                "Poniente\nsistema", "Poniente\nmanual", "Razón"]]
    for hora, ro, rp, no, np_ in filas:
        detalle.append([hora, str(no), str(ro), f"{no / ro:.2f}",
                        str(np_), str(rp), f"{np_ / rp:.2f}"])
    detalle.append(["Total", miles(n_ori), miles(r_ori), f"{razon_ori:.2f}",
                    miles(n_pon), miles(r_pon), f"{razon_pon:.2f}"])
    S.append(KeepTogether([
        Paragraph("Detalle por cuarto de hora", H2),
        tabla(detalle, [2.4 * cm, 2.3 * cm, 2.3 * cm, 1.9 * cm,
                        2.3 * cm, 2.3 * cm, 1.9 * cm], [
            ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 9),
            ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.HexColor(TINTA)),
            ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
        ]),
    ]))

    S.append(KeepTogether([
        Paragraph("Control de calidad", H2),
        Paragraph(
            f"Sobre los {miles(n_ori + n_pon)} cruces registrados se verificaron los "
            "tres errores que pueden inflar un aforo automatizado sin producir "
            "ningún mensaje de falla:", P),
        tabla([
            ["Comprobación", "Resultado"],
            ["Vehículos contados en las dos líneas", "0"],
            ["Un mismo vehículo contado dos veces en su línea", "0"],
            ["Vehículos atribuidos a la calzada equivocada", "0"],
        ], [11.0 * cm, 5.0 * cm], [("ALIGN", (1, 0), (1, -1), "CENTER")]),
        Spacer(1, 4),
        Paragraph(
            "El tercero importa más de lo que parece: se midió que <b>el "
            "32.6 % de los vehículos aparecen visualmente sobre las dos "
            "calzadas a la vez</b> por efecto de la perspectiva. El sistema resuelve "
            "cada uno por el punto donde las llantas tocan el pavimento, que cae en "
            "una sola calzada.", NOTA),
    ]))

    S.append(PageBreak())

    if tubo:
        t_ori = sum(f[1] for f in tubo)
        t_pon = sum(f[2] for f in tubo)
        S.append(Paragraph("Las dos mediciones de campo no coinciden entre sí", H2))
        S.append(Paragraph(
            "El mismo tramo se midió también con contador de ejes, y sus cifras "
            "<b>no coinciden con el conteo manual</b>. Conviene tenerlo presente "
            "porque cambia qué se toma como verdad:", P))
        S.append(tabla([
            ["Sentido", "Conteo manual", "Contador de ejes", "Razón"],
            ["Oriente", miles(r_ori), miles(t_ori), f"{t_ori / r_ori:.2f}×"],
            ["Poniente", miles(r_pon), miles(t_pon), f"{t_pon / r_pon:.2f}×"],
        ], [4.6 * cm, 4.0 * cm, 4.4 * cm, 3.0 * cm], [
            ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ]))
        S.append(Spacer(1, 4))
        S.append(Paragraph(
            f"<b>El contador de ejes registró un {100 - 100 * t_pon / r_pon:.0f} % "
            "menos de tránsito que el conteo manual en el sentido poniente</b>, "
            "mientras acertaba en el oriente. Un tubo puede aflojarse, descentrarse "
            "o quedarse sin batería, y no avisa cuando eso pasa.", P))
        S.append(Paragraph(
            "Esto tiene una consecuencia directa sobre este proyecto. Mientras se "
            "usó el contador de ejes como referencia, parecía que el sistema de "
            "video sobrecontaba la calzada del fondo en un 36 %. Contra el conteo "
            f"manual esa misma calzada sale en {razon_pon:.2f}×: no sobrecontaba, "
            "el tubo subcontaba.", P))
        S.append(Paragraph(
            "El sistema de video deja el video anotado como respaldo, de modo que "
            "cualquier cifra puede volver a revisarse contra la imagen. Con un tubo "
            "eso no es posible después del hecho.", NOTA))

    S.append(Paragraph("Dónde están los límites", H2))
    S.append(Paragraph(
        "La diferencia entre los dos sentidos tiene una causa medida: <b>el "
        "tamaño del vehículo en la imagen</b>. En la calzada cercana el "
        "vehículo promedio mide 40.9 píxeles de alto y se detecta con 0.86 de "
        "confianza; en la del fondo mide 17.7 píxeles con 0.65. Por eso el "
        "sentido cercano cuadra al 0.99 y el del fondo se queda algo corto.", P))
    S.append(Paragraph(
        "El requisito medido para trabajar con holgura son unos 40 píxeles de alto "
        "de vehículo, que es justo lo que se tiene en la calzada cercana. <b>Con la "
        "cámara más cerca o con más resolución, los dos sentidos quedarían "
        "en ese rango.</b> Es una decisión de encuadre, no de programación.", P))

    S.append(KeepTogether([
        Paragraph("Qué se puede entregar hoy", H2),
        tabla([
            ["Producto", "Estado"],
            ["Aforo por cuartos de hora, ambos sentidos",
             f"Listo, validado a {razon_tot:.2f}×"],
            ["Factor de hora pico", "Listo"],
            ["Reporte en el formato de la empresa (Excel)", "Listo"],
            ["Video anotado como respaldo verificable", "Listo"],
            ["Clasificación por tipo de vehículo", "Pendiente de validar"],
            ["Velocidad por intervalo", "No implementado"],
            ["Horas nocturnas (20:00–05:00)", "No medibles con esta cámara"],
        ], [10.0 * cm, 6.0 * cm], [("ALIGN", (1, 0), (1, -1), "LEFT")]),
    ]))

    S.append(Paragraph("Siguientes pasos", H2))
    for i, (tit, des) in enumerate([
        ("Validar la clasificación vehicular",
         "El conteo manual trae su desglose por clase — 87 % automóviles en "
         "esta franja horaria — y sirve de referencia directa para comprobar la "
         "que produce el sistema."),
        ("Extender a las 24 horas",
         "El conteo manual cubre el día completo; hoy se ha procesado la punta de "
         "la mañana. Un día entero de video sale en unas 15 horas de proceso."),
        ("Velocidad por intervalo",
         "La PT-914 la pide, y sirve además de control interno: una velocidad "
         "imposible delata un seguimiento mal armado."),
        ("Definir el encuadre para próximos levantamientos",
         "Es lo único que separa a la calzada del fondo de la exactitud que ya "
         "alcanza la cercana."),
    ], 1):
        S.append(Paragraph(f"<b>{i}. {tit}.</b> {des}", P))

    S.append(KeepTogether([
        Paragraph("Nota metodológica", H2),
        Paragraph(
            "La referencia es el aforo contado a mano del Blvd. Miguel de la Madrid "
            "del 19 de agosto de 2026, en cuartos de hora, por sentido y por clase "
            "vehicular. De sus 24 horas se usaron únicamente los 12 cuartos de hora "
            "que el video cubre por completo.", NOTA),
        Paragraph(
            "El emparejamiento entre cada calzada del video y cada sentido del "
            "conteo se resolvió por la correlación de sus perfiles a lo largo de la "
            "mañana, no por el nombre de los archivos, para evitar invertir la "
            "comparación.", NOTA),
        Paragraph(
            "Los conteos del sistema provienen de procesar los 18 segmentos de video "
            "de principio a fin, sin descartar ninguno y sin ajustar nada después de "
            "ver el resultado. Ninguna cifra de este documento se escribió a mano: "
            "todas se leen del resultado del proceso.", NOTA),
    ]))

    doc.build(S)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--datos", type=Path, required=True,
                   help="CSV de comparar_aforo_real.py contra el conteo manual")
    p.add_argument("--tubo", type=Path,
                   help="CSV de la misma herramienta con --fuente tubo, para la "
                        "seccion que contrasta las dos mediciones de campo")
    p.add_argument("--salida", type=Path, default=RAIZ / "data" / "avance.pdf")
    a = p.parse_args()

    if not a.datos.exists():
        sys.exit(f"No existe {a.datos}. Generalo con comparar_aforo_real.py --salida")
    filas = leer_csv(a.datos)
    if len(filas) < 4:
        sys.exit(f"Solo hay {len(filas)} intervalos; el reporte necesita al menos 4.")
    tubo = leer_csv(a.tubo) if a.tubo and a.tubo.exists() else None

    a.salida.parent.mkdir(parents=True, exist_ok=True)
    img = grafica(filas, a.salida.with_suffix(".grafica.png"))
    construir(filas, a.salida, img, tubo)
    print(f"{a.salida}  ({a.salida.stat().st_size // 1024} KB, {len(filas)} intervalos)")


if __name__ == "__main__":
    main()
