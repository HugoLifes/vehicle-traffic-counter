"""
La hora de cada cuadro, tomada del archivo y no de cuadro / fps.

Las cámaras de los aforos direccionales de Juárez (Cruce Gómez Morín,
7 y 8-oct-2026) declaran 15 cuadros/s y en modo nocturno graban a 10: el
archivo dura sus 10 minutos con 6 059 cuadros, no 9 001. Con la hora calculada
como cuadro / 15, cada video se comprimía en sus primeros 6 min 44 s: lo de los
últimos tres minutos se apuntaba en el cuarto de hora anterior, la cobertura
del cuarto salía en 67 % y el aviso decía "archivo cortado" de un video
completo. 52 de los 90 videos de ese aforo. El reloj de la imagen lo confirma:
el cuadro 4 500 del video de las 06:40:08 dice 06:47:34 (446 s, 10.1
cuadros/s), no 06:45:08.

El contenedor sí trae el instante de cada cuadro (`CAP_PROP_POS_MSEC`): en ese
video, el cuadro 2 000 está en 198.1 s. Se usa ese, y cuadro / fps solo donde
el archivo no lo da.
"""

from typing import List, Optional

import cv2

# Diferencia con lo declarado a partir de la cual se cree a lo medido. Por
# debajo es redondeo del contenedor (29.97 contra 30).
TOLERANCIA_FPS = 0.05


def medir_fps(ruta, declarado: float, cuadros: int = 61) -> float:
    """Cuadros por segundo de verdad al principio del archivo.

    Lo usan el rastreador y el direccional, que miden huecos y olvidos en
    cuadros pensando en segundos. La hora de cada cuadro no sale de aquí sino
    de `RelojVideo`, porque la cámara puede cambiar de ritmo a medio video
    (al pasar a modo nocturno)."""
    cap = cv2.VideoCapture(str(ruta))
    tiempos = []
    try:
        for _ in range(cuadros):
            ok, _cuadro = cap.read()
            if not ok:
                break
            tiempos.append(cap.get(cv2.CAP_PROP_POS_MSEC))
    finally:
        cap.release()
    if len(tiempos) < 11 or tiempos[-1] <= tiempos[0]:
        return declarado
    medido = (len(tiempos) - 1) * 1000.0 / (tiempos[-1] - tiempos[0])
    if declarado and abs(medido - declarado) <= TOLERANCIA_FPS * declarado:
        return declarado
    return medido


class RelojVideo:
    """Segundo de cada cuadro desde el inicio del archivo, en el orden en que
    se leen. Con un instante que no avanza (contenedor sin tiempos, o que
    devuelve 0) se sigue a 1 / fps desde el último bueno."""

    def __init__(self, fps: float):
        self.fps = fps or 25.0
        self._segundos: List[float] = []
        self._base: Optional[float] = None

    def anotar(self, ms: Optional[float]):
        anterior = self._segundos[-1] if self._segundos else None
        s = None
        if ms is not None and ms >= 0:
            if self._base is None:
                self._base = ms / 1000.0
            s = ms / 1000.0 - self._base
        if anterior is not None and (s is None or s <= anterior):
            s = anterior + 1.0 / self.fps
        self._segundos.append(s if s is not None else 0.0)

    def segundos(self, cuadro: int) -> float:
        if 0 <= cuadro < len(self._segundos):
            return self._segundos[cuadro]
        if self._segundos:
            return self._segundos[-1] + (cuadro - len(self._segundos) + 1) / self.fps
        return cuadro / self.fps

    def __len__(self) -> int:
        return len(self._segundos)

    @property
    def duracion(self) -> float:
        return self._segundos[-1] + 1.0 / self.fps if self._segundos else 0.0


def tiempos_del_archivo(ruta, fps: float) -> RelojVideo:
    """El reloj de un archivo entero, sin detectar nada (para corregir lo ya
    contado). A 640x360 son unos segundos por video de 10 minutos."""
    cap = cv2.VideoCapture(str(ruta))
    reloj = RelojVideo(fps)
    try:
        while True:
            ok, _cuadro = cap.read()
            if not ok:
                break
            reloj.anotar(cap.get(cv2.CAP_PROP_POS_MSEC))
    finally:
        cap.release()
    return reloj
