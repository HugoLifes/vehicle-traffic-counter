"""
Clase de los pesados sobre su recorte, con un modelo propio que corre en el
equipo.

Hasta ahora la clase fina de los pesados (autobús, camión, tractocamión,
tractor sin caja) salía de revisar cada recorte con un modelo de visión de la
API de NVIDIA (`tools/revisar_pesados.py`). Funciona, pero depende de
internet y de un catálogo que cambia sin aviso, y la revisión se pierde al
recontar un video. Este modelo aprendió de esas mismas etiquetas
(`tools/entrenar_clasificador.py --clases BUS,SEMI,TRUCK,TRACTOR,CAR`) y
clasifica en el instante del cruce: unas decenas de inferencias por minuto de
video, nada frente a las 1 200 del detector.

No reemplaza a la regla del alto: decide QUÉ pesado es solo cuando la regla
ya dijo que es pesado (ver traffic_db.get_interval_counts). La frontera
liviano/pesado es la validada contra el conteo manual.
"""
import logging
from typing import Optional, Tuple

import cv2
import numpy as np

# Etiqueta del modelo -> clase de la empresa.
A_CLASE = {"BUS": "B", "TRUCK": "C", "SEMI": "T-S", "TRACTOR": "TRACTOR", "CAR": "A"}
# Lo que la regla del alto (src/engine/clasificacion.py) entrega como pesado.
# Solo ahí manda el modelo; en lo demás la regla, que es la validada.
CLASES_PESADAS_REGLA = ("B", "C", "PESADO")
# Por debajo de esta probabilidad el modelo duda y se queda la regla.
PROB_MINIMA_MODELO = 0.5
# El recorte con que se etiquetó y entrenó (recortes_sin_posicion.py): la caja
# más un margen del 15 % de su lado mayor. Clasificar otro encuadre sería
# medir con una regla distinta de la calibrada.
MARGEN = 0.15


def recortar(cuadro: np.ndarray, bbox) -> Optional[np.ndarray]:
    x1, y1, x2, y2 = [float(v) for v in bbox]
    m = int(MARGEN * max(x2 - x1, y2 - y1))
    alto, ancho = cuadro.shape[:2]
    y0, y1_ = max(0, int(y1) - m), min(alto, int(y2) + m)
    x0, x1_ = max(0, int(x1) - m), min(ancho, int(x2) + m)
    if y1_ - y0 < 8 or x1_ - x0 < 8:
        return None
    return cuadro[y0:y1_, x0:x1_]


class ClasificadorPesados:
    def __init__(self, ruta: str, device: Optional[str] = None):
        import torch
        import torchvision
        datos = torch.load(ruta, map_location="cpu")
        self.clases = list(datos["clases"])
        self.px = int(datos["px"])
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        m = torchvision.models.mobilenet_v3_small(weights=None)
        m.classifier[3] = torch.nn.Linear(m.classifier[3].in_features, len(self.clases))
        m.load_state_dict(datos["modelo"])
        self.modelo = m.eval().to(self.device)
        self._torch = torch
        self._media = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
        self._desv = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)
        logging.info(f"Clasificador de pesados {ruta}: {self.clases} a {self.px} px")

    def _preparar(self, recorte_bgr: np.ndarray):
        """Exactamente Encajar() del entrenamiento, con PIL: al cuadrado SIN
        deformar, rellenando con gris 114. Aplastar el recorte borra la
        proporción, que es justo la señal que separa un tractocamión de un
        camión; y reducir con otra interpolación que la del entrenamiento
        mueve las probabilidades justo en los casos frontera."""
        from PIL import Image
        img = Image.fromarray(cv2.cvtColor(recorte_bgr, cv2.COLOR_BGR2RGB))
        w, h = img.size
        e = self.px / max(w, h)
        img = img.resize((max(1, int(w * e)), max(1, int(h * e))))
        fondo = Image.new("RGB", (self.px, self.px), (114, 114, 114))
        fondo.paste(img, ((self.px - img.size[0]) // 2, (self.px - img.size[1]) // 2))
        t = self._torch.from_numpy(np.asarray(fondo).copy()).permute(2, 0, 1).float() / 255.0
        return (t - self._media) / self._desv

    def clasificar(self, cuadro: np.ndarray, bbox) -> Optional[Tuple[str, float]]:
        """(clase de la empresa, probabilidad) o None si no hay recorte."""
        rec = recortar(cuadro, bbox)
        if rec is None:
            return None
        with self._torch.no_grad():
            x = self._preparar(rec).unsqueeze(0).to(self.device)
            p = self._torch.softmax(self.modelo(x), dim=1)[0].cpu()
        i = int(p.argmax())
        return A_CLASE.get(self.clases[i], self.clases[i]), float(p[i])
