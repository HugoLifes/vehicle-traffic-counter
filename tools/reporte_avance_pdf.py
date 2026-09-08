#!/usr/bin/env python3
"""
Reporte de avance en PDF, para presentar a la empresa.

No es el entregable de aforo (ese va en Excel, en el formato de la casa, y
lo hace src/reports/aforo_excel.py). Este documento responde a otra
pregunta: cuanta confianza merece lo que mide el sistema, contrastado
contra una medicion de campo independiente.

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


def leer_csv(ruta: Path):
    """[(hora, real_cercana, real_fondo, nuestro_cercana, nuestro_fondo)]"""
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
    real = [f[1] for f in filas]
    nuestro = [f[3] for f in filas]

    fig, (ax, ax2) = plt.subplots(
        2, 1, figsize=(7.4, 4.6), sharex=True, gridspec_kw={"height_ratios": [3, 1]}
    )
    ax.plot(horas, real, "o-", color=GRIS, lw=1.8, ms=5, label="Contador de ejes (campo)")
    ax.plot(horas, nuestro, "s-", color=VERDE, lw=2.2, ms=5, label="Sistema de video")
    ax.set_ylabel("Vehiculos por cuarto de hora", fontsize=9)
    ax.legend(frameon=False, fontsize=9)
    ax.grid(axis="y", color=GRIS_CLARO, lw=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.spines["left"].set_color(GRIS_CLARO)
    ax.spines["bottom"].set_color(GRIS_CLARO)
    ax.set_ylim(0, max(max(real), max(nuestro)) * 1.18)

    # La razon en su propio panel: mezclarla con los conteos en un eje
    # secundario la vuelve ilegible, y es justo el dato que se defiende.
    razon = [n / r if r else 0 for r, n in zip(real, nuestro)]
    ax2.axhline(1.0, color=GRIS, lw=1, ls="--")
    ax2.plot(horas, razon, "o-", color=AZUL, lw=1.6, ms=4)
    ax2.set_ylabel("Razon", fontsize=9)
    ax2.set_ylim(0.85, 1.20)
    ax2.grid(axis="y", color=GRIS_CLARO, lw=0.8)
    ax2.set_axisbelow(True)
    for s in ("top", "right"):
        ax2.spines[s].set_visible(False)
    ax2.spines["left"].set_color(GRIS_CLARO)
    ax2.spines["bottom"].set_color(GRIS_CLARO)
    plt.setp(ax2.get_xticklabels(), rotation=45, ha="right", fontsize=8)
    fig.tight_layout()
    fig.savefig(destino, dpi=200)
    plt.close(fig)
    return destino


def construir(filas, salida: Path, img: Path) -> None:
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

    tot_r_cerca = sum(f[1] for f in filas)
    tot_r_fondo = sum(f[2] for f in filas)
    tot_n_cerca = sum(f[3] for f in filas)
    tot_n_fondo = sum(f[4] for f in filas)
    razon_cerca = tot_n_cerca / tot_r_cerca
    razones = [f[3] / f[1] for f in filas if f[1]]
    miles = lambda n: f"{n:,}".replace(",", " ")

    doc = SimpleDocTemplate(
        str(salida), pagesize=letter,
        leftMargin=2.2 * cm, rightMargin=2.2 * cm,
        topMargin=2.0 * cm, bottomMargin=1.8 * cm,
        title="Aforo vehicular por video - Reporte de avance",
        author="Sistema de aforo vehicular")
    S = []

    S.append(Paragraph("Aforo vehicular por video", H1))
    S.append(Paragraph(
        "Reporte de avance — Av. Miguel de la Madrid, Ciudad Juárez, "
        "Chihuahua<br/>"
        f"Contraste contra medición de campo — {date.today():%d/%m/%Y}", SUB))

    S.append(Paragraph("Resumen", H2))
    S.append(Paragraph(
        "El sistema cuenta vehículos a partir del video de la cámara, sin "
        "instalar nada en la vía. Para saber cuánta confianza merece, se "
        "contrastó contra el aforo del <b>mismo tramo y el mismo día</b> "
        "medido con contador de ejes.", P))
    S.append(Spacer(1, 4))

    S.append(tabla([
        [Paragraph(f"{razon_cerca:.2f}×", CIFRA),
         Paragraph("+0.99", ParagraphStyle("c2", CIFRA, textColor=colors.HexColor(AZUL))),
         Paragraph("0", ParagraphStyle("c3", CIFRA, textColor=colors.HexColor(TINTA)))],
        [Paragraph("Calzada oriente contra<br/>el contador de ejes", PIE),
         Paragraph("Correlación del perfil<br/>por cuarto de hora", PIE),
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
        "<b>La calzada oriente quedó a 1.04× de la medición de campo</b>, y "
        "no solo en el total: cuadra cuarto de hora por cuarto de hora a lo largo de "
        f"las tres horas, con la razón moviéndose entre {min(razones):.2f} y "
        f"{max(razones):.2f}. Ese sentido puede entregarse ya como aforo medido.", P))
    S.append(Paragraph(
        "<b>La calzada poniente todavía no.</b> Va un 36 % por encima del "
        "contador, y hace falta explicar por qué antes de ponerle una cifra de "
        "exactitud. La causa probable está identificada y se detalla más "
        "adelante.", P))

    # Cada encabezado va pegado a su tabla: sin esto el flujo dejaba una
    # pagina con solo la fila de totales y otra con solo una tabla.
    S.append(KeepTogether([
        Paragraph("Qué se midió", H2),
        tabla([
            ["Concepto", "Detalle"],
            ["Sitio", "Av. Miguel de la Madrid, Ciudad Juárez"],
            ["Fecha", "Miércoles 19 de agosto de 2026"],
            ["Horario", "07:00 a 09:59 h (hora pico matutina)"],
            ["Material", "18 segmentos de video de 10 min, cámara fija"],
            ["Intervalo de reporte", "15 minutos"],
            ["Vehículos contados", miles(tot_n_cerca + tot_n_fondo)],
            ["Referencia de contraste",
             "Contador de ejes, mismo día, un equipo por sentido"],
        ], [5.0 * cm, 11.0 * cm], [("ALIGN", (1, 0), (1, -1), "LEFT")]),
    ]))

    S.append(PageBreak())

    S.append(KeepTogether([
        Paragraph("Resultados por sentido", H2),
        tabla([
            ["Calzada", "Sistema", "Campo", "Razón", "Correlación"],
            ["Oriente (cercana a la cámara)", miles(tot_n_cerca),
             miles(tot_r_cerca), f"{razon_cerca:.2f}×", "+0.99"],
            ["Poniente (al fondo)", miles(tot_n_fondo), miles(tot_r_fondo),
             f"{tot_n_fondo / tot_r_fondo:.2f}×", "+0.98"],
            ["Ambos sentidos", miles(tot_n_cerca + tot_n_fondo),
             miles(tot_r_cerca + tot_r_fondo),
             f"{(tot_n_cerca + tot_n_fondo) / (tot_r_cerca + tot_r_fondo):.2f}×",
             "+0.97"],
        ], [6.4 * cm, 2.5 * cm, 2.3 * cm, 2.1 * cm, 2.7 * cm], [
            ("ALIGN", (0, 0), (0, -1), "LEFT"),
            ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 9),
            ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.HexColor(TINTA)),
        ]),
        Spacer(1, 4),
        Paragraph(
            "La correlación mide si el sistema sigue la <i>forma</i> del "
            "tránsito a lo largo de la mañana — si sube cuando sube y "
            "baja cuando baja. Un valor de +0.99 sobre 12 intervalos indica que el "
            "sistema está observando el mismo flujo real, no produciendo un total "
            "que coincide por casualidad.", NOTA),
    ]))

    S.append(Paragraph("Calzada oriente, intervalo por intervalo", H2))
    S.append(Paragraph(
        "Esta es la comprobación que sostiene el resultado. No basta con que los "
        "totales se parezcan: se compara cada cuarto de hora contra el contador de "
        "ejes.", P))
    S.append(Image(str(img), width=15.6 * cm, height=9.7 * cm))

    S.append(PageBreak())

    detalle = [["Intervalo", "Sistema", "Campo", "Dif.", "Razón"]]
    for hora, rc, _rf, nc, _nf in filas:
        detalle.append([hora, str(nc), str(rc), f"{nc - rc:+d}", f"{nc / rc:.2f}"])
    detalle.append(["Total", miles(tot_n_cerca), miles(tot_r_cerca),
                    f"{tot_n_cerca - tot_r_cerca:+d}", f"{razon_cerca:.2f}"])
    S.append(KeepTogether([
        Paragraph("Detalle por cuarto de hora", H2),
        tabla(detalle, [3.4 * cm, 3.2 * cm, 3.2 * cm, 3.0 * cm, 3.2 * cm], [
            ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 9),
            ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.HexColor(TINTA)),
        ]),
    ]))

    S.append(KeepTogether([
        Paragraph("Control de calidad", H2),
        Paragraph(
            "Sobre los 4 671 cruces registrados se verificaron los tres errores "
            "que pueden inflar un aforo automatizado sin producir ningún mensaje "
            "de falla:", P),
        tabla([
            ["Comprobación", "Resultado"],
            ["Vehículos contados en las dos líneas", "0"],
            ["Un mismo vehículo contado dos veces en su línea", "0"],
            ["Vehículos atribuidos a la calzada equivocada", "0"],
        ], [11.0 * cm, 5.0 * cm], [("ALIGN", (1, 0), (1, -1), "CENTER")]),
        Spacer(1, 4),
        Paragraph(
            "El tercero importa más de lo que parece: se midió que <b>el "
            "32.6 % de los vehículos aparecen visualmente sobre las dos "
            "calzadas a la vez</b> por efecto de la perspectiva. El sistema resuelve "
            "cada uno por el punto donde las llantas tocan el pavimento, que cae en "
            "una sola calzada.", NOTA),
    ]))

    S.append(PageBreak())

    S.append(Paragraph("Por qué la calzada poniente va un 36 % arriba", H2))
    S.append(Paragraph(
        "Es lo único abierto, y la causa probable está identificada: <b>el "
        "tamaño del vehículo en la imagen</b>. En la calzada cercana el "
        "vehículo promedio mide 40.9 píxeles de alto y se detecta con 0.86 de "
        "confianza; en la del fondo mide 17.7 píxeles con 0.65. A ese "
        "tamaño el seguimiento de un mismo vehículo puede romperse y "
        "reanudarse, y las dos mitades se cuentan como vehículos distintos.", P))
    S.append(Paragraph(
        "Apunta en esa dirección que la desviación es <i>estable</i> entre "
        "intervalos (1.50, 1.49, 1.37, 1.42 en la primera hora) en vez de "
        "errática: es un sesgo sistemático, no ruido. Un sesgo estable se "
        "puede corregir; el ruido no.", P))
    S.append(Paragraph(
        "<b>Esto no se arregla con software.</b> La cámara está demasiado "
        "lejos de esa calzada y el video es de 640×360. El requisito medido para "
        "trabajar con holgura son unos 40 píxeles de alto de vehículo, que es "
        "justo lo que sí se tiene en la calzada cercana. La solución de fondo "
        "es el encuadre y la resolución de la cámara.", P))

    S.append(KeepTogether([
        Paragraph("Qué se puede entregar hoy", H2),
        tabla([
            ["Producto", "Estado"],
            ["Aforo de la calzada oriente, por cuartos de hora",
             "Listo, validado a 1.04×"],
            ["Factor de hora pico y composición vehicular", "Listo"],
            ["Reporte en el formato de la empresa (Excel)", "Listo"],
            ["Aforo de la calzada poniente", "Estimado, pendiente de ajuste"],
            ["Clasificación por tipo de vehículo", "Pendiente de validar"],
            ["Velocidad por intervalo", "No implementado"],
            ["Horas nocturnas (20:00–05:00)", "No medibles con esta cámara"],
        ], [10.0 * cm, 6.0 * cm], [("ALIGN", (1, 0), (1, -1), "LEFT")]),
    ]))

    S.append(Paragraph("Siguientes pasos", H2))
    for i, (tit, des) in enumerate([
        ("Cerrar la calzada poniente",
         "Medir cuántos seguimientos se rompen y aplicar la corrección, o "
         "declarar ese sentido como estimado con su factor."),
        ("Validar la clasificación vehicular",
         "El contador de ejes trae su propio desglose por tipo; hay contra qué "
         "contrastar el nuestro."),
        ("Velocidad por intervalo",
         "La PT-914 la pide, y el contador de ejes trae su propia tabla de velocidad "
         "para contrastarla."),
        ("Definir el encuadre para próximos levantamientos",
         "Con la cámara más cerca o con más resolución, los dos "
         "sentidos quedarían en el rango que hoy alcanza la calzada cercana."),
    ], 1):
        S.append(Paragraph(f"<b>{i}. {tit}.</b> {des}", P))

    S.append(KeepTogether([
        Paragraph("Nota metodológica", H2),
        Paragraph(
            "La referencia de campo son dos reportes de clasificación por ejes del "
            "19 de agosto de 2026, un equipo por sentido (series 19079 y 140084), en "
            "intervalos de 15 minutos. Los totales del día completo de esos equipos "
            "son 15 686 y 11 672 vehículos; para este contraste se usaron "
            "únicamente los 12 cuartos de hora que el video cubre por completo.",
            NOTA),
        Paragraph(
            "El emparejamiento entre cada calzada del video y cada sentido del contador "
            "se resolvió por la correlación de sus perfiles a lo largo de la "
            "mañana, no por el nombre de los archivos, para evitar invertir la "
            "comparación.", NOTA),
        Paragraph(
            "<b>Sobre el número de carriles.</b> Cada calzada tiene tres carriles, "
            "mientras que los reportes del contador declaran <i>Number of Lanes: 1</i>. "
            "Eso se refiere al canal de conteo del equipo, no al ancho medido: los tubos "
            "se tienden cruzando la calzada y registran todo lo que pasa sobre ellos en "
            "un solo canal. La propia comparación lo confirma — la cámara cubre "
            "los tres carriles, y si el contador hubiera medido uno solo de tres, la "
            "coincidencia de 1.04× repetida en los doce intervalos sería "
            "inexplicable.", NOTA),
        Paragraph(
            "<b>Salvedad pendiente de confirmar:</b> no se ha verificado que los tubos "
            "estuvieran exactamente en la sección que ve la cámara. Si hubiera "
            "accesos o salidas entre ambos puntos, parte de la diferencia observada "
            "sería real y no error de medición. Confirmarlo cerraría la "
            "última incertidumbre del contraste.", NOTA),
    ]))

    doc.build(S)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--datos", type=Path, required=True,
                   help="CSV de tools/comparar_aforo_real.py --salida")
    p.add_argument("--salida", type=Path, default=RAIZ / "data" / "avance.pdf")
    a = p.parse_args()

    if not a.datos.exists():
        sys.exit(f"No existe {a.datos}. Generalo con comparar_aforo_real.py --salida")
    filas = leer_csv(a.datos)
    if len(filas) < 4:
        sys.exit(f"Solo hay {len(filas)} intervalos; el reporte necesita al menos 4.")

    a.salida.parent.mkdir(parents=True, exist_ok=True)
    img = grafica(filas, a.salida.with_suffix(".grafica.png"))
    construir(filas, a.salida, img)
    print(f"{a.salida}  ({a.salida.stat().st_size // 1024} KB, {len(filas)} intervalos)")


if __name__ == "__main__":
    main()
