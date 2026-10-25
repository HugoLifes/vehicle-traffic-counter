"""
Qué tan confiable es cada movimiento del aforo direccional, dicho en el
reporte y en el Excel junto a la cifra.

Por qué. Una cifra sin su nivel se lee igual de cierta que todas. En
Fraccionamiento la misma tabla Hr/Mov mezcla movimientos seguidos de punta a
punta, movimientos medidos con la línea de la calle (1_3, 3_1) y dos que la
cámara no separa (2_1 y 2_3, que doblan detrás de un arbusto). Antes eso solo
lo sabía quien calibró; con esto lo sabe quien recibe el Excel.

El nivel sale de tres cosas que la plataforma ya mide:
  1. la comparación contra el conteo a mano (validacion_od), si la hay: es la
     única que VALIDA;
  2. cómo se obtuvo la cifra: seguida de punta a punta, por línea o juntos;
  3. la calidad del seguimiento de la cámara (calidad.py): sin conteo a mano,
     es lo que separa "medido" de "poco confiable". Sus cortes están medidos
     en los cinco direccionales con resultado conocido.

Nunca sube una cifra de nivel por lo que se espera de ella: sin conteo a
mano, lo más alto que se declara es "medido".
"""

from __future__ import annotations

from typing import Dict, List, Optional

VALIDADO = "Validado"
NO_PASA = "No pasó la validación"
MEDIDO = "Medido"
CON_RESERVAS = "Medido con reservas"
POCO_CONFIABLE = "Poco confiable"
# Por debajo de esto, en la hora, el GEH acepta diferencias grandes.
POCOS = 30


_MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre")


def _fecha(iso: Optional[str]) -> str:
    try:
        a, m, d = (int(x) for x in str(iso)[:10].split("-"))
        return f" del {d} de {_MESES[m - 1]}"
    except (ValueError, IndexError):
        return ""


def niveles(formato: Dict, validacion: Optional[Dict], calidad: Optional[Dict]) -> List[Dict]:
    """Un renglón por movimiento del formato: {movimiento, nivel, detalle}.

    `formato` = aforo_excel.formato_direccional; `validacion` =
    validacion_od.validar (o None); `calidad` = calidad.resumir (o None).
    Puro: se prueba sin base de datos."""
    derivados = set(formato.get("derivados") or [])
    juntos = {m: g for g in (formato.get("juntos") or []) for m in g}
    filas_val = {}
    ventana = ""
    if validacion and not validacion.get("error"):
        cuartos = validacion.get("por_cuarto") or []
        if cuartos:
            h, m = map(int, cuartos[-1]["inicio"].split(":"))
            fin = f"{(h * 60 + m + 15) // 60:02d}:{(m + 15) % 60:02d}"
            ventana = f" en {cuartos[0]['inicio']}–{fin}{_fecha(validacion.get('fecha'))}"
        for r in validacion.get("movimientos") or []:
            for m in r["movimiento"].split(" + "):
                filas_val[m] = r

    salida = []
    for mov in formato.get("movimientos") or []:
        como = []
        if mov in derivados:
            como.append("sale de la línea de conteo de su calle, menos las vueltas")
        if mov in juntos:
            otros = " y ".join(juntos[mov])
            como.append(f"la cámara no separa {otros}: vale la suma, no el reparto")

        r = filas_val.get(mov)
        if r is not None:
            comparado = (f"{r['plataforma']} contra {r['manual']} del conteo a mano{ventana}, "
                         f"GEH {r['geh']:.1f}"
                         + (f" (suma de {r['movimiento']})" if r.get("juntos") else ""))
            nivel = VALIDADO if r["pasa"] else NO_PASA
            detalle = comparado
            mayor = max(r["plataforma"], r["manual"])
            if r["pasa"] and mayor < POCOS and abs(r["plataforma"] - r["manual"]) > 0.3 * mayor:
                # El GEH es tolerante con flujos chicos: en Calle terracería
                # 1_3 dio 11 contra 3 y pasa (GEH 3.0). Pasa el criterio, pero
                # la cifra solo vale como orden de magnitud.
                detalle += (f"; con menos de {POCOS} vehículos en la hora el GEH es tolerante: "
                            "tómese como orden de magnitud")
        else:
            color = (calidad or {}).get("color")
            if (calidad or {}).get("cordon") or color in (None, "gris"):
                # En un cordón la fracción de seguimiento no dice nada (ver
                # calidad.py): sin conteo a mano no hay con qué graduarlo.
                nivel, detalle = MEDIDO, "sin conteo a mano para compararlo"
            elif color == "verde":
                nivel = MEDIDO
                detalle = (f"la cámara sigue al {round(100 * calidad['fraccion'])} % de los vehículos "
                           "de punta a punta; sin conteo a mano para compararlo")
            elif color == "ambar":
                nivel = CON_RESERVAS
                detalle = (f"la cámara solo sigue al {round(100 * calidad['fraccion'])} % de los "
                           "vehículos de punta a punta; conviene compararlo con un conteo a mano")
            else:
                nivel = POCO_CONFIABLE
                detalle = (f"la cámara solo sigue al {round(100 * calidad['fraccion'])} % de los "
                           "vehículos de punta a punta; no entregarlo sin un conteo a mano")
        if como:
            detalle = detalle + "; " + "; ".join(como)
        salida.append({"movimiento": mov, "nivel": nivel, "detalle": detalle})
    return salida


def niveles_de_proyecto(project_id: int, formato: Dict) -> List[Dict]:
    from src.engine import calidad
    from src.reports import validacion_od
    try:
        val = validacion_od.validar(project_id)
    except Exception:
        val = None
    try:
        cal = calidad.calidad_de_proyecto(project_id)
    except Exception:
        cal = None
    return niveles(formato, val, cal)
