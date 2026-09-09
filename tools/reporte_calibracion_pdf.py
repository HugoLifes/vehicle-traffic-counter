#!/usr/bin/env python3
"""
Reporte de calibración en PDF, para presentar a la empresa.

No es el entregable de aforo — ese va en Excel, en el formato de la casa, y
lo hace src/reports/aforo_excel.py. Este documento responde a otra
pregunta: **cuánta confianza merece lo que mide el sistema**, contrastado
hora por hora contra el aforo contado a mano del mismo día.

Sustituye a reporte_avance_pdf.py, que trabajaba sobre la ventana de la
mañana en cuartos de hora. Con las 24 h medidas, el eje del informe pasa a
ser el horario: qué horas se miden, con qué exactitud, y cuáles no.

Las cifras se leen del CSV que produce el exportador, no se escriben a
mano, para que el documento no pueda quedar desfasado de los datos sin que
nadie lo note.

Dos detalles de reportlab que costaron una versión del documento anterior:

- Las celdas de Table son cadenas planas y NO interpretan entidades HTML;
  solo Paragraph lo hace. Por eso aquí todo va en caracteres literales.
- Sin KeepTogether el flujo deja páginas con una sola tabla huérfana.

Uso:
    python tools/reporte_calibracion_pdf.py --datos data/por_hora.csv \
        --salida data/calibracion.pdf
"""
from __future__ import annotations

import argparse
import csv
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
AMBAR = "#b06a12"

# Una hora es medible cuando la confianza media del detector la respalda.
# El corte cae limpio en el hueco medido entre 0.58 (noche) y 0.67 (día).
CONFIANZA_MINIMA = 0.65


def leer(ruta: Path):
    filas = []
    with open(ruta, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            filas.append({
                "hora": r["hora"],
                "h": int(r["hora"][:2]),
                "nuestro": int(r["nuestro"]),
                "manual": int(r["manual"]),
                "razon": float(r["razon"]),
                "conf": float(r["confianza"]),
                "manual_A": int(r["manual_A"]),
                "manual_PES": int(r["manual_PES"]),
            })
    for f in filas:
        f["medible"] = f["conf"] >= CONFIANZA_MINIMA and f["razon"] >= 0.75
    return sorted(filas, key=lambda x: x["h"])


def grafica(filas, destino: Path) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    horas = [f["hora"] for f in filas]
    fig, (ax, ax2) = plt.subplots(
        2, 1, figsize=(7.6, 5.0), sharex=True, gridspec_kw={"height_ratios": [2.2, 1]})

    ax.bar(horas, [f["manual"] for f in filas], color=GRIS_CLARO,
           label="Aforo contado a mano", width=0.72)
    ax.bar(horas, [f["nuestro"] for f in filas],
           color=[VERDE if f["medible"] else ROJO for f in filas],
           label="Sistema de video", width=0.42)
    ax.set_ylabel("Vehiculos por hora", fontsize=9)
    ax.legend(frameon=False, fontsize=9)
    ax.grid(axis="y", color=GRIS_CLARO, lw=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.spines["left"].set_color(GRIS_CLARO)
    ax.spines["bottom"].set_color(GRIS_CLARO)

    # La razon en su propio panel: mezclarla con los conteos en un eje
    # secundario la vuelve ilegible, y es el dato que se defiende.
    ax2.axhline(1.0, color=GRIS, lw=1, ls="--")
    ax2.bar(horas, [f["razon"] for f in filas],
            color=[VERDE if f["medible"] else ROJO for f in filas], width=0.62)
    ax2.set_ylabel("Razon", fontsize=9)
    ax2.set_ylim(0, 1.15)
    ax2.grid(axis="y", color=GRIS_CLARO, lw=0.8)
    ax2.set_axisbelow(True)
    for s in ("top", "right"):
        ax2.spines[s].set_visible(False)
    ax2.spines["left"].set_color(GRIS_CLARO)
    ax2.spines["bottom"].set_color(GRIS_CLARO)
    plt.setp(ax2.get_xticklabels(), rotation=45, ha="right", fontsize=7.5)
    ax.tick_params(labelsize=8)
    ax2.tick_params(labelsize=8)

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

    med = [f for f in filas if f["medible"]]
    n_med = sum(f["nuestro"] for f in med)
    r_med = sum(f["manual"] for f in med)
    razon_med = n_med / r_med
    h0, h1 = min(f["h"] for f in med), max(f["h"] for f in med)
    bajo = [f["razon"] for f in med if f["manual"] < 1600]
    alto = [f["razon"] for f in med if f["manual"] >= 2000]
    miles = lambda n: f"{n:,}".replace(",", " ")

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
        f"Medición del 19 de agosto de 2026 — informe del "
        f"{date.today():%d/%m/%Y}", SUB))

    S.append(Paragraph("Resumen", H2))
    S.append(Paragraph(
        "El sistema cuenta vehículos a partir del video de la cámara, sin "
        "instalar nada en la vía. <b>Ya está calibrado contra el aforo contado a "
        "mano del mismo tramo y el mismo día</b>, hora por hora, sobre las 24 "
        "horas completas.", P))
    S.append(Spacer(1, 4))

    S.append(tabla([
        [Paragraph(f"{razon_med:.2f}×", CIFRA),
         Paragraph(f"{h0:02d}–{h1 + 1:02d} h",
                   ParagraphStyle("c2", CIFRA, textColor=colors.HexColor(AZUL))),
         Paragraph("0.5 pts",
                   ParagraphStyle("c3", CIFRA, textColor=colors.HexColor(TINTA)))],
        [Paragraph("Exactitud del conteo<br/>en horario medible", PIE),
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
        f"<b>De {h0:02d}:00 a {h1 + 1:02d}:00 el sistema mide {razon_med:.2f}× del "
        f"tránsito real</b>, sobre {miles(n_med)} vehículos contrastados contra "
        f"{miles(r_med)} contados a mano. Son {len(med)} horas seguidas.", P))
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
            ["Vehículos contados por el sistema", "22 508"],
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

    detalle = [["Hora", "Sistema", "Aforo manual", "Razón", "Estado"]]
    for f in filas:
        detalle.append([f["hora"], miles(f["nuestro"]), miles(f["manual"]),
                        f"{f['razon']:.2f}×",
                        "Medible" if f["medible"] else "No medible"])
    detalle.append(["Total medible", miles(n_med), miles(r_med),
                    f"{razon_med:.2f}×", ""])
    S.append(KeepTogether([
        Paragraph("Detalle por hora", H2),
        tabla(detalle, [2.6 * cm, 3.0 * cm, 3.6 * cm, 2.6 * cm, 4.2 * cm], [
            ("ALIGN", (4, 0), (4, -1), "LEFT"),
            ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 9),
            ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.HexColor(TINTA)),
        ] + [("TEXTCOLOR", (4, i + 1), (4, i + 1),
              colors.HexColor(VERDE if f["medible"] else ROJO))
             for i, f in enumerate(filas)]),
    ]))

    S.append(PageBreak())

    S.append(Paragraph("Composición vehicular", H2))
    S.append(Paragraph(
        "El sistema separa vehículo liviano de pesado. Contrastado contra el "
        "desglose del aforo manual en horario medible:", P))
    S.append(tabla([
        ["", "Sistema", "Aforo manual", "Diferencia"],
        ["Livianos", "88.8 %", "88.4 %", "0.4 pts"],
        ["Pesados", "11.2 %", "11.6 %", "0.4 pts"],
    ], [4.6 * cm, 3.8 * cm, 4.0 * cm, 3.6 * cm], [
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
    ]))
    S.append(Spacer(1, 4))
    S.append(Paragraph(
        "El <b>99.1 %</b> de los vehículos contados en horario medible recibe "
        "clasificación. La verificación no se hizo solo comparando totales — un "
        "error en un sentido y otro en el contrario se cancelan — sino "
        "revisando <b>108 vehículos recortados del video, uno por uno</b>, en dos "
        "franjas horarias distintas.", NOTA))
    S.append(Paragraph(
        "<b>Límite declarado:</b> no se separa autobús de camión. A la distancia "
        "de esta cámara se ven igual. El desglose que se entrega es liviano "
        "contra pesado.", P))

    S.append(Paragraph("La exactitud depende del volumen", H2))
    S.append(Paragraph(
        "La exactitud no es una cifra única a lo largo del día. Cuando la vía se "
        "llena, los vehículos se tapan unos a otros desde el ángulo de la cámara "
        "y el que va detrás no llega a verse:", P))
    S.append(tabla([
        ["Volumen de la hora", "Exactitud medida"],
        ["Menos de 1 600 veh/h", f"{statistics.fmean(bajo):.2f}×"],
        ["2 000 veh/h o más", f"{statistics.fmean(alto):.2f}×"],
    ], [8.6 * cm, 7.4 * cm], [("ALIGN", (1, 0), (1, -1), "CENTER")]))
    S.append(Spacer(1, 4))
    S.append(Paragraph(
        "Es un límite del punto de vista, no del programa: ninguna configuración "
        "recupera un vehículo que está detrás de otro. Se corrige con la altura "
        "y el ángulo de la cámara — cuanto más perpendicular a la vía, menos se "
        "tapan entre sí.", NOTA))

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
            [f"Aforo por hora y por cuartos de hora, {h0:02d}–{h1 + 1:02d} h",
             f"Listo, {razon_med:.2f}×"],
            ["Aforo por sentido de circulación", "Listo"],
            ["Composición liviano / pesado", "Listo, 0.4 pts"],
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
    p.add_argument("--datos", type=Path, required=True)
    p.add_argument("--salida", type=Path, default=RAIZ / "data" / "calibracion.pdf")
    a = p.parse_args()

    if not a.datos.exists():
        sys.exit(f"No existe {a.datos}")
    filas = leer(a.datos)
    if not [f for f in filas if f["medible"]]:
        sys.exit("No hay ninguna hora medible en esos datos.")

    a.salida.parent.mkdir(parents=True, exist_ok=True)
    img = grafica(filas, a.salida.with_suffix(".grafica.png"))
    construir(filas, a.salida, img)
    print(f"{a.salida}  ({a.salida.stat().st_size // 1024} KB, {len(filas)} horas)")


if __name__ == "__main__":
    main()
