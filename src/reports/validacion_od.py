"""
Validación de un aforo direccional contra el conteo a mano de la empresa,
dentro de la plataforma.

La exactitud de un direccional depende de la cámara: en Calle terracería la
plataforma dio 152 contra 147 con los 6 movimientos en GEH < 5, y en Gómez
Morín, con una cámara de 640x360, 1 380 contra 3 014 (13-oct-2026). No se
puede declarar un número de exactitud general; se declara el de cada
intersección, midiéndolo contra una hora contada a mano. Esto lo hacía
`tools/comparar_od_real.py` desde la terminal; aquí lo hace quien opera la
plataforma: sube el Excel de campo (el formato Hr/Mov de la empresa, una
tabla por hoja), elige la hoja y el día, y el Reporte dice el GEH de cada
movimiento y si pasa el criterio.

Lo de la plataforma sale de `aforo_excel.formato_direccional`: lo mismo que
el Reporte y el Excel, movimientos tomados de una línea incluidos.

GEH = sqrt(2 (M - C)^2 / (M + C)) sobre flujos HORARIOS; se acepta el aforo
cuando al menos 85 % de los movimientos dan GEH < 5.
"""

import json
import math
import re
import warnings
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

DIRECTORIO = Path("data/conteos_manuales")
CRITERIO_GEH = 5.0
CRITERIO_PCT = 85.0


def _minuto(etiqueta) -> Optional[int]:
    """'4:45 PM - 5:00 PM' -> 1005."""
    m = re.match(r"\s*(\d{1,2}):(\d{2})\s*(AM|PM)", str(etiqueta or ""), re.I)
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if ap == "PM" and h != 12:
        h += 12
    if ap == "AM" and h == 12:
        h = 0
    return h * 60 + mi


def leer_hojas(ruta) -> Dict[str, Dict[int, Dict[str, List[int]]]]:
    """{hoja: {minuto: {"1_2": [A, B, C]}}} de cada hoja con una tabla Hr/Mov.
    Una fila sin ningún número es un cuarto que nadie contó y no entra."""
    import openpyxl
    warnings.filterwarnings("ignore")
    salida = {}
    for ws in openpyxl.load_workbook(ruta, data_only=True).worksheets:
        filas = [list(r) for r in ws.iter_rows(values_only=True)]
        hoja = {}
        i = 0
        while i < len(filas):
            col = next((j for j, v in enumerate(filas[i])
                        if v and str(v).strip().lower().startswith("hr/mov")), None)
            if col is None:
                i += 1
                continue
            movs = {j: str(v).strip() for j, v in enumerate(filas[i])
                    if j > col and v not in (None, "") and re.fullmatch(r"\d+_\d+", str(v).strip())}
            k = i + 2
            while k < len(filas) and filas[k][col] and "TOTAL" not in str(filas[k][col]).upper():
                ini = _minuto(filas[k][col])
                valores = {m: [int(filas[k][j + d]) if j + d < len(filas[k])
                               and isinstance(filas[k][j + d], (int, float)) else None
                               for d in range(3)] for j, m in movs.items()}
                if ini is not None and any(v is not None for vs in valores.values() for v in vs):
                    hoja[ini] = {m: [v or 0 for v in vs] for m, vs in valores.items()}
                k += 1
            i = k
        if hoja:
            salida[ws.title] = hoja
    return salida


def _rutas(project_id: int):
    return DIRECTORIO / f"{project_id}.xlsx", DIRECTORIO / f"{project_id}.json"


def resumen_hojas(ruta) -> List[Dict]:
    """Lo que hay en cada hoja, para elegir cuál es esta intersección."""
    salida = []
    for hoja, q in leer_hojas(ruta).items():
        ms = sorted(q)
        total = sum(sum(v) for c in q.values() for v in c.values())
        salida.append({"hoja": hoja, "total": total,
                       "desde": f"{ms[0] // 60:02d}:{ms[0] % 60:02d}",
                       "hasta": f"{(ms[-1] + 15) // 60:02d}:{(ms[-1] + 15) % 60:02d}"})
    return salida


def guardar(project_id: int, datos: bytes, nombre: str, hoja: str, fecha: str) -> None:
    xlsx, meta = _rutas(project_id)
    DIRECTORIO.mkdir(parents=True, exist_ok=True)
    xlsx.write_bytes(datos)
    meta.write_text(json.dumps({"archivo": nombre, "hoja": hoja, "fecha": fecha},
                               ensure_ascii=False), encoding="utf-8")


def borrar(project_id: int) -> None:
    for r in _rutas(project_id):
        r.unlink(missing_ok=True)


def _geh(m: float, c: float) -> float:
    return math.sqrt(2 * (m - c) ** 2 / (m + c)) if m + c else 0.0


def validar(project_id: int) -> Optional[Dict]:
    """La comparación, o None si la intersección no tiene conteo a mano."""
    from src.reports.aforo_excel import formato_direccional
    xlsx, meta_ruta = _rutas(project_id)
    if not (xlsx.exists() and meta_ruta.exists()):
        return None
    meta = json.loads(meta_ruta.read_text(encoding="utf-8"))
    manual = leer_hojas(xlsx).get(meta["hoja"], {})
    f = formato_direccional(project_id)
    if f is None:
        return {**meta, "error": "Los accesos no tienen el número del croquis («1 · …»)."}
    nuestro = {int(q["inicio"][:2]) * 60 + int(q["inicio"][3:]): q["valores"]
               for q in f["cuartos"] if q["fecha"] == meta["fecha"]}
    cuartos = sorted(m for m in manual if m in nuestro)
    faltan = sorted(m for m in manual if m not in nuestro)
    if not cuartos:
        return {**meta, "error": "Ningún cuarto de hora del conteo a mano está contado por la "
                                 "plataforma ese día. Revisa la fecha."}
    movs = sorted({m for q in cuartos for m in manual[q]} | set(f["movimientos"]),
                  key=lambda m: tuple(int(x) for x in m.split("_")))
    horas = len(cuartos) / 4
    filas = []
    for mv in movs:
        p = sum(sum(nuestro[q].get(mv, [0, 0, 0])) for q in cuartos)
        a = sum(sum(manual[q].get(mv, [0, 0, 0])) for q in cuartos)
        if not p and not a:
            continue
        g = _geh(p / horas, a / horas)
        filas.append({"movimiento": mv, "plataforma": p, "manual": a, "geh": round(g, 1),
                      "pasa": g < CRITERIO_GEH,
                      "por_linea": mv in f["derivados"]})
    # Movimientos que la cámara no separa: se valida su suma y no cada uno.
    for g in f.get("juntos", []):
        enc = [r for r in filas if r["movimiento"] in g]
        if not enc:
            continue
        p = sum(r["plataforma"] for r in enc)
        a = sum(r["manual"] for r in enc)
        gh = _geh(p / horas, a / horas)
        filas = [r for r in filas if r["movimiento"] not in g]
        filas.append({"movimiento": " + ".join(g), "plataforma": p, "manual": a, "geh": round(gh, 1),
                      "pasa": gh < CRITERIO_GEH, "por_linea": False, "juntos": True})
    pasan = sum(1 for r in filas if r["pasa"])
    tp, ta = sum(r["plataforma"] for r in filas), sum(r["manual"] for r in filas)
    por_cuarto = [{"inicio": f"{q // 60:02d}:{q % 60:02d}",
                   "plataforma": sum(sum(v) for v in nuestro[q].values()),
                   "manual": sum(sum(v) for v in manual[q].values())} for q in cuartos]
    pct = 100 * pasan / len(filas) if filas else 0
    return {**meta, "movimientos": filas, "por_cuarto": por_cuarto,
            "total_plataforma": tp, "total_manual": ta,
            "razon": round(tp / ta, 3) if ta else None,
            "pasan": pasan, "de": len(filas), "pct": round(pct),
            "aceptado": pct >= CRITERIO_PCT,
            "criterio": f"GEH < {CRITERIO_GEH:g} en al menos {CRITERIO_PCT:g} % de los movimientos",
            "cuartos_sin_contar": [f"{q // 60:02d}:{q % 60:02d}" for q in faltan]}
