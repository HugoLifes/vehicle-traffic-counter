# Calibrador de campo

Página para usar en el celular, junto a la vía, **antes** de dejar una cámara
grabando un día entero. Tres herramientas:

- **Planear**: con la altura de la cámara, la distancia a cada carril, la
  resolución y el lente, estima qué tan grande se va a ver un automóvil
  (modelo de cámara estenopeica, auto de 1.5 m de alto y 1.8 m de ancho) y
  qué cambiar si el carril lejano queda corto.
- **Medir foto**: sobre una captura real de la cámara, se tocan el techo y la
  llanta de un vehículo y da su alto en píxeles; además mide brillo y nitidez
  (varianza del laplaciano, la misma medida que la plataforma). Todo en el
  navegador: la imagen no sale del teléfono.
- **Lista**: los puntos que costaron un aforo cada vez que se olvidaron, y un
  resumen para copiar y mandar con el minuto de prueba.

La escala de píxeles es la medida en los aforos de la empresa contra conteo
manual (src/engine/diagnostico_encuadre.py): 40 px con holgura, 33 px bueno,
20 px mínimo.

`calibrador_campo.src.html` es la fuente; `calibrador_campo.html` es la misma
página con la imagen de ejemplo incrustada, que es la que se publica.
