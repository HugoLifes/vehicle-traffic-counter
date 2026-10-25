"""
Regresión sin GPU del nivel de confiabilidad por movimiento
(src/reports/confiabilidad.py), con las cifras reales de las tres
intersecciones del 7 y 8 de octubre:

  1. con conteo a mano, el nivel lo da el GEH: Validado o No pasó, y la
     ventana validada va en el detalle;
  2. un movimiento chico que pasa con mucha diferencia (Calle terracería,
     1_3: 11 contra 3, GEH 3.0) lleva el aviso de "orden de magnitud";
  3. los "juntos" se validan por su suma y lo dicen; los "por línea" también;
  4. sin conteo a mano, la calidad del seguimiento manda: verde = Medido,
     ámbar = con reservas, rojo = Poco confiable (Gómez Morín, 36 %), y en un
     cordón nunca más que Medido;
  5. nunca sale "Validado" sin conteo a mano.

    python tools/probar_confiabilidad.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.reports import confiabilidad as cf  # noqa: E402

fallos = 0


def comprobar(nombre, ok, detalle=""):
    global fallos
    fallos += 0 if ok else 1
    print(f"  [{'ok' if ok else 'FALLA'}] {nombre}" + (f" — {detalle}" if detalle else ""))


def fila(mv, p, a, g, pasa=None, juntos=False, por_linea=False):
    return {"movimiento": mv, "plataforma": p, "manual": a, "geh": g,
            "pasa": g < 5 if pasa is None else pasa, "juntos": juntos, "por_linea": por_linea}


VAL = {"fecha": "2026-10-08", "por_cuarto": [{"inicio": "06:45"}, {"inicio": "07:30"}],
       "movimientos": [fila("1_3", 11, 3, 3.0), fila("3_2", 49, 50, 0.1), fila("2_1", 60, 120, 6.3)]}
FORMATO = {"movimientos": ["1_3", "3_2", "2_1", "1_2"], "derivados": [], "juntos": []}


def main():
    n = {r["movimiento"]: r for r in cf.niveles(FORMATO, VAL, {"color": "verde", "fraccion": 0.89})}
    print("Con conteo a mano")
    comprobar("GEH 0.1 es Validado", n["3_2"]["nivel"] == cf.VALIDADO)
    comprobar("la ventana va en el detalle", "06:45–07:45 del 8 de octubre" in n["3_2"]["detalle"], n["3_2"]["detalle"])
    comprobar("GEH 6.3 no pasa", n["2_1"]["nivel"] == cf.NO_PASA)
    comprobar("11 contra 3 pasa pero avisa", n["1_3"]["nivel"] == cf.VALIDADO and "orden de magnitud" in n["1_3"]["detalle"])
    comprobar("49 contra 50 no lleva ese aviso", "orden de magnitud" not in n["3_2"]["detalle"])
    comprobar("sin renglón en el conteo a mano no se valida", n["1_2"]["nivel"] == cf.MEDIDO, n["1_2"]["nivel"])

    print("Juntos y por línea (Fraccionamiento)")
    val = {"fecha": "2026-10-08", "por_cuarto": [{"inicio": "06:45"}],
           "movimientos": [fila("2_1 + 2_3", 38, 38, 0.0, juntos=True), fila("3_1", 506, 529, 1.0, por_linea=True)]}
    f = {"movimientos": ["2_1", "2_3", "3_1"], "derivados": ["3_1"], "juntos": [["2_1", "2_3"]]}
    n = {r["movimiento"]: r for r in cf.niveles(f, val, {"color": "gris", "cordon": True})}
    comprobar("2_1 validado por la suma", n["2_1"]["nivel"] == cf.VALIDADO and "suma" in n["2_1"]["detalle"])
    comprobar("y dice que no se separan", "no separa" in n["2_3"]["detalle"])
    comprobar("3_1 dice que sale de la línea", "línea de conteo" in n["3_1"]["detalle"])

    print("Sin conteo a mano")
    for color, frac, esperado in (("verde", 0.89, cf.MEDIDO), ("ambar", 0.56, cf.CON_RESERVAS),
                                  ("rojo", 0.36, cf.POCO_CONFIABLE)):
        r = cf.niveles(FORMATO, None, {"color": color, "fraccion": frac})[0]
        comprobar(f"calidad {color} = {esperado}", r["nivel"] == esperado, r["nivel"])
    r = cf.niveles(FORMATO, None, {"color": "gris", "cordon": True, "fraccion": 0.04})[0]
    comprobar("en un cordón, Medido (la fracción no aplica)", r["nivel"] == cf.MEDIDO)
    todos = [r["nivel"] for c in ("verde", "ambar", "rojo") for r in cf.niveles(FORMATO, None, {"color": c, "fraccion": 0.5})]
    comprobar("nunca Validado sin conteo a mano", cf.VALIDADO not in todos)
    r = cf.niveles(FORMATO, {"error": "no cuadra la fecha"}, {"color": "verde", "fraccion": 0.9})[0]
    comprobar("un conteo a mano con error no valida", r["nivel"] == cf.MEDIDO)


if __name__ == "__main__":
    main()
    print(f"\n{'TODO BIEN' if fallos == 0 else f'{fallos} FALLOS'}")
    sys.exit(1 if fallos else 0)
