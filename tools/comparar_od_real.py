"""
Contrasta el aforo direccional de la plataforma contra el conteo manual de
la empresa, movimiento por movimiento y cuarto de hora por cuarto de hora.

El conteo manual numera los accesos (1, 2, 3...) sobre un croquis y anota
cada movimiento como "origen_destino" (p. ej. 2_3) con clases A, B y C. Los
accesos de la plataforma se dibujan sobre la imagen de la cámara y tienen
nombres ("Arco", "Bajo puente"). Qué acceso es qué número no se adivina por
el nombre —igual que el emparejamiento calzada↔sentido del aforo por línea
se hace por los datos—: se prueban TODAS las asignaciones y se queda la que
menos error deja. Un acceso nuestro puede caer en el mismo número que otro
(dos polígonos sobre el mismo brazo).

Se reporta por movimiento el GEH, la medida estándar para validar conteos
de tránsito: GEH = sqrt(2 (M - C)^2 / (M + C)) sobre flujos horarios. Se
acepta un conteo cuando al menos 85 % de los movimientos tiene GEH < 5.

Los movimientos de la plataforma se leen con get_matriz_od, el mismo
camino que usan el informe y el Excel: por omisión decididos por
trayectoria (--metodo zonas para los de antes). El emparejamiento se puede
fijar por geometría con --asignacion; sin ella se busca el de menos error,
que con pocos cuartos de hora rescata dibujos equivocados.

    python tools/comparar_od_real.py --proyecto 3 \\
        --manual "referencias/aforo_direccional/AFORO BLVD. INDEPENDENCIA.xlsx" \\
        --asignacion "Arco=2,Fondo izq=1,Izquierda=3,Abajo=3,Derecha=x"
"""

import argparse
import itertools
import math
import re
import sqlite3
import sys
import warnings
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BD = RAIZ / 'data' / 'traffic.db'
sys.path.insert(0, str(RAIZ))


def _minuto(etiqueta):
    """'4:45 PM - 5:00 PM' -> 1005 (minuto del día en que empieza)."""
    m = re.match(r'\s*(\d{1,2}):(\d{2})\s*(AM|PM)', str(etiqueta or ''), re.I)
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if ap == 'PM' and h != 12:
        h += 12
    if ap == 'AM' and h == 12:
        h = 0
    return h * 60 + mi


def leer_manual(ruta):
    """{minuto_inicio: {'2_3': [A, B, C], ...}} de todos los bloques del libro."""
    import openpyxl
    warnings.filterwarnings('ignore')
    real = {}
    for ws in openpyxl.load_workbook(ruta, data_only=True).worksheets:
        filas = [list(r) for r in ws.iter_rows(values_only=True)]
        i = 0
        while i < len(filas):
            r = filas[i]
            col = next((j for j, v in enumerate(r)
                        if v and str(v).strip().lower().startswith('hr/mov')), None)
            if col is None:
                i += 1
                continue
            movs = {j: str(v).strip() for j, v in enumerate(r)
                    if j > col and v not in (None, '') and re.fullmatch(r'\w+_\w+', str(v).strip())}
            k = i + 2
            while k < len(filas) and filas[k][col] and 'TOTAL' not in str(filas[k][col]).upper():
                ini = _minuto(filas[k][col])
                if ini is not None:
                    real[ini] = {
                        m: [int(filas[k][j + d]) if j + d < len(filas[k])
                            and isinstance(filas[k][j + d], (int, float)) else 0 for d in range(3)]
                        for j, m in movs.items()
                    }
                k += 1
            i = k
    return real


def leer_plataforma(bd, proyecto, metodo='trayectoria'):
    con = sqlite3.connect(f'file:{bd}?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    accesos = {r['id']: r['name'] for r in con.execute(
        "select id, name from zones where project_id=? and kind='acceso'", (proyecto,))}
    # Cobertura como unión de intervalos en SEGUNDOS. Redondear cada video a
    # minutos enteros por separado dejaba un hueco falso entre tramos
    # contiguos (16:34:53-16:44:53 y 16:44:53-...: el minuto 16:44 se perdía)
    # y ningún cuarto de hora salía completo. Entre tramos reales hay huecos
    # de 1 s, así que se toleran 3 s.
    tramos = []
    for r in con.execute("select video_start_time t, total_frames f, fps from video_jobs "
                         "where project_id=? and status='done' and video_start_time is not null",
                         (proyecto,)):
        h, m, s = map(int, r['t'][11:19].split(':'))
        ini = h * 3600 + m * 60 + s
        tramos.append((ini, ini + (r['f'] or 0) / (r['fps'] or 15)))
    cubiertos = []
    for ini, fin in sorted(tramos):
        if cubiertos and ini <= cubiertos[-1][1] + 3:
            cubiertos[-1][1] = max(cubiertos[-1][1], fin)
        else:
            cubiertos.append([ini, fin])
    con.close()

    from src.storage import traffic_db
    traffic_db.DB_PATH = Path(bd)
    od = traffic_db.get_matriz_od(proyecto, 15, metodo)
    completos = defaultdict(lambda: defaultdict(int))
    incompletos = defaultdict(int)

    def cuarto(intervalo):
        return int(intervalo[11:13]) * 60 + int(intervalo[14:16])

    for m in od['movimientos']:
        completos[cuarto(m['intervalo'])][(m['origen_id'], m['destino_id'])] += m['total']
    for i in od['incompletos']:
        incompletos[cuarto(i['intervalo'])] += i['total']
    return accesos, cubiertos, completos, incompletos, od


def geh(m, c):
    return math.sqrt(2 * (m - c) ** 2 / (m + c)) if m + c else 0.0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--proyecto', type=int, required=True)
    ap.add_argument('--manual', required=True)
    ap.add_argument('--bd', type=Path, default=BD)
    ap.add_argument('--metodo', choices=('trayectoria', 'zonas'), default='trayectoria')
    ap.add_argument('--asignacion', default=None,
                    help='"Nombre=número,..." fijado por geometría; x para un acceso que '
                         'el manual no cuenta')
    a = ap.parse_args()

    real = leer_manual(a.manual)
    accesos, cubiertos, completos, incompletos, od = leer_plataforma(a.bd, a.proyecto, a.metodo)
    if not accesos:
        sys.exit(f'El proyecto {a.proyecto} no tiene accesos dibujados')
    cuartos = sorted(q for q in real
                     if any(ini <= q * 60 and (q + 15) * 60 <= fin for ini, fin in cubiertos))
    if not cuartos:
        sys.exit('Ningún cuarto de hora del conteo manual está cubierto ENTERO por videos contados')
    numeros = sorted({n for q in real for mov in real[q] for n in mov.split('_')})
    movs_manual = sorted({mov for q in real for mov in real[q]})
    ids = sorted(accesos)
    print(f"Cuartos de hora comparables: {', '.join(f'{q // 60:02d}:{q % 60:02d}' for q in cuartos)}")
    print(f"Accesos de la plataforma: {', '.join(accesos[i] for i in ids)}")
    print(f"Accesos del conteo manual: {', '.join(numeros)}")

    print(f"Método: {od['metodo']}" + (
        '  (' + ', '.join(f'{k} {v}' for k, v in sorted(od['resumen_metodo'].items(),
                                                        key=lambda kv: -kv[1])) + ')'
        if od.get('resumen_metodo') else ''))

    def predicho(asig):
        p = defaultdict(lambda: defaultdict(int))
        for q in cuartos:
            for (o, d), n in completos[q].items():
                if o in asig and d in asig and 'x' not in (asig[o], asig[d]):
                    p[q][f'{asig[o]}_{asig[d]}'] += n
        return p

    if a.asignacion:
        por_nombre = {n.strip(): v.strip() for n, v in
                      (par.split('=') for par in a.asignacion.split(','))}
        faltan = {accesos[i] for i in ids} - set(por_nombre)
        if faltan:
            sys.exit(f'La asignación no dice qué número es: {", ".join(sorted(faltan))}')
        asig = {i: por_nombre[accesos[i]] for i in ids}
        titulo = 'Emparejamiento fijado por geometría:'
    else:
        mejor = None
        for combo in itertools.product(numeros, repeat=len(ids)):
            asig = dict(zip(ids, combo))
            p = predicho(asig)
            err = sum(abs(p[q].get(mv, 0) - sum(real[q].get(mv, [0, 0, 0])))
                      for q in cuartos for mv in set(movs_manual) | set(p[q]))
            if mejor is None or err < mejor[0]:
                mejor = (err, asig)
        asig = mejor[1]
        titulo = 'Emparejamiento que menos error deja:'
    print('\n' + titulo)
    for i in ids:
        print(f'  {accesos[i]:<16} -> acceso {asig[i]}')
    p = predicho(asig)

    minutos = 15 * len(cuartos)
    print(f"\n{'movimiento':<11}{'plataforma':>11}{'manual':>8}{'%':>7}{'GEH':>7}")
    geh_ok = n_geh = 0
    tot_p = tot_r = 0
    for mv in movs_manual:
        pv = sum(p[q].get(mv, 0) for q in cuartos)
        rv = sum(sum(real[q].get(mv, [0, 0, 0])) for q in cuartos)
        tot_p += pv
        tot_r += rv
        g = geh(pv * 60 / minutos, rv * 60 / minutos)
        if rv or pv:
            n_geh += 1
            geh_ok += g < 5
        pct = f'{100 * pv / rv:.0f}' if rv else '-'
        print(f'{mv:<11}{pv:>11}{rv:>8}{pct:>7}{g:>7.1f}')
    extra = sorted({mv for q in cuartos for mv in p[q]} - set(movs_manual))
    for mv in extra:
        pv = sum(p[q].get(mv, 0) for q in cuartos)
        tot_p += pv
        print(f'{mv:<11}{pv:>11}{"(no está en el manual)":>30}')
    inc = sum(incompletos[q] for q in cuartos)
    print(f"\n{'TOTAL':<11}{tot_p:>11}{tot_r:>8}{100 * tot_p / tot_r if tot_r else 0:>6.0f}%")
    print(f'Movimientos incompletos de la plataforma en la ventana (no sumados): {inc}')
    print(f'Movimientos con GEH < 5: {geh_ok} de {n_geh} '
          f'({100 * geh_ok / n_geh if n_geh else 0:.0f} %; el criterio de aceptación es 85 %)')

    print('\nPor cuarto de hora (todos los movimientos): plataforma / manual')
    for q in cuartos:
        pv = sum(p[q].values())
        rv = sum(sum(v) for v in real[q].values())
        print(f'  {q // 60:02d}:{q % 60:02d}  {pv:>5} / {rv:<5} ({100 * pv / rv if rv else 0:.0f} %)'
              f'   incompletos {incompletos[q]}')


if __name__ == '__main__':
    main()
