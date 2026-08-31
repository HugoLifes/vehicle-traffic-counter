# Por qué el detector está configurado así

Los tres parámetros que deciden cuántos vehículos se ven —modelo, `imgsz` y
la banda de detección— no vienen de una recomendación genérica. Salieron de
medir sobre 2 minutos del video real (08:00, calle pino), contando **cruces
de punta a punta**, no detecciones sueltas: detectar más cajas no sirve de
nada si no se traducen en conteos.

## El punto de partida

El usuario reportó que se perdían vehículos, sobre todo **al pasar cerca de
la cámara**. Se comprobó cruzando dos señales independientes: la sustracción
de fondo encuentra lo que se *mueve* sin saber qué es, y YOLO encuentra lo
que *reconoce*. Un blob en movimiento del tamaño de un vehículo que ninguna
caja de YOLO cubre es, casi siempre, un vehículo perdido
(`tools/diagnostico_fallos.py`).

El resultado fue peor de lo esperado: con la configuración original, en un
cuadro de las 08:00 con 8 vehículos visibles sobre la vía, YOLO reportaba
**0**. Incluso bajando el umbral a 0.05 y quitando el filtro de clases,
apenas devolvía 5 cajas, todas de 10-30 px.

La causa es la geometría del encuadre: **más de la mitad del cuadro es
terreno sin tránsito**, y toda la vía cabe en una franja de unos 60 px de
alto. A `imgsz` 640 sobre el cuadro completo, al vehículo le tocaban 13-18
píxeles de alto — por debajo de lo que el modelo puede resolver.

## Lo que se midió

Cruces contados en los mismos 2 minutos, con el mismo tracker y los mismos
carriles. Solo cambia el detector:

| Configuración | Cruces | ms/cuadro |
|---|---|---|
| yolov8n, imgsz 640, cuadro completo *(la original)* | 75 | 14 |
| yolov8m, imgsz 640, cuadro completo | 98 | 45 |
| yolov8m, imgsz 1280, cuadro completo | 110 | 147 |
| yolov8s, imgsz 1280, **banda** | **107** | **24** |
| yolov8m, imgsz 1280, banda | 108 | 49 |

Y el ancho de la banda, con yolov8m a 1280:

| Banda | Cruces | ms/cuadro |
|---|---|---|
| y 130-235 (margen justo) | 107 | 56 |
| y 110-265 | 112 | 75 |
| y 90-290 | 110 | 92 |
| cuadro completo | 110 | 153 |

## Las tres decisiones

**`model_path: yolov8s.pt`** — el salto de `n` a `s` es el cambio más grande
de todos. `yolov8m` da 108 cruces contra 107 del `s`: un cruce más al doble
de costo, así que no se justifica. `yolov8l` resultó a la vez más lento y
*peor* que `m` (2.9 det/cuadro contra 3.1), y quedó descartado.

**`input_size: 1280`** — con el video a 640×360, subir `imgsz` por encima de
la resolución nativa sí ayuda, porque el modelo trabaja sobre una versión
ampliada donde el vehículo ocupa más celdas de la rejilla de predicción. Es
lo que separa 98 cruces de 110.

**`band`** — detectar solo en la franja donde están los carriles. Contra lo
que parece, **no es una mejora de exactitud sino de velocidad**: da
prácticamente los mismos cruces que el cuadro completo a 1280 (107 contra
110) en un tercio del tiempo. Es lo que vuelve asequible el `imgsz` alto.

La banda se deriva de los carriles ya calibrados, no se escribe a mano, así
que sigue a la calibración si alguien mueve las líneas. El margen es
deliberadamente amplio (15 % del alto del cuadro por lado): un tráiler cerca
de la cámara es mucho más alto que la línea de conteo, y recortar a ras de
la línea perdería justo el vehículo grande — que es el caso que originó todo
esto. Si los carriles llegaran a cubrir casi todo el cuadro, la banda se
desactiva sola.

## Costo

De 14 a 24 ms por cuadro: un video de 10 minutos pasa de ~2 a ~3.6 minutos
de proceso. Un aforo de 24 h (144 videos) pasa de unas 5 a unas 9 horas.

## Lo que esto NO arregla

Sigue habiendo subconteo. 107 cruces es mejor que 75, pero no hay un conteo
manual con el que comparar, así que **no se sabe cuál es el número real**.
Las tres referencias automáticas disponibles siguen sin coincidir entre sí.
Y nada de esto rescata el material nocturno, donde el problema es pérdida de
detalle por bitrate y no capacidad del modelo (ver
[REQUISITOS_CAMARA.md](REQUISITOS_CAMARA.md)).

La solución de fondo sigue siendo el encuadre y la cámara: con el vehículo a
54 px en vez de 18, ninguno de estos ajustes haría falta.

## Herramientas

```bash
# Ver lo que ve el detector, como imagen
python tools/inspeccionar.py --job 164 --modelo models/yolov8s.pt --imgsz 1280 --banda

# Medir dónde falla dentro del cuadro, sin conteo manual
python tools/diagnostico_fallos.py --job 164 --segundos 90
```
