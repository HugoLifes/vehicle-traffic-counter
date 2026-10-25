"""
Cola de vehículos a revisar: solo los dudosos, con su recorte, para que
quien opera confirme o corrija con un clic.

Por qué existe. La clase de cada vehículo es un entregable y hasta ahora solo
se revisaba con herramientas de línea de comandos (hoja_cruces.py,
revisar_pesados.py). Las plataformas del ramo hacen lo mismo de otra forma:
OpenTrafficCam aparta para revisión los vehículos cuya clase sale insegura,
con un umbral por clase, y Miovision revisa a mano lo anómalo después de
procesar (ver docs/IDEAS_DE_OTRAS_HERRAMIENTAS.md). Revisar 50 dudosos
cuesta mucho menos que contar una hora a mano, y cada corrección queda como
etiqueta para entrenar el clasificador.

Qué es "dudoso", y de dónde sale cada criterio:

- `doble`: otro cruce de la misma línea y el mismo sentido a menos de
  DOBLE_S, con las cajas encimadas. Medido en el frontal: el 17.6 % de los
  pesados hacia la cámara tenía uno así, y 9 de 16 revisados eran el MISMO
  vehículo (el frente de un autobús como `car`, el faro como moto). Es el
  único motivo que cambia el CONTEO, por eso va primero.
- `frontera`: el alto cae a menos de FRONTERA del corte liviano/pesado. La
  regla del alto acertó 38 de 40 y sus dos fallos fueron una SUV de 53 px y
  una pickup de 54 con el corte en 52.1: justo ahí.
- `modelo`: el clasificador propio de pesados respondió con probabilidad
  menor a PROB_DUDOSA.
- `confianza`: el detector lo vio con menos de CONFIANZA_BAJA y entre el 5 %
  más bajo de su línea. Es donde caen los falsos positivos.

La clase que se revisa es la MISMA que se entrega: sale de
traffic_db._clase_de_cruce, la función que usa get_interval_counts.

Lo que decide quien revisa:
- confirmar o corregir la clase -> `clase_revisada` (gana sobre la regla en
  todo lo que lee el usuario);
- descartar (no es vehículo, o es el mismo contado dos veces) -> el renglón
  pasa a la tabla `descartados` con todos sus datos y sale del conteo; se
  puede deshacer.

Recontar un video borra sus cruces y con ellos la revisión, igual que la de
los pesados.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Medido en el frontal: los pares del mismo vehículo caen a menos de 0.6 s.
DOBLE_S = 0.6
DOBLE_IOU = 0.3
# ±10 % del corte liviano/pesado (los fallos medidos estaban a +4 %).
FRONTERA = 0.10
PROB_DUDOSA = 0.6
CONFIANZA_BAJA = 0.35

# Prioridad: primero lo que cambia el conteo, después la clase.
PRIORIDAD = {"doble": 0, "frontera": 1, "modelo": 2, "confianza": 3}
NOMBRE_MOTIVO = {
    "doble": "Posible doble conteo",
    "frontera": "Entre liviano y pesado",
    "modelo": "El clasificador duda",
    "confianza": "El detector lo vio poco",
}

RECORTES_DIR = Path("data/recortes_revision")

# Cómo se entrega cada clase cuando las opciones son las de la empresa
# (A/B/C, formato Hr/Mov): lo mismo que aforo_excel._CLASE_EMPRESA. Sin esto
# un direccional enseñaba "Pesado" y no ofrecía confirmarlo, porque el
# formato no tiene esa columna.
A_EMPRESA = {"MOTO": "A", "PESADO": "C", "T-S": "C", "T-S-R": "C", "TRACTOR": "C"}


# ── Qué es dudoso (puro, sin base de datos: se prueba sin GPU) ──────────────

def _iou(a, b) -> float:
    ax0, ay0, aw, ah = a
    bx0, by0, bw, bh = b
    ix = max(0.0, min(ax0 + aw, bx0 + bw) - max(ax0, bx0))
    iy = max(0.0, min(ay0 + ah, by0 + bh) - max(ay0, by0))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def _caja(c) -> Optional[Tuple[float, float, float, float]]:
    if c.get("bbox_x") is None or c.get("bbox_y") is None:
        return None
    if not c.get("bbox_width") or not c.get("bbox_height"):
        return None
    return (c["bbox_x"], c["bbox_y"], c["bbox_width"], c["bbox_height"])


def segundo_del_cruce(c: Dict, fps: Optional[float]) -> float:
    """Segundo del cruce con fracción si se sabe el cuadro; si no, al segundo."""
    if c.get("cuadro") is not None and fps:
        return c["cuadro"] / fps
    return float(datetime.fromisoformat(c["timestamp"]).timestamp())


def _confianza_baja(filas: List[Dict], clave) -> Dict:
    """Corte de confianza baja por grupo (línea o acceso): el menor entre
    CONFIANZA_BAJA y el percentil 5 del grupo.

    Un corte fijo no sirve donde el umbral de detección se bajó a propósito:
    en Fraccionamiento el carril tapado cuenta desde 0.10 (umbral por
    sentido, validado contra el conteo a mano) y con 0.35 fijo salían 3 215
    "dudosos", casi la tercera parte del aforo."""
    grupos = defaultdict(list)
    for f in filas:
        if f.get("confidence") is not None:
            grupos[clave(f)].append(f["confidence"])
    cortes = {}
    for g, cs in grupos.items():
        cs.sort()
        cortes[g] = min(CONFIANZA_BAJA, cs[int(0.05 * (len(cs) - 1))])
    return cortes


def motivos_de_cruces(cruces: List[Dict], fps_por_job: Dict[int, float]) -> Dict[int, List[Tuple[str, str]]]:
    """{id: [(motivo, explicación)]} de los cruces dudosos.

    Cada cruce trae ya su `clase` (la que se entrega) y `umbral` (el corte
    liviano/pesado de su carril y su hora, None si la hora no es medible).
    """
    salida: Dict[int, List[Tuple[str, str]]] = defaultdict(list)

    # Doble conteo: dentro de cada video, línea y sentido, por orden de tiempo.
    grupos = defaultdict(list)
    for c in cruces:
        grupos[(c.get("job_id"), c["lane_id"], c["direction"])].append(c)
    for (job, _, _), lista in grupos.items():
        fps = fps_por_job.get(job)
        con_t = sorted(((segundo_del_cruce(c, fps), c) for c in lista), key=lambda x: x[0])
        for (t0, a), (t1, b) in zip(con_t, con_t[1:]):
            if t1 - t0 > DOBLE_S:
                continue
            # Solo con la caja de los dos: sin ella no se distingue el mismo
            # vehículo de dos que pasan lado a lado. Probado en el frontal,
            # donde los cruces de antes de las 18:20 solo tienen el segundo:
            # con "mismo segundo y alto parecido" salían 1 076 dobles, casi
            # todos parejas en los dos carriles de la calzada.
            ca, cb = _caja(a), _caja(b)
            if not ca or not cb or _iou(ca, cb) < DOBLE_IOU:
                continue
            # Se marca el segundo de la pareja: es el que se descarta si es
            # el mismo vehículo, y su recorte enseña las dos cajas.
            salida[b["id"]].append(("doble", f"Otro cruce {t1 - t0:.1f} s antes en la misma línea (n.º {a['id']})"))
            b["_pareja"] = a["id"]

    cortes = _confianza_baja(cruces, lambda f: f["lane_id"])
    for c in cruces:
        umbral, alto = c.get("umbral"), c.get("bbox_height")
        if umbral and alto and c.get("vehicle_type") in ("truck", "bus") \
                and abs(alto - umbral) <= FRONTERA * umbral:
            salida[c["id"]].append(("frontera", f"Mide {alto} px y el corte es {umbral:.0f} px"))
        if c.get("clase_modelo") and c.get("prob_modelo") is not None \
                and c["prob_modelo"] < PROB_DUDOSA and c.get("clase") not in ("A", "MOTO", "SIN_RESOLVER"):
            salida[c["id"]].append(("modelo", f"Dijo {c['clase_modelo']} con {c['prob_modelo']:.0%}"))
        if umbral and c.get("confidence") is not None and c["confidence"] <= cortes.get(c["lane_id"], -1):
            salida[c["id"]].append(("confianza", f"Confianza {c['confidence']:.2f}"))
    return dict(salida)


def motivos_de_movimientos(movs: List[Dict]) -> Dict[int, List[Tuple[str, str]]]:
    """Lo mismo para el direccional, sin doble conteo: ahí los pedazos ya se
    unen al cerrar el video."""
    salida: Dict[int, List[Tuple[str, str]]] = defaultdict(list)
    cortes = _confianza_baja(movs, lambda f: f.get("origen_id"))
    for m in movs:
        umbral, alto = m.get("umbral"), m.get("bbox_height")
        if umbral and alto and m.get("vehicle_type") in ("truck", "bus") \
                and abs(alto - umbral) <= FRONTERA * umbral:
            salida[m["id"]].append(("frontera", f"Mide {alto} px y el corte es {umbral:.0f} px"))
        if umbral and m.get("confidence") is not None and m["confidence"] <= cortes.get(m.get("origen_id"), -1):
            salida[m["id"]].append(("confianza", f"Confianza {m['confidence']:.2f}"))
    return dict(salida)


# ── La cola, sobre la base ──────────────────────────────────────────────────

def opciones_de_clase(project_id: int, ctx: Optional[Dict] = None) -> List[str]:
    """Las clases entre las que se puede corregir, en la taxonomía que se
    entrega en este proyecto: A/B/C en el direccional (el formato Hr/Mov de
    la empresa), las finas donde alguna calzada da para ellas, y si no,
    liviano/pesado."""
    from src.storage import traffic_db
    if any(z.get("kind") == "acceso" for z in traffic_db.list_zones(project_id)):
        return ["A", "B", "C"]
    if ctx is None:
        ctx = traffic_db.cruces_para_revision(project_id)[1]
    if any((p or {}).get("fino") for p in ctx.get("perfiles", {}).values()):
        return ["A", "MOTO", "B", "C", "T-S", "TRACTOR"]
    return ["A", "PESADO"]


def _clase_mostrada(clase: Optional[str], opciones: List[str]) -> Optional[str]:
    if clase in opciones or clase is None:
        return clase
    return A_EMPRESA.get(clase, clase) if "C" in opciones else clase


def cola(project_id: int, motivo: Optional[str] = None,
         limite: int = 40, desde: int = 0) -> Dict:
    from src.storage import traffic_db
    cruces, ctx = traffic_db.cruces_para_revision(project_id)
    fps = traffic_db.fps_de_videos(project_id)
    m_cruces = motivos_de_cruces(cruces, fps)
    movs = traffic_db.movimientos_para_revision(project_id)
    m_movs = motivos_de_movimientos(movs)

    opciones = opciones_de_clase(project_id, ctx)
    items = []
    for lista, motivos, tipo in ((cruces, m_cruces, "cruce"), (movs, m_movs, "movimiento")):
        for c in lista:
            ms = motivos.get(c["id"])
            if not ms or c.get("clase_revisada"):
                continue
            items.append({
                "tipo": tipo, "id": c["id"], "job_id": c.get("job_id"),
                "hora": c["timestamp"], "clase": _clase_mostrada(c.get("clase"), opciones),
                "linea": c.get("linea"), "movimiento": c.get("movimiento"),
                "alto": c.get("bbox_height"), "confianza": c.get("confidence"),
                "motivos": [{"motivo": k, "texto": t} for k, t in ms],
                "prioridad": min(PRIORIDAD[k] for k, _ in ms),
                "pareja": c.get("_pareja"),
            })
    total = len(items)
    resumen = defaultdict(int)
    for it in items:
        for m in it["motivos"]:
            resumen[m["motivo"]] += 1
    if motivo:
        items = [it for it in items if any(m["motivo"] == motivo for m in it["motivos"])]
    items.sort(key=lambda it: (it["prioridad"], it["hora"]))
    return {
        # `total`: los dudosos sin filtrar; `pendientes`: los del filtro. Un
        # vehículo con dos motivos sale en los dos grupos del resumen, así
        # que sumar el resumen da de más.
        "total": total,
        "pendientes": len(items),
        "resumen": [{"motivo": k, "nombre": NOMBRE_MOTIVO[k], "total": resumen[k]}
                    for k in sorted(resumen, key=PRIORIDAD.get)],
        "revisados": traffic_db.contar_revisados(project_id),
        "descartados": traffic_db.list_descartados(project_id),
        "opciones": opciones,
        "items": items[desde:desde + limite],
    }


def decidir(project_id: int, tipo: str, item_id: int, decision: str) -> Dict:
    """`decision`: una clase de `opciones_de_clase`, o 'descartar'."""
    from src.storage import traffic_db
    if tipo not in ("cruce", "movimiento"):
        raise ValueError("tipo debe ser 'cruce' o 'movimiento'")
    if decision == "descartar":
        return {"descartado": traffic_db.descartar(project_id, tipo, item_id, "revision")}
    if decision not in opciones_de_clase(project_id):
        raise ValueError(f"clase desconocida: {decision}")
    traffic_db.revisar_clase(project_id, tipo, item_id, decision, "revision_manual")
    return {"clase": decision}


def quitar_dobles(project_id: int) -> Dict:
    """Quita del conteo, de una vez, todos los posibles dobles pendientes.

    Revisados a ojo en Fraccionamiento (25-oct-2026), 36 pares al azar de tres
    líneas: ~9 de cada 10 eran el mismo vehículo contado dos veces (un pedazo
    detrás del arbusto o del poste y, unos cuadros después, el vehículo
    entero). Quitarlos dejó el aforo aceptado contra el conteo a mano (5 de 5)
    con 693 en vez de 707. Por eso existe la opción en bloque, pero es del
    operador: queda cada uno en `descartados` con su motivo y se devuelve uno
    por uno o todos (`devolver_dobles`)."""
    from src.storage import traffic_db
    cruces, _ = traffic_db.cruces_para_revision(project_id)
    motivos = motivos_de_cruces(cruces, traffic_db.fps_de_videos(project_id))
    pendientes = {c["id"] for c in cruces if not c.get("clase_revisada")}
    ids = [i for i, ms in motivos.items() if i in pendientes and any(k == "doble" for k, _ in ms)]
    for i in ids:
        traffic_db.descartar(project_id, "cruce", i, MOTIVO_EN_BLOQUE)
    return {"quitados": len(ids)}


def devolver_dobles(project_id: int) -> Dict:
    """Devuelve al conteo todo lo que `quitar_dobles` sacó."""
    from src.storage import traffic_db
    ids = [d["id"] for d in traffic_db.list_descartados(project_id) if d["motivo"] == MOTIVO_EN_BLOQUE]
    for i in ids:
        traffic_db.restaurar_descartado(project_id, i)
    return {"devueltos": len(ids)}


MOTIVO_EN_BLOQUE = "doble (en bloque)"


# ── El recorte ──────────────────────────────────────────────────────────────

def _caja_de_movimiento(m: Dict, fps: float):
    """Cuadro y caja del momento en que el vehículo se ve más grande."""
    rec = json.loads(m["recorrido"]) if isinstance(m.get("recorrido"), str) else m.get("recorrido")
    if not rec or not rec.get("t"):
        return None, None
    i = max(range(len(rec["h"])), key=lambda k: rec["h"][k])
    x, y, h = rec["x"][i], rec["y"][i], rec["h"][i]
    # El recorrido guarda el punto de apoyo (centro del borde inferior) y el
    # alto; el ancho no, y se supone de automóvil visto en diagonal.
    w = 1.5 * h
    return int(round(rec["t"][i] * fps)), (x - w / 2, y - h, w, h)


def recorte_jpeg(tipo: str, item_id: int, pareja: Optional[int] = None) -> Optional[bytes]:
    """JPEG del vehículo en su cuadro, con la caja (y la de su pareja, si es
    un posible doble). Se guarda en disco: leer un cuadro de 2560x1440 a la
    mitad del video cuesta casi un segundo en el Orin."""
    import cv2
    from src.storage import traffic_db

    RECORTES_DIR.mkdir(parents=True, exist_ok=True)
    cache = RECORTES_DIR / f"{tipo}_{item_id}{f'_{pareja}' if pareja else ''}.jpg"
    if cache.exists():
        return cache.read_bytes()

    fila = traffic_db.fila_para_recorte(tipo, item_id)
    if not fila:
        return None
    job = traffic_db.get_video_job(fila["job_id"]) if fila.get("job_id") else None
    if not job or not Path(job["stored_path"]).exists():
        return None
    fps = job.get("fps") or 15.0

    cajas = []
    if tipo == "cruce":
        cuadro = fila.get("cuadro")
        if cuadro is None and job.get("video_start_time"):
            t = (datetime.fromisoformat(fila["timestamp"])
                 - datetime.fromisoformat(job["video_start_time"])).total_seconds()
            cuadro = int((t + 0.5) * fps)
        caja = _caja(fila)
        if caja:
            cajas.append((caja, (60, 200, 60)))
        if pareja:
            otra = traffic_db.fila_para_recorte("cruce", pareja)
            if otra and _caja(otra):
                cajas.append((_caja(otra), (0, 165, 255)))
    else:
        cuadro, caja = _caja_de_movimiento(fila, fps)
        if caja:
            cajas.append((caja, (60, 200, 60)))
    if cuadro is None:
        return None

    cap = cv2.VideoCapture(job["stored_path"])
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, cuadro))
        ok, img = cap.read()
    finally:
        cap.release()
    if not ok or img is None:
        return None

    alto_img, ancho_img = img.shape[:2]
    if cajas:
        x0, y0, w, h = cajas[0][0]
        lado = max(w, h) * 2.2
        lado = max(lado, 160)
        cx, cy = x0 + w / 2, y0 + h / 2
        a = int(max(0, cx - lado / 2)); b = int(max(0, cy - lado / 2))
        c = int(min(ancho_img, cx + lado / 2)); d = int(min(alto_img, cy + lado / 2))
    else:
        a, b, c, d = 0, 0, ancho_img, alto_img
    grosor = max(1, int(round(ancho_img / 640)))
    for (x0, y0, w, h), color in cajas:
        cv2.rectangle(img, (int(x0), int(y0)), (int(x0 + w), int(y0 + h)), color, grosor)
    rec = img[b:d, a:c]
    escala = min(1.0, 420 / max(rec.shape[:2])) if rec.size else 1.0
    if escala < 1.0:
        rec = cv2.resize(rec, None, fx=escala, fy=escala, interpolation=cv2.INTER_AREA)
    elif max(rec.shape[:2]) < 240:
        # Vehículos de 15 px: se amplía para que se distinga algo.
        f = 240 / max(rec.shape[:2])
        rec = cv2.resize(rec, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    ok, buf = cv2.imencode(".jpg", rec, [cv2.IMWRITE_JPEG_QUALITY, 82])
    if not ok:
        return None
    datos = buf.tobytes()
    cache.write_bytes(datos)
    return datos
