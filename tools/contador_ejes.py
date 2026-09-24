"""
Lector de los reportes del contador de ejes (tubo neumatico RoadRunner3).

La empresa entrega dos reportes por sentido, del mismo aparato:

- "Basic Axle Classification Report" (clasificatorio): por cuarto de hora,
  13 clases por ejes: Cycle, Cars, 2A-4T, Buses, 2A-SU, 3A-SU, 4A-SU, 4A-ST,
  5A-ST, 6A-ST, 5A-MT, 6A-MT, Other, y el Total.
- "Basic Volume Report" (volumen): por hora, con una columna por cuarto
  (:00 :15 :30 :45) y el Total.

Tres detalles del formato que costaron descubrir, y por los que este lector
NO toma las columnas del encabezado:

1. **Los encabezados no caen en la misma columna que los datos** (celdas
   combinadas): "Buses" dice columna 8 y el dato esta en la 9. Leer las
   clases por encabezado las revuelve.
2. **Las columnas se recorren entre paginas del reporte**: el total cae en la
   23 en la primera pagina y en la 22 en las siguientes.
3. **"Cycle" son las motocicletas** (clase 1 del esquema), y el Total las
   incluye. No es la hora de ningun ciclo: sin ella las clases no suman el
   total en ninguna fila.

Por eso el clasificatorio se lee por POSICION ORDINAL: en cada fila se toman
los numeros despues de la hora, en orden, y la fila solo vale si las 13 clases
suman el total. El volumen, cuyas columnas si coinciden con su encabezado, se
lee con las del encabezado de cada pagina y se exige lo mismo: que los cuatro
cuartos sumen el total de la hora.

Los reportes traen VARIOS DIAS (el del frontal va del 19 al 24 de
septiembre). La fecha aparece solo en la primera fila de cada dia, como
serial de Excel; en las demas se arrastra, y un cambio de dia tambien se
reconoce porque la hora regresa.

    python tools/contador_ejes.py "D:/nuevos datos aforos miguel/*.xls"
"""
from __future__ import annotations

import datetime as dt
import glob
import sys
from collections import defaultdict

CLASES = ("Cycle", "Cars", "2A-4T", "Buses", "2A-SU", "3A-SU", "4A-SU",
          "4A-ST", "5A-ST", "6A-ST", "5A-MT", "6A-MT", "Other")

# Traduccion a la taxonomia SCT de la empresa. "Other" es lo que el aparato
# no pudo clasificar (ejes que no forman un patron conocido): se deja aparte.
SCT = {"Cycle": "MOTO", "Cars": "A", "2A-4T": "A", "Buses": "B",
       "2A-SU": "C", "3A-SU": "C", "4A-SU": "C",
       "4A-ST": "T-S", "5A-ST": "T-S", "6A-ST": "T-S",
       "5A-MT": "T-S-R", "6A-MT": "T-S-R", "Other": "OTRO"}

_EXCEL_0 = dt.date(1899, 12, 30)
DIAS = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}


def _con_rotulo(hoja, fila) -> bool:
    """La fila trae texto que no es el dia de la semana: "Daily Total",
    "Percent", "Average", "AM Total"... Son resumenes, no datos. La de
    porcentajes es la peligrosa: sus valores son menores que 1, se leian como
    una hora, y como suman 100 pasaban el candado de la suma."""
    for c in range(hoja.ncols):
        v = hoja.cell_value(fila, c)
        if isinstance(v, str) and v.strip() and v.strip() not in DIAS:
            return True
    return False


def _es_fecha(v) -> bool:
    return isinstance(v, float) and 40000 < v < 60000


def _texto(hoja, fila) -> str:
    return " ".join(str(hoja.cell_value(fila, c)) for c in range(hoja.ncols))


def metadatos(hoja) -> dict:
    meta = {}
    for r in range(min(hoja.nrows, 30)):
        linea = _texto(hoja, r)
        vals = [str(hoja.cell_value(r, c)).strip() for c in range(hoja.ncols)]
        vals = [v for v in vals if v]
        if "Info Line 1" in linea and len(vals) > 1:
            meta["sentido"] = vals[1].lower()
        if "Serial Number" in linea:
            meta["serie"] = vals[-1].replace(".0", "")
        if "Ax-Ax" in linea:
            # Separacion entre mangueras: de ella depende la velocidad y, con
            # ella, la clase por ejes. En agosto el aparato 19079 la tenia mal
            # y clasificaba casi todos los automoviles como 2A-4T.
            cm_ = [v for v in vals if v.endswith("cm")]
            if cm_:
                meta["separacion"] = cm_[0]
        if "Data From:" in linea:
            meta["rango"] = linea.split("From:")[1].strip()
        if "Classification Report" in linea:
            meta["tipo"] = "clasificatorio"
        if "Volume Report" in linea:
            meta["tipo"] = "volumen"
    return meta


# Rangos de velocidad del reporte de velocidades, en km/h (son de 5 mph:
# 32.2 km/h = 20 mph). Quince rangos y despues "Other", que es lo que pasa de
# 144.7 o no se pudo medir.
RANGOS_KMH = ((0.0, 32.1), (32.2, 40.1), (40.2, 48.1), (48.2, 56.2), (56.3, 64.2),
              (64.3, 72.3), (72.4, 80.3), (80.4, 88.4), (88.5, 96.4), (96.5, 104.5),
              (104.6, 112.5), (112.6, 120.6), (120.7, 128.6), (128.7, 136.7),
              (136.8, 144.7))


def _seccion(textos, actual):
    """Estado del recorrido: (tipo, carril) de la seccion en la que se esta.

    Un solo archivo "clasificatorio" trae CUATRO secciones: la clasificacion
    por ejes del carril 1, la del carril 2, un resumen, y un reporte de
    VELOCIDADES por rango para los dos carriles. La primera version lo leia
    como una sola tabla y el carril 2, casi todo en ceros, pisaba al carril 1:
    el 19 de septiembre salia con 3 vehiculos donde el aparato conto 9 776.
    """
    tipo, carril = actual
    for x in textos:
        if "Summary" in x or "Charts" in x:
            return None, None
        if "Lane #" in x and ("Data From" in x):
            carril = int(x.split("Lane #")[1][0])
            if "Speed" in x:
                tipo = "velocidad"
            elif "Axle" in x:
                tipo = "clasificatorio"
            elif "Volume" in x or tipo is None:
                tipo = tipo or "volumen"
    return tipo, carril


def leer_todo(ruta):
    """{(tipo, carril): {fecha_iso: {minuto: valores}}}, y metadatos.

    tipo 'clasificatorio': valores = {clase: n}
    tipo 'velocidad':      valores = [n por rango de RANGOS_KMH] + [otros]
    tipo 'volumen':        valores = vehiculos
    """
    import xlrd
    hoja = xlrd.open_workbook(ruta).sheet_by_index(0)
    meta = metadatos(hoja)
    salida: dict = defaultdict(lambda: defaultdict(dict))
    rechazadas: dict = defaultdict(int)
    estado = (None, None)
    fecha, ultimo = None, None
    for r in range(hoja.nrows):
        celdas = [hoja.cell_value(r, c) for c in range(hoja.ncols)]
        textos = [x for x in celdas if isinstance(x, str) and x.strip()]
        nuevo = _seccion(textos, estado)
        if nuevo != estado:
            estado, fecha, ultimo = nuevo, None, None
        tipo, carril = estado
        if tipo is None or _con_rotulo(hoja, r):
            continue
        if tipo == "volumen" and meta.get("tipo") != "volumen":
            continue
        nums = [(c, v) for c, v in enumerate(celdas) if isinstance(v, float)]
        if len(nums) < 3:
            continue
        if _es_fecha(nums[0][1]):
            fecha = _EXCEL_0 + dt.timedelta(days=int(nums[0][1]))
            nums = nums[1:]
            ultimo = None
        (_, hora), resto = nums[0], nums[1:]
        if not (0 <= hora < 1) or fecha is None or not resto:
            continue
        minuto = round(hora * 1440)
        if ultimo is not None and minuto < ultimo:
            fecha += dt.timedelta(days=1)   # la hora regreso: otro dia
        ultimo = minuto
        dia = salida[(tipo, carril)][fecha.isoformat()]
        valores = [v for _, v in resto]
        if tipo == "clasificatorio":
            if len(valores) < 14 or abs(sum(valores[:13]) - valores[13]) > 0.5:
                rechazadas[(tipo, carril)] += 1
                continue
            dia[minuto] = dict(zip(CLASES, valores[:13]))
        elif tipo == "velocidad":
            n = len(RANGOS_KMH) + 1          # rangos + "Other"
            if len(valores) < n + 1 or abs(sum(valores[:n]) - valores[n]) > 0.5:
                rechazadas[(tipo, carril)] += 1
                continue
            dia[minuto] = valores[:n]
        else:
            # Los cuartos se ubican por su distancia a la columna del TOTAL:
            # el encabezado no sirve (en la pagina 2 dice que la hora va en la
            # columna 3 y va en la 2), y por orden tampoco, porque la primera y
            # la ultima hora del reporte llegan incompletas.
            col_total, total = resto[-1]
            cuartos = {col_total - c: v for c, v in resto[:-1]}
            if not cuartos or max(cuartos) > 4 or abs(sum(cuartos.values()) - total) > 0.5:
                rechazadas[(tipo, carril)] += 1
                continue
            for distancia, v in cuartos.items():
                dia[minuto + 15 * (4 - distancia)] = v
    return meta, {k: dict(v) for k, v in salida.items()}, dict(rechazadas)


def leer(ruta, carril=1):
    """Compatibilidad: (meta, {fecha: {minuto: ...}}, rechazadas) del carril
    pedido, del tipo principal del archivo."""
    meta, secciones, rech = leer_todo(ruta)
    tipo = meta.get("tipo", "clasificatorio")
    return meta, secciones.get((tipo, carril), {}), rech.get((tipo, carril), 0)


def _total(v):
    if isinstance(v, dict):
        return sum(v.values())
    if isinstance(v, list):
        return sum(v)
    return v


def main():
    for patron in sys.argv[1:]:
        for ruta in sorted(glob.glob(patron)):
            meta, secciones, rech = leer_todo(ruta)
            print(ruta)
            print("  " + ", ".join(f"{k}: {v}" for k, v in meta.items() if k != "tipo"))
            for (tipo, carril), datos in sorted(secciones.items()):
                print(f"  [{tipo}, carril {carril}]  filas que no suman su total: "
                      f"{rech.get((tipo, carril), 0)}")
                for fecha, d in sorted(datos.items()):
                    tot = sum(_total(v) for v in d.values())
                    print(f"    {fecha}: {len(d):>3} cuartos de hora, {int(tot):>6} vehiculos")


if __name__ == "__main__":
    main()
