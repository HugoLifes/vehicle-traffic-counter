"""
Regresión sin GPU de la cola de vehículos a revisar (src/engine/revision.py).

Comprueba, con cruces fabricados:
  1. el doble conteo: dos cruces de la misma línea y sentido a 0.3 s con las
     cajas encimadas SÍ se marcan; dos autos lado a lado en el mismo instante
     (cajas sin encimar) NO; y sin caja no se marca nada, porque solo con el
     segundo no se distingue un doble de dos carriles (1 076 falsos en el
     frontal antes de exigirla);
  2. la frontera liviano/pesado (±10 % del corte) y que fuera de ella no;
  3. la confianza baja relativa a la línea: en una línea que cuenta desde
     0.10 a propósito, 0.20 no es "baja";
  4. de punta a punta en una base temporal: corregir la clase la cambia en
     get_interval_counts, descartar saca el cruce del conteo y restaurarlo lo
     devuelve con el mismo id.

    python tools/probar_revision.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.engine import revision  # noqa: E402
from src.storage import traffic_db  # noqa: E402

fallos = 0


def comprobar(nombre, ok, detalle=""):
    global fallos
    fallos += 0 if ok else 1
    print(f"  [{'ok' if ok else 'FALLA'}] {nombre}" + (f" — {detalle}" if detalle else ""))


def cruce(i, cuadro, x, conf=0.8, h=40, w=70, tipo="car", lane=1, d="in", caja=True, umbral=60.0):
    return {"id": i, "job_id": 1, "lane_id": lane, "direction": d, "vehicle_type": tipo,
            "confidence": conf, "timestamp": "2026-10-08 07:00:00", "cuadro": cuadro,
            "bbox_x": x if caja else None, "bbox_y": 100 if caja else None,
            "bbox_width": w, "bbox_height": h, "umbral": umbral, "clase": "A"}


def puras():
    fps = {1: 10.0}
    print("Doble conteo")
    m = revision.motivos_de_cruces([cruce(1, 100, 300), cruce(2, 103, 305)], fps)
    comprobar("misma caja a 0.3 s se marca", any(k == "doble" for k, _ in m.get(2, [])), str(m))
    m = revision.motivos_de_cruces([cruce(1, 100, 300), cruce(2, 100, 420)], fps)
    comprobar("lado a lado no se marca", "doble" not in str(m), str(m))
    m = revision.motivos_de_cruces([cruce(1, 100, 300), cruce(2, 103, 305, d="out")], fps)
    comprobar("sentidos distintos no se marcan", "doble" not in str(m), str(m))
    m = revision.motivos_de_cruces([cruce(1, 100, 300, caja=False), cruce(2, 100, 300, caja=False)], fps)
    comprobar("sin caja no se marca", "doble" not in str(m), str(m))
    m = revision.motivos_de_cruces([cruce(1, 100, 300), cruce(2, 110, 305)], fps)
    comprobar("a 1 s ya no es doble", "doble" not in str(m), str(m))

    print("Frontera liviano/pesado")
    m = revision.motivos_de_cruces([cruce(1, 10, 0, tipo="truck", h=63)], fps)
    comprobar("truck a +5 % del corte se marca", "frontera" in str(m), str(m))
    m = revision.motivos_de_cruces([cruce(1, 10, 0, tipo="truck", h=90)], fps)
    comprobar("truck muy por encima no", "frontera" not in str(m), str(m))
    m = revision.motivos_de_cruces([cruce(1, 10, 0, tipo="car", h=60)], fps)
    comprobar("un car en el corte no (la regla no lo mira)", "frontera" not in str(m), str(m))

    print("Confianza baja relativa a la línea")
    linea_baja = [cruce(i, 30 * i, 0, conf=0.10 + 0.01 * (i % 20)) for i in range(1, 101)]
    m = revision.motivos_de_cruces(linea_baja, fps)
    marcados = sum("confianza" in str(v) for v in m.values())
    comprobar("en una línea que cuenta desde 0.10 se marca ~5 %", 1 <= marcados <= 10, f"{marcados} de 100")
    linea_alta = [cruce(i, 30 * i, 0, conf=0.80) for i in range(1, 60)] + [cruce(99, 5000, 0, conf=0.27)]
    m = revision.motivos_de_cruces(linea_alta, fps)
    comprobar("en una línea normal, 0.27 se marca", "confianza" in str(m.get(99, [])), str(m.get(99)))


def de_punta_a_punta():
    print("De punta a punta (base temporal)")
    tmp = Path(tempfile.mkdtemp())
    traffic_db.DB_PATH = tmp / "revision.db"
    traffic_db.init_schema()
    pid = traffic_db.create_project("Revisión de prueba")
    lane = traffic_db.create_lane("prueba", "Carril 1", "line", [[100, 0], [100, 400]], project_id=pid)
    conn = traffic_db.get_connection()
    conn.execute("""INSERT INTO video_jobs (id, original_name, stored_path, project_id,
                    video_start_time, fps, total_frames, status)
                    VALUES (1, 'a.mp4', '/no/existe.mp4', ?, '2026-10-08 07:00:00', 10, 6000, 'done')""", (pid,))
    conn.commit()
    lane_id = lane["id"] if isinstance(lane, dict) else lane
    ids = []
    for i in range(40):
        traffic_db.record_crossing(lane_id, i, "in", "car", 0.8, timestamp=f"2026-10-08 07:{i:02d}:00",
                                   job_id=1, bbox_height=40, bbox_width=70, bbox_x=300, bbox_y=100,
                                   cuadro=600 * i)
    traffic_db.record_crossing(lane_id, 99, "in", "car", 0.8, timestamp="2026-10-08 07:05:00",
                               job_id=1, bbox_height=40, bbox_width=70, bbox_x=302, bbox_y=101,
                               cuadro=3003)
    filas, _ = traffic_db.cruces_para_revision(pid)
    ids = [f["id"] for f in filas]

    def total():
        r = traffic_db.get_interval_counts(pid, 60)
        return sum(b["total"] for l in r["lanes"] for b in l["intervals"])

    def clases():
        r = traffic_db.get_interval_counts(pid, 60)
        out = {}
        for l in r["lanes"]:
            for b in l["intervals"]:
                for k, v in b["by_vehicle_type"].items():
                    out[k] = out.get(k, 0) + v["in"] + v["out"]
        return out

    comprobar("41 cruces al empezar", total() == 41, str(total()))
    cola = revision.cola(pid)
    dobles = [it for it in cola["items"] if any(m["motivo"] == "doble" for m in it["motivos"])]
    comprobar("la cola encuentra el doble fabricado", len(dobles) == 1, str(len(dobles)))

    objetivo = ids[3]
    revision.decidir(pid, "cruce", objetivo, "PESADO")
    comprobar("corregir la clase la cambia en el conteo", clases().get("PESADO") == 1, str(clases()))

    if dobles:
        d = revision.decidir(pid, "cruce", dobles[0]["id"], "descartar")
        comprobar("descartar lo saca del conteo", total() == 40, str(total()))
        comprobar("y ya no está en la cola", all(it["id"] != dobles[0]["id"] for it in revision.cola(pid)["items"]))
        traffic_db.restaurar_descartado(pid, d["descartado"])
        comprobar("restaurar lo devuelve", total() == 41, str(total()))
        vuelto = traffic_db.fila_para_recorte("cruce", dobles[0]["id"])
        comprobar("con el mismo id", vuelto is not None)

    try:
        revision.decidir(pid, "cruce", objetivo, "INVENTADA")
        comprobar("una clase que no existe se rechaza", False)
    except ValueError:
        comprobar("una clase que no existe se rechaza", True)
    try:
        revision.decidir(pid + 1, "cruce", objetivo, "A")
        comprobar("un cruce de otro proyecto se rechaza", False)
    except KeyError:
        comprobar("un cruce de otro proyecto se rechaza", True)


if __name__ == "__main__":
    puras()
    de_punta_a_punta()
    print(f"\n{'TODO BIEN' if fallos == 0 else f'{fallos} FALLOS'}")
    sys.exit(1 if fallos else 0)
