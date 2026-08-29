# Requisitos de cámara y video

Todo lo que sigue está medido sobre el aforo de 24 horas de la cámara "2ta"
(calle pino, Chihuahua), no tomado de una recomendación genérica. Ese
material sirvió como caso real y dejó claro dónde está el límite.

## Lo que se midió en el material actual

| | Día (08:00) | Noche (22:00) |
|---|---|---|
| Resolución | 640×360 | 640×360 |
| Bitrate | 470 kb/s | **167 kb/s** |
| Nitidez de la vía (varianza del laplaciano) | 11 827 | **1 428** |
| Alto del vehículo en la línea de conteo | 18 px | 13 px |
| Confianza media del detector | 0.48 | **0.36** |
| Detecciones por debajo de 0.4 | 43 % | **70 %** |

Y el efecto sobre el conteo, siguiendo la cadena completa en 2 minutos:

| | Detecciones | → Tracks | → Cruces contados |
|---|---|---|---|
| Día 08:00 | 2 022 | 126 | **75** |
| Noche 22:00 | 1 084 | 45 | **4** |

De noche solo el **9 %** de los tracks llega a cruzar una línea, contra el
60 % de día. Y los tracks nocturnos duran más cuadros que los diurnos, lo
que indica que el detector se está enganchando a cosas **quietas**
(vehículos estacionados, estructuras iluminadas) mientras se le escapa el
tránsito en movimiento.

## El problema de fondo no es la oscuridad

Conviene descartarlo porque es la explicación intuitiva y es falsa: el
brillo medio de la vía **sube** de noche (165 contra 113 de día) por las
luminarias. Lo que se pierde es el detalle, no la luz:

- El bitrate cae a un tercio, así que el compresor descarta justo la
  textura fina que distingue un vehículo del asfalto.
- La ganancia alta del sensor mete ruido.
- El glare de faros y luminarias satura zonas completas.

Un vehículo nocturno queda en unos **21×23 px de borrón**. Ningún ajuste
de umbral recupera información que el compresor ya tiró.

## Qué hace falta para que esto funcione bien

El detector necesita alrededor de **40 px de alto por vehículo** para
trabajar con holgura. Hoy hay 18. De ahí sale todo lo demás:

| Resolución | Alto del vehículo en la línea | Sirve |
|---|---|---|
| 640×360 (actual) | 18 px | No — al límite, y de noche se cae |
| 1280×720 | ~36 px | Mínimo aceptable |
| **1920×1080** | **~54 px** | **Recomendado** |
| 2560×1440 | ~72 px | Cómodo, más carga para el Jetson |

**Bitrate:** para 1080p H.264 con detalle utilizable hacen falta
**4–8 Mb/s**, entre 9 y 48 veces lo que trae el material actual. Es tan
determinante como la resolución: 1080p a bitrate bajo vuelve al mismo
problema con más píxeles vacíos.

### Al elegir la cámara para el Jetson

- **1080p mínimo**, H.264 o H.265, con bitrate configurable a 4 Mb/s o más.
- **Modo nocturno real**: infrarrojo con iluminador, o sensor tipo
  *starlight* / *low-light*. Una cámara que de noche solo sube la ganancia
  reproduce exactamente el problema medido aquí.
- **WDR / HDR**, para que el glare de las luminarias no sature la escena.
- **15 fps es suficiente** para contar; conviene gastar el ancho de banda
  en resolución y bitrate antes que en cuadros por segundo.
- **Encuadre**: cuanto más cerca esté la línea de conteo, más grande sale
  el vehículo. Vale tanto como subir la resolución, y es gratis. Evitar
  que la vía quede en una franja de 15 px al fondo del cuadro, como pasa
  en el material actual.

## Cómo leer los datos del aforo ya levantado

- **06:00–19:00**: utilizable.
- **20:00–05:00**: no es una medición. El sistema reporta 13–28 vehículos
  por hora donde el video muestra tránsito continuo. Esos números no deben
  ir a un informe como si fueran conteos.
