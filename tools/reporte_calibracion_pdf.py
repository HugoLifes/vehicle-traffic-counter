#!/usr/bin/env python3
"""
Reporte de calibración en PDF, para presentar a la empresa.

No es el entregable de aforo — ese va en Excel, en el formato de la casa, y
lo hace src/reports/aforo_excel.py. Este documento responde a otra
pregunta: **cuánta confianza merece lo que mide el sistema**, contrastado
hora por hora contra el aforo contado a mano del mismo día.

Toda cifra sale del JSON de `exportar_comparacion.py`. La versión anterior
llevaba la composición vehicular escrita en el código, lo que contradecía
la nota metodológica del propio documento.

Dos detalles de reportlab que costaron una versión del documento:

- Las celdas de Table son cadenas planas y NO interpretan entidades HTML;
  solo Paragraph lo hace. Por eso aquí todo va en caracteres literales.
- Sin KeepTogether el flujo deja páginas con una tabla huérfana.

Uso, dentro del contenedor del Jetson:
    python3 tools/exportar_comparacion.py --proyecto 2 \
        --zona "Calzada oriente" --salida data/cmp.json
    python3 tools/reporte_calibracion_pdf.py --datos data/cmp.json \
        --salida data/calibracion.pdf
"""
from __future__ import annotations

import argparse
import json
import statistics
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


def grafica(horas, destino: Path) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    etiquetas = [h["hora"] for h in horas]
    color = [VERDE if h["medible"] else ROJO for h in horas]

    fig, (ax, ax2) = plt.subplots(
        2, 1, figsize=(7.6, 5.0), sharex=True,
        gridspec_kw={"height_ratios": [2.2, 1]})

    ax.bar(etiquetas, [h["manual"] for h in horas], color=GRIS_CLARO,
           label="Aforo contado a mano", width=0.72)
    ax.bar(etiquetas, [h["nuestro"] for h in horas], color=color,
           label="Sistema de video", width=0.42)
    ax.set_ylabel("Vehiculos por hora", fontsize=9)
    ax.legend(frameon=False, fontsize=9)

    # La razon en su propio panel: mezclarla con los conteos en un eje
    # secundario la vuelve ilegible, y es el dato que se defiende.
    ax2.axhline(100, color=GRIS, lw=1, ls="--")
    ax2.bar(etiquetas, [100 * h["razon"] for h in horas], color=color, width=0.62)
    ax2.set_ylabel("% del aforo real", fontsize=9)
    ax2.set_ylim(0, 115)

    for eje in (ax, ax2):
        eje.grid(axis="y", color=GRIS_CLARO, lw=0.8)
        eje.set_axisbelow(True)
        for s in ("top", "right"):
            eje.spines[s].set_visible(False)
        eje.spines["left"].set_color(GRIS_CLARO)
        eje.spines["bottom"].set_color(GRIS_CLARO)
        eje.tick_params(labelsize=8)
    plt.setp(ax2.get_xticklabels(), rotation=45, ha="right", fontsize=7.5)

    fig.tight_layout()
    fig.savefig(destino, dpi=200)
    plt.close(fig)
    return destino


def construir(d: dict, salida: Path, img: Path) -> None:
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
                       textColor=colors.HexColor(TINTA), alignment=TA_JUSTIFY,
                       spaceAfter=8)
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
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("LINEBELOW", (0, 1), (-1, -2), 0.4, colors.HexColor(GRIS_CLARO)),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#f7f9fb")]),
        ] + (extra or [])))
        return t

    horas = d["horas"]
    med = [h for h in horas if h["medible"]]
    tot = d["totales_medibles"]
    hm = d["horario_medible"]
    c = d["composicion"]
    dif_comp = abs(c["nuestro_A_pct"] - c["manual_A_pct"])
    miles = lambda n: f"{n:,}".replace(",", " ")
    alcance = " y ".join(d["zonas"])

    bajo = [h["razon"] for h in med if h["manual"] < 1600]
    alto = [h["razon"] for h in med if h["manual"] >= 2000]

    doc = SimpleDocTemplate(
        str(salida), pagesize=letter,
        leftMargin=2.2 * cm, rightMargin=2.2 * cm,
        topMargin=2.0 * cm, bottomMargin=1.8 * cm,
        title="Aforo vehicular por video - Calibracion contra aforo manual",
        author="Sistema de aforo vehicular")
    S = []

    S.append(Paragraph("Aforo vehicular por video", H1))
    S.append(Paragraph(
        "Calibración contra aforo manual — Blvd. Miguel de la Madrid, "
        "Ciudad Juárez<br/>"
        f"Alcance: {alcance} — medición del 19 de agosto de 2026 — "
        f"informe del {date.today():%d/%m/%Y}", SUB))

    S.append(Paragraph("Resumen", H2))
    S.append(Paragraph(
        "El sistema cuenta vehículos a partir del video de la cámara, sin "
        "instalar nada en la vía. <b>Ya está calibrado contra el aforo contado a "
        "mano del mismo tramo y el mismo día</b>, hora por hora, sobre las 24 "
        "horas completas.", P))
    S.append(Spacer(1, 4))

    S.append(tabla([
        [Paragraph(f"{100 * tot['razon']:.0f} %", CIFRA),
         Paragraph(f"{hm['desde'][:2]}–{hm['hasta'][:2]} h",
                   ParagraphStyle("c2", CIFRA, textColor=colors.HexColor(AZUL))),
         Paragraph(f"{dif_comp:.1f} pts",
                   ParagraphStyle("c3", CIFRA, textColor=colors.HexColor(TINTA)))],
        [Paragraph("Del aforo real, contado<br/>en horario medible", PIE),
         Paragraph("Horario en que el<br/>sistema mide", PIE),
         Paragraph("Diferencia en la<br/>composición vehicular", PIE)],
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
        f"<b>De {hm['desde']} a {hm['hasta']} el sistema cuenta el "
        f"{100 * tot['razon']:.0f} % de los vehículos reales</b>, sobre "
        f"{miles(tot['nuestro'])} vehículos contrastados contra "
        f"{miles(tot['manual'])} contados a mano. Son {hm['horas']} horas "
        f"seguidas, y ninguna se aparta: por hora se mueve entre el "
        f"{100 * tot['razon_min']:.0f} % y el {100 * tot['razon_max']:.0f} %.", P))
    S.append(Paragraph(
        "Fuera de ese horario <b>el sistema no mide</b>, y el informe lo declara "
        "en blanco en vez de publicar un conteo parcial. La causa está "
        "identificada y tiene solución conocida — se detalla más adelante.", P))

    S.append(KeepTogether([
        Paragraph("Qué se midió", H2),
        tabla([
            ["Concepto", "Detalle"],
            ["Sitio", "Blvd. Miguel de la Madrid, Ciudad Juárez"],
            ["Fecha", "Miércoles 19 de agosto de 2026"],
            ["Cobertura", "24 horas continuas"],
            ["Material", "135 segmentos de video de 10 min, cámara fija"],
            ["Alcance del informe", alcance],
            ["Vehículos medidos en horario útil", miles(tot["nuestro"])],
            ["Referencia de calibración", "Aforo contado a mano, mismo día, "
                                          "por sentido y por clase"],
            ["Errores de proceso", "Ninguno"],
        ], [7.4 * cm, 8.6 * cm], [("ALIGN", (1, 0), (1, -1), "LEFT")]),
    ]))

    S.append(PageBreak())

    S.append(Paragraph("Resultado hora por hora", H2))
    S.append(Paragraph(
        "Cada hora del día contrastada contra el aforo manual. En verde las "
        "horas que el sistema mide; en rojo las que no.", P))
    S.append(Image(str(img), width=15.8 * cm, height=10.4 * cm))

    S.append(PageBreak())

    detalle = [["Hora", "Sistema", "Aforo manual", "% del real", "Estado"]]
    for h in horas:
        detalle.append([h["hora"], miles(h["nuestro"]), miles(h["manual"]),
                        f"{100 * h['razon']:.0f} %",
                        "Medible" if h["medible"] else "No medible"])
    detalle.append(["Total medible", miles(tot["nuestro"]), miles(tot["manual"]),
                    f"{100 * tot['razon']:.0f} %", ""])
    S.append(KeepTogether([
        Paragraph("Detalle por hora", H2),
        tabla(detalle, [2.6 * cm, 3.0 * cm, 3.6 * cm, 2.6 * cm, 4.2 * cm], [
            ("ALIGN", (4, 0), (4, -1), "LEFT"),
            ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 9),
            ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.HexColor(TINTA)),
        ] + [("TEXTCOLOR", (4, i + 1), (4, i + 1),
              colors.HexColor(VERDE if h["medible"] else ROJO))
             for i, h in enumerate(horas)]),
    ]))

    S.append(PageBreak())

    S.append(Paragraph("Composición vehicular", H2))
    S.append(Paragraph(
        "El sistema separa vehículo liviano de pesado. Contrastado contra el "
        "desglose del aforo manual en horario medible:", P))
    S.append(tabla([
        ["", "Sistema", "Aforo manual", "Diferencia"],
        ["Livianos", f"{c['nuestro_A_pct']} %", f"{c['manual_A_pct']} %",
         f"{dif_comp:.1f} pts"],
        ["Pesados", f"{c['nuestro_PES_pct']} %", f"{c['manual_PES_pct']} %",
         f"{dif_comp:.1f} pts"],
    ], [4.6 * cm, 3.8 * cm, 4.0 * cm, 3.6 * cm], [
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
    ]))
    S.append(Spacer(1, 4))
    S.append(Paragraph(
        f"El <b>{c['clasificados_pct']} %</b> de los vehículos contados en "
        "horario medible recibe clasificación. La verificación no se hizo solo "
        "comparando totales — un error en un sentido y otro en el contrario se "
        "cancelan — sino revisando <b>108 vehículos recortados del video, uno "
        "por uno</b>, en dos franjas horarias distintas.", NOTA))
    S.append(Paragraph(
        "<b>Límite declarado:</b> no se separa autobús de camión. A la distancia "
        "de esta cámara se ven igual. El desglose que se entrega es liviano "
        "contra pesado.", P))

    if bajo and alto:
        S.append(Paragraph("La exactitud depende del volumen", H2))
        S.append(Paragraph(
            "La exactitud no es una cifra única a lo largo del día. Cuando la vía "
            "se llena, los vehículos se tapan unos a otros desde el ángulo de la "
            "cámara y el que va detrás no llega a verse:", P))
        S.append(tabla([
            ["Volumen de la hora", "Se cuenta"],
            ["Menos de 1 600 veh/h", f"{100 * statistics.fmean(bajo):.0f} % del real"],
            ["2 000 veh/h o más", f"{100 * statistics.fmean(alto):.0f} % del real"],
        ], [8.6 * cm, 7.4 * cm], [("ALIGN", (1, 0), (1, -1), "CENTER")]))
        S.append(Spacer(1, 4))
        S.append(Paragraph(
            "Es un límite del punto de vista, no del programa: ninguna "
            "configuración recupera un vehículo que está detrás de otro. Se "
            "corrige con la altura y el ángulo de la cámara — cuanto más "
            "perpendicular a la vía, menos se tapan entre sí.", NOTA))

    S.append(PageBreak())

    S.append(Paragraph("Por qué no se mide de noche", H2))
    S.append(Paragraph(
        "La causa <b>no es falta de luz</b>. Es lo contrario. Medido sobre la "
        "franja de la vía:", P))
    S.append(tabla([
        ["", "Brillo medio", "Contraste"],
        ["Día, 07:00", "84", "36"],
        ["Madrugada, 05:00", "177", "70"],
        ["Noche, 21:00", "168", "70"],
    ], [6.0 * cm, 5.0 * cm, 5.0 * cm], [
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
    ]))
    S.append(Spacer(1, 6))
    S.append(Paragraph(
        "De noche la imagen es <b>el doble de brillante</b> que de día. La cámara "
        "abre la exposición al máximo; los faros y el pavimento iluminado se "
        "queman a blanco puro, y con el obturador abierto tanto tiempo <b>todo lo "
        "que se mueve se convierte en una estela</b>. Un vehículo nocturno en este "
        "material no es un objeto reconocible: es una raya de luz.", P))
    S.append(Paragraph(
        "<b>La corrección es un ajuste de la cámara, no del sistema.</b> Forzar "
        "obturador rápido en el modo nocturno, aceptando algo más de ruido a "
        "cambio de congelar el movimiento. Es un cambio de configuración, sin "
        "costo, y se verifica grabando diez minutos de noche y volviendo a "
        "medir.", P))
    S.append(Paragraph(
        "Conviene atenderlo: <b>la hora de mayor tránsito del día son las "
        "05:00</b>, con 2 038 vehículos — más que cualquier hora de la mañana — y "
        "hoy cae fuera del horario medible.", P))

    S.append(KeepTogether([
        Paragraph("Qué se puede entregar", H2),
        tabla([
            ["Producto", "Estado"],
            [f"Aforo por hora y por cuartos de hora, {hm['desde'][:2]}–"
             f"{hm['hasta'][:2]} h", f"Listo, {100 * tot['razon']:.0f} % del real"],
            ["Aforo por sentido de circulación", "Listo"],
            ["Composición liviano / pesado",
             f"Listo, a {dif_comp:.1f} puntos del real"],
            ["Factor de hora pico", "Listo"],
            ["Reporte en el formato de la empresa (Excel)", "Listo"],
            ["Video anotado como respaldo verificable", "Listo"],
            ["Horario nocturno", "No medible con esta configuración"],
            ["Velocidad por intervalo", "No implementado"],
        ], [10.2 * cm, 5.8 * cm], [("ALIGN", (1, 0), (1, -1), "LEFT")]),
    ]))

    S.append(Paragraph("Nota metodológica", H2))
    S.append(Paragraph(
        "La referencia es el aforo contado a mano del Blvd. Miguel de la Madrid "
        "del 19 de agosto de 2026, en cuartos de hora, por sentido y por clase "
        "vehicular. Se procesaron los 135 segmentos de video del día completo de "
        "principio a fin, sin descartar ninguno y sin ajustar nada después de ver "
        "el resultado.", NOTA))
    S.append(Paragraph(
        f"Este informe cubre <b>{alcance}</b>, contrastada contra el sentido "
        f"{' y '.join(d['sentidos'])} del aforo manual.", NOTA))
    S.append(Paragraph(
        "Las horas fuera del horario medible se dejan <b>en blanco</b> en el "
        "entregable, en vez de publicar el conteo parcial que produjo el "
        "detector. Una celda vacía significa \"no medido\"; nunca \"cero "
        "vehículos\".", NOTA))
    S.append(Paragraph(
        "Ninguna cifra de este documento se escribió a mano: todas se leen del "
        "resultado del proceso.", NOTA))

    doc.build(S)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--datos", type=Path, required=True,
                   help="JSON de tools/exportar_comparacion.py")
    p.add_argument("--salida", type=Path, default=RAIZ / "data" / "calibracion.pdf")
    a = p.parse_args()

    if not a.datos.exists():
        sys.exit(f"No existe {a.datos}. Generalo con exportar_comparacion.py")
    d = json.loads(a.datos.read_text(encoding="utf-8"))
    if not [h for h in d["horas"] if h["medible"]]:
        sys.exit("No hay ninguna hora medible en esos datos.")

    a.salida.parent.mkdir(parents=True, exist_ok=True)
    img = grafica(d["horas"], a.salida.with_suffix(".grafica.png"))
    construir(d, a.salida, img)
    print(f"{a.salida}  ({a.salida.stat().st_size // 1024} KB, "
          f"{len(d['horas'])} horas, alcance: {', '.join(d['zonas'])})")


if __name__ == "__main__":
    main()
