"""
Entrena el clasificador de automovil contra camioneta sobre recortes reales.

Es lo unico de la taxonomia de la empresa que el detector no puede dar. COCO
no tiene la clase "pickup", y su etiqueta `truck` resulto medir el ANGULO y
no el vehiculo: 1.2 % de los livianos en la calzada que va hacia la camara
contra 7.6 % en la que se aleja, la misma via el mismo dia. Eso no se
arregla con un umbral.

    python tools/exportar_recortes.py --proyecto 7 --salida data/recortes
    # etiquetar moviendo archivos a data/recortes/auto y .../camioneta
    python tools/entrenar_clasificador.py --datos data/recortes \\
        --salida models/auto_vs_camioneta.pt

TRES DECISIONES QUE NO SON DE GUSTO, SINO DE LO QUE YA COSTO CARO AQUI
----------------------------------------------------------------------

1. **La separacion es POR HORA, no al azar.** Repartir los recortes al azar
   entre entrenamiento y prueba da una cifra inflada: los vehiculos de una
   misma hora comparten sol, sombra y color de la luz, asi que el modelo
   puede aprender la hora en vez del vehiculo y aun asi acertar. Este
   proyecto ya se quemo con eso: el modelo de vision de NVIDIA dio **36 de
   36 a mediodia y 28 de 40 a las 07:00**, y solo probarlo en otra franja lo
   descubrio. Aqui se entrena con unas horas y se mide con OTRAS.

2. **Se reportan dos cifras, no una.** El acierto por vehiculo y el error de
   COMPOSICION, que es lo que sale en el entregable. Hacen falta las dos
   porque se tapan entre si: un automovil contado como camioneta y una
   camioneta contada como automovil **se cancelan** y la composicion cuadra
   con dos errores dentro. Al reves tambien: la composicion puede irse
   aunque el acierto sea alto, si los errores van todos para el mismo lado.

3. **No se entrena con las clases del detector.** `truck` de COCO no es la
   verdad; es justo lo que se esta tratando de sustituir. Las etiquetas
   salen de mirar los recortes.

El modelo es `mobilenet_v3_small` con pesos de ImageNet (torchvision, de
licencia libre para uso comercial, a diferencia de Ultralytics, que es
AGPL-3.0). Medido: 1 803 recortes por segundo en una GTX 1650, con pico de
0.37 GB. Diez mil recortes por treinta epocas son menos de tres minutos.
"""

import argparse
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

CLASES = ("auto", "camioneta")
# Con --clases entrena cualquier otra separacion con las mismas reglas; la
# primera que la uso fue la de los pesados (autobus, camion, tractocamion,
# tractor sin caja y los livianos que la regla del alto mando a pesado), con
# las etiquetas que dejo la revision sobre el recorte.
# La hora viene en el nombre que puso `exportar_recortes.py`: `..._18h.jpg`.
PATRON_HORA = re.compile(r"_(\d{2})h\.jpg$", re.IGNORECASE)

# Minimos para que la medicion signifique algo. Por debajo la herramienta
# entrena igual pero lo dice: con 20 ejemplos de prueba, un acierto del 95 %
# y uno del 85 % son el mismo dato.
MINIMO_POR_CLASE = 100
MINIMO_PRUEBA = 100


def inventario(carpeta):
    """{clase: {hora: [rutas]}} de lo que hay etiquetado."""
    datos = {c: defaultdict(list) for c in CLASES}
    for c in CLASES:
        d = os.path.join(carpeta, c)
        if not os.path.isdir(d):
            continue
        for n in sorted(os.listdir(d)):
            if not n.lower().endswith((".jpg", ".jpeg", ".png")):
                continue
            m = PATRON_HORA.search(n)
            datos[c][m.group(1) if m else "??"].append(os.path.join(d, n))
    return datos


def partir_por_hora(datos, horas_prueba):
    """Entrena con unas horas y mide con OTRAS. Ver el encabezado."""
    horas = sorted({h for c in CLASES for h in datos[c]})
    if not horas_prueba:
        # Una de cada tres horas para medir, repartidas a lo largo del dia y
        # no las ultimas: la luz de la tarde no representa al dia entero.
        horas_prueba = horas[1::3] or horas[-1:]
    horas_prueba = set(horas_prueba)
    tren, prueba = [], []
    for c, etiqueta in enumerate(CLASES):
        for h, rutas in datos[etiqueta].items():
            (prueba if h in horas_prueba else tren).extend((r, c) for r in rutas)
    return tren, prueba, sorted(horas_prueba), [h for h in horas if h not in horas_prueba]


def informe(verdad, predicho, nombre):
    """Acierto por vehiculo Y error de composicion. Ver el encabezado."""
    n = len(verdad)
    aciertos = sum(1 for a, b in zip(verdad, predicho) if a == b)
    print(f"\n--- {nombre} ({n} recortes) ---")
    print(f"acierto por vehiculo: {100 * aciertos / n:.1f} %")
    print(f"\n{'clase':12} {'reales':>7} {'hallados':>9} {'precision':>10} {'recuerdo':>9}")
    filas = {}
    for c, etiqueta in enumerate(CLASES):
        reales = sum(1 for a in verdad if a == c)
        hallados = sum(1 for b in predicho if b == c)
        ok = sum(1 for a, b in zip(verdad, predicho) if a == c and b == c)
        prec = ok / hallados if hallados else 0.0
        rec = ok / reales if reales else 0.0
        filas[etiqueta] = {"reales": reales, "hallados": hallados,
                           "precision": round(prec, 3), "recuerdo": round(rec, 3)}
        print(f"{etiqueta:12} {reales:>7} {hallados:>9} {prec:>10.3f} {rec:>9.3f}")

    # La cifra del entregable: que porcentaje de cada clase se declara.
    composicion = {}
    print()
    for i, etiqueta in enumerate(CLASES):
        real_pct = 100 * sum(1 for a in verdad if a == i) / n
        dicho_pct = 100 * sum(1 for b in predicho if b == i) / n
        composicion[etiqueta] = (round(dicho_pct, 1), round(real_pct, 1))
        print(f"composicion {etiqueta}: dice {dicho_pct:.1f} % y es {real_pct:.1f} %"
              f"  ->  {abs(dicho_pct - real_pct):.1f} puntos")
    print("(el acierto por vehiculo y la composicion NO dicen lo mismo: dos "
          "errores\n opuestos se cancelan en la composicion y no en el acierto)")
    # Con dos clases la cifra de siempre es la de la segunda (camioneta).
    dicho, real = composicion[CLASES[-1]] if len(CLASES) == 2 else (None, None)
    return {"n": n, "acierto": round(aciertos / n, 4), "clases": filas,
            "composicion": composicion,
            "composicion_dicha_pct": dicho, "composicion_real_pct": real,
            "composicion_puntos": round(max(abs(d - r) for d, r in composicion.values()), 1)}


def humo():
    """Recortes sinteticos para comprobar que la tuberia aprende.

    Sirve para no descubrir un fallo del entrenamiento DESPUES de etiquetar
    dos mil recortes a mano. Las imagenes son ruido; lo unico que separa a
    las dos clases es la PROPORCION del recorte, igual que en la realidad
    una camioneta es mas alta respecto a su ancho que un automovil. Si la
    tuberia no saca de aqui un buen acierto, esta rota.

    Asi se encontro que `Resize((px, px))` aplastaba el recorte y borraba
    justo esa senal: con el recorte aplastado el modelo se rendia y decia
    siempre la misma clase.
    """
    import shutil
    import tempfile
    import numpy as np
    from PIL import Image
    base = os.path.join(tempfile.gettempdir(), "humo_recortes")
    shutil.rmtree(base, ignore_errors=True)
    np.random.seed(0)
    for clase, (w, h) in (("auto", (220, 130)), ("camioneta", (215, 175))):
        d = os.path.join(base, clase)
        os.makedirs(d, exist_ok=True)
        for hora in ("12", "13", "14", "15", "16", "17"):
            for i in range(40):
                luz = 50 + int(hora) * 7          # la luz cambia con la hora
                ww = w + np.random.randint(-25, 25)
                hh = h + np.random.randint(-15, 15)
                img = np.clip(np.full((hh, ww, 3), luz, np.int16)
                              + np.random.randint(-25, 25, (hh, ww, 3)),
                              0, 255).astype(np.uint8)
                Image.fromarray(img).save(
                    os.path.join(d, f"{hora}{i:03d}_car_{hh}x{ww}_{hora}h.jpg"))
    print(f"prueba de humo: recortes sinteticos en {base}")
    return base


def main():
    global CLASES
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--datos", default=None,
                    help="carpeta con una subcarpeta por clase (auto/ y camioneta/)")
    ap.add_argument("--clases", default=",".join(CLASES),
                    help="subcarpetas a usar como clases, separadas por coma")
    ap.add_argument("--minimo-prueba-clase", type=int, default=20,
                    help="ejemplos minimos de cada clase en las horas de prueba")
    ap.add_argument("--salida", default="models/auto_vs_camioneta.pt")
    ap.add_argument("--epocas", type=int, default=30)
    ap.add_argument("--lote", type=int, default=64)
    ap.add_argument("--px", type=int, default=128)
    ap.add_argument("--horas-prueba", default=None,
                    help="horas reservadas para medir, separadas por coma "
                         "(p. ej. 13,17,21). Por omisión una de cada tres.")
    ap.add_argument("--semilla", type=int, default=0)
    ap.add_argument("--humo", action="store_true",
                    help="prueba la tubería con recortes sintéticos, sin "
                         "etiquetar nada: comprueba que aprende cuando la "
                         "señal existe")
    a = ap.parse_args()
    CLASES = tuple(c.strip() for c in a.clases.split(",") if c.strip())

    if a.humo:
        CLASES = ("auto", "camioneta")
        a.datos = humo()
    if not a.datos:
        ap.error("hace falta --datos (o --humo para la prueba sintética)")

    datos = inventario(a.datos)
    for c in CLASES:
        n = sum(len(v) for v in datos[c].values())
        print(f"{c:12} {n:>5} recortes en {len(datos[c])} horas")
        if n < MINIMO_POR_CLASE:
            print(f"  AVISO: menos de {MINIMO_POR_CLASE}; la medida va a ser ruido")
    if not any(sum(len(v) for v in datos[c].values()) for c in CLASES):
        sys.exit(f"No hay nada etiquetado en {a.datos} ({', '.join(CLASES)})")

    horas_prueba = ([h.strip() for h in a.horas_prueba.split(",")]
                    if a.horas_prueba else None)
    tren, prueba, h_prueba, h_tren = partir_por_hora(datos, horas_prueba)
    print(f"\nentrena con las horas {', '.join(h_tren)}  ({len(tren)} recortes)")
    print(f"mide con las horas    {', '.join(h_prueba)}  ({len(prueba)} recortes)")
    if not prueba:
        sys.exit("No quedaron recortes para medir. Etiqueta más de una hora.")
    if len(prueba) < MINIMO_PRUEBA:
        print(f"AVISO: menos de {MINIMO_PRUEBA} recortes de prueba; la cifra "
              "no separa un modelo bueno de uno regular.")

    # Si las horas de prueba traen una sola clase, el acierto sale del 100 %
    # diciendo siempre lo mismo. La prueba de humo cayo justo ahi y el
    # script lo dio por bueno, asi que ahora se para: una medida que no
    # puede fallar no es una medida.
    hay = Counter(y for _, y in prueba)
    flacas = [CLASES[c] for c in range(len(CLASES)) if hay[c] < a.minimo_prueba_clase]
    if flacas:
        reparto = {CLASES[c]: hay[c] for c in range(len(CLASES))}
        print()
        print(f"Las horas de prueba solo traen {reparto}.")
        sys.exit(
            f"Con menos de {a.minimo_prueba_clase} ejemplos de {', '.join(flacas)} en la prueba, el "
            "acierto se puede\nsacar diciendo siempre la otra clase, y entonces "
            "no mide nada. Etiqueta esa\nclase en mas horas, o elige otras con "
            "--horas-prueba.")

    import torch
    import torchvision
    from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler
    from torchvision import transforms
    from PIL import Image

    random.seed(a.semilla)
    torch.manual_seed(a.semilla)
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"\nentrenando en {dev}")

    # Aumentos suaves y del tipo que de verdad varia entre un cruce y otro:
    # la luz, un poco de encuadre, el lado. Nada que invente siluetas.
    norm = transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])

    class Encajar:
        """Lleva el recorte a un cuadrado SIN deformarlo, rellenando.

        `Resize((px, px))` a secas lo aplasta, y con eso se pierde la
        proporcion ancho/alto — que es justo una de las senales que separan
        una camioneta de un automovil, y la misma que ya distingue a la moto
        en la regla del alto. La prueba de humo lo destapo: con el recorte
        aplastado, las dos clases sinteticas se volvian identicas y el
        modelo se rendia diciendo siempre la misma.
        """

        def __init__(self, px):
            self.px = px

        def __call__(self, img):
            w, h = img.size
            e = self.px / max(w, h)
            img = img.resize((max(1, int(w * e)), max(1, int(h * e))))
            fondo = Image.new("RGB", (self.px, self.px), (114, 114, 114))
            fondo.paste(img, ((self.px - img.size[0]) // 2,
                              (self.px - img.size[1]) // 2))
            return fondo

    tr_tren = transforms.Compose([
        Encajar(a.px),
        transforms.ColorJitter(0.3, 0.3, 0.3, 0.05),
        transforms.RandomAffine(degrees=5, translate=(0.05, 0.05), scale=(0.9, 1.1)),
        transforms.RandomHorizontalFlip(),
        transforms.ToTensor(), norm])
    tr_prueba = transforms.Compose([
        Encajar(a.px), transforms.ToTensor(), norm])

    class Recortes(Dataset):
        def __init__(self, items, tr):
            self.items, self.tr = items, tr

        def __len__(self):
            return len(self.items)

        def __getitem__(self, i):
            ruta, y = self.items[i]
            return self.tr(Image.open(ruta).convert("RGB")), y

    # Clases desbalanceadas: en la via hay muchos mas automoviles que
    # camionetas, y sin esto el modelo aprende a decir siempre "automovil"
    # y acierta el 70 % sin haber aprendido nada.
    cuenta = Counter(y for _, y in tren)
    pesos = [1.0 / max(1, cuenta[y]) for _, y in tren]
    cargador = DataLoader(
        Recortes(tren, tr_tren), batch_size=a.lote,
        sampler=WeightedRandomSampler(pesos, len(tren), replacement=True),
        num_workers=0)
    cargador_prueba = DataLoader(Recortes(prueba, tr_prueba),
                                 batch_size=a.lote, num_workers=0)

    m = torchvision.models.mobilenet_v3_small(
        weights=torchvision.models.MobileNet_V3_Small_Weights.IMAGENET1K_V1)
    m.classifier[3] = torch.nn.Linear(m.classifier[3].in_features, len(CLASES))
    m = m.to(dev)
    opt = torch.optim.AdamW(m.parameters(), lr=1e-3, weight_decay=1e-4)
    plan = torch.optim.lr_scheduler.CosineAnnealingLR(opt, a.epocas)
    crit = torch.nn.CrossEntropyLoss(label_smoothing=0.05)

    for e in range(a.epocas):
        m.train()
        suma = 0.0
        for x, y in cargador:
            x, y = x.to(dev), y.to(dev)
            opt.zero_grad()
            p = crit(m(x), y)
            p.backward()
            opt.step()
            suma += p.item()
        plan.step()
        if (e + 1) % 5 == 0 or e == a.epocas - 1:
            print(f"  epoca {e + 1:>3}/{a.epocas}  perdida {suma / len(cargador):.4f}")

    m.eval()
    verdad, predicho = [], []
    with torch.no_grad():
        for x, y in cargador_prueba:
            verdad += y.tolist()
            predicho += m(x.to(dev)).argmax(1).cpu().tolist()

    metricas = informe(verdad, predicho, "HORAS NO VISTAS AL ENTRENAR")

    os.makedirs(os.path.dirname(a.salida) or ".", exist_ok=True)
    torch.save({"modelo": m.state_dict(), "clases": CLASES, "px": a.px,
                "horas_entrenamiento": h_tren, "horas_prueba": h_prueba,
                "metricas": metricas}, a.salida)
    with open(os.path.splitext(a.salida)[0] + ".json", "w", encoding="utf-8") as fh:
        json.dump({"clases": CLASES, "px": a.px, "epocas": a.epocas,
                   "horas_entrenamiento": h_tren, "horas_prueba": h_prueba,
                   "recortes_entrenamiento": len(tren), "metricas": metricas},
                  fh, indent=1, ensure_ascii=False)
    print(f"\nmodelo -> {a.salida}")
    if a.humo:
        ok = metricas["acierto"] >= 0.75
        print(f"\nprueba de humo: {'PASA' if ok else 'FALLA'} "
              f"(acierto {metricas['acierto']:.2f}, se pide 0.75)")
        return 0 if ok else 1
    print("NO integrar al motor sin mirar antes los recortes que fallaron.")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
