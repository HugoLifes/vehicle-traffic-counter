"""
Lectura del video un paso adelante de la detección.

En el Orin, con TensorRT, un cuadro del frontal costaba 72 ms y se hacía todo
en fila: leer (10.5 ms en el CPU), recortar y reducir la franja (10 ms en el
CPU) y detectar (26 ms en la GPU). Mientras el CPU leía, la GPU esperaba, y
al revés. Este lector hace lo del CPU para el cuadro siguiente en un hilo
aparte mientras la GPU detecta el actual.

No cambia ningún píxel: el mismo VideoCapture lee los mismos cuadros en el
mismo orden, y la reducción es la de la letterbox de ultralytics
(`VehicleDetector.preparar`). cv2 suelta el GIL al decodificar y al reducir,
así que el hilo sí corre en paralelo.
"""

import logging
import queue
import threading
from typing import Callable, Optional

_FIN = object()


class LectorAdelantado:
    def __init__(self, cap, preparar: Optional[Callable] = None, adelanto: int = 3):
        # 3 cuadros de 2560x1440 son ~33 MB: el Orin tiene 8 GB compartidos.
        self._cap = cap
        self._preparar = preparar
        self._cola: "queue.Queue" = queue.Queue(maxsize=adelanto)
        self._parar = threading.Event()
        self._hilo = threading.Thread(target=self._leer, name="lector-video", daemon=True)
        self._hilo.start()

    def _poner(self, item) -> bool:
        while not self._parar.is_set():
            try:
                self._cola.put(item, timeout=0.2)
                return True
            except queue.Full:
                continue
        return False

    def _leer(self):
        try:
            while not self._parar.is_set():
                ok, cuadro = self._cap.read()
                if not ok:
                    break
                preparado = None
                if self._preparar is not None:
                    try:
                        preparado = self._preparar(cuadro)
                    except Exception:
                        # Sin preparar, el detector lo hace él mismo: más
                        # lento, igual de correcto.
                        logging.exception("No se pudo preparar el cuadro en el lector")
                if not self._poner((cuadro, preparado)):
                    return
        except Exception:
            logging.exception("El lector de video falló")
        finally:
            self._poner(_FIN)

    def read(self):
        """(ok, cuadro, preparado), como cap.read() más lo ya preparado."""
        item = self._cola.get()
        if item is _FIN:
            self._cola.put(_FIN)  # que otra lectura también vea el final
            return False, None, None
        return True, item[0], item[1]

    def cerrar(self):
        """Detiene el hilo ANTES de soltar el VideoCapture: soltarlo mientras
        el hilo lee tumba el proceso."""
        self._parar.set()
        while True:
            try:
                self._cola.get_nowait()
            except queue.Empty:
                break
        self._hilo.join(timeout=10)
