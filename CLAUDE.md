# Contexto del proyecto

Sistema de **aforo vehicular** para una empresa de estudios de tránsito en
Chihuahua, México. Procesa video grabado en campo y produce conteos por
intervalos (15 min por omisión), factor de hora pico y composición
vehicular. Destino final: un **NVIDIA Jetson Orin Nano** que procesa video
— nunca graba.

El material real es de una intersección en **Ciudad Juárez**, cámara "2ta",
24 horas continuas en segmentos de 10 minutos.

Todo el código, los comentarios y los mensajes de commit van **en español**.

---

## Lo que hay que saber antes de tocar nada

### 1. El límite del sistema es el tamaño del vehículo en píxeles, no el software

Medido sobre el material real, no estimado:

| | Calzada cercana | Calzada del fondo |
|---|---|---|
| Alto del vehículo | 36 px | **14 px** |
| Confianza media | 0.81 | **0.55** |
| Cruces bajo 20 px | 0 % | **89 %** |

El detector necesita unos **40 px de alto** para trabajar con holgura. El
video es de 640×360 a 167–470 kb/s. **La información no está en el
archivo**: ningún ajuste de modelo, umbral o zona la recupera.

Ya se probó y descartó **SAHI** (inferencia por rebanadas, la técnica
estándar para objetos pequeños): 2.4 detecciones por cuadro contra 2.2, a
entre 2 y 6 veces el costo. No aporta aquí.

La solución real es la cámara y el encuadre — está documentado en
[docs/REQUISITOS_CAMARA.md](docs/REQUISITOS_CAMARA.md) con precios en
México. **No re-investigues esto**, ya está hecho.

### 2. Mirar el cuadro antes de concluir

Semanas de métricas agregadas no revelaron lo que apareció al mirar un solo
cuadro: 8 vehículos visibles y 0 detectados. **Antes de sacar conclusiones
sobre la escena a partir de promedios, mira la imagen.**

```bash
python tools/inspeccionar.py --job N --banda
```

Genera un PNG que se puede abrir con la herramienta Read. Las
herramientas leen el modelo y el imgsz de `configs/platform.yaml`, así que
siempre diagnostican con la misma configuración que cuenta producción.

### 3. No re-derivar la geometría de la escena

Ya está medida sobre 126 trayectorias reales:

- **Dos corredores, ambos horizontales**: este (calzada cercana) y oeste
  (calzada del fondo). **No hay tránsito norte-sur.** Lo que a ojo parece
  ir "de abajo hacia arriba" es la perspectiva: el vehículo se aleja de la
  cámara mientras avanza en horizontal.
- Las líneas de conteo van a **90°** (verticales).
- Alto del corredor este: y 187–203 en x=200; y 212–263 en x=600.
- Alto del corredor oeste: y 179–180 en x=200; y 189–192 en x=600.

```bash
python tools/trayectorias.py --job N --minutos 3
```

---

## Trampas que ya costaron caro

Cada una de estas produjo daño real. Están arregladas; se documentan para
que no se reintroduzcan.

**El contador usaba el centro geométrico de la caja.** Una línea de conteo
es una marca sobre el asfalto y el vehículo la cruza con las llantas. Con
el centro, el punto probado flota ~10 px sobre el suelo, en un corredor que
mide 15. Una línea bien trazada contaba 4 vehículos donde había 30. Ahora
se usa el centro del borde inferior (`src/counter.py`), el mismo criterio
que usan las zonas (`src/engine/zones.py::_punto_de_apoyo`). **Que ambos
usen el mismo punto no es casualidad — es el arreglo.**

**Borrar un proyecto destruía los videos originales del usuario.** Los
`video_jobs` pueden estar registrados *en su sitio*, con `stored_path`
apuntando a la carpeta del usuario en vez de a una copia. El borrado en
cascada eliminó 144 grabaciones originales. Ahora solo se borran archivos
dentro de `data/uploads`. **Nunca borrar archivos que la plataforma no
copió ella misma.**

**Valores de configuración que no se leían.** `input_size`,
`iou_threshold`, `use_tensorrt` y `half_precision` existían en
`platform.yaml` y en el detector, pero `VideoJobProcessor._get_detector`
no los pasaba: se podían cambiar sin ningún efecto. Al agregar una opción
nueva al detector, **verificar que el procesador la lea de verdad.**

**Detener la cola cambiando el estado en la base no la detenía.** La cola
vive en memoria. Se comprueba el estado en `_process_job`, que es el único
punto por el que pasa cualquier trabajo.

**Reprocesar duplicaba los conteos.** `crossings.job_id` permite borrar los
cruces previos de un video antes de volver a contarlo.

**Una zona mal dibujada recorta el conteo sin dar error.** Medido: 107 → 36
cruces con polígonos puestos a ojo. El procesador avisa en el log cuando el
filtro descarta más del 40 % de las detecciones.

---

## Configuración actual y por qué

`configs/platform.yaml` — cada valor está medido, no elegido por defecto.
El razonamiento completo está en [docs/DETECCION.md](docs/DETECCION.md).

- **`yolov8s`** y no `yolov8n`: 75 → 107 cruces en 2 min. `yolov8m` da 108
  al doble de costo; `yolov8l` es más lento *y* peor.
- **`input_size: 1280`** aunque el video sea de 640×360: el modelo trabaja
  sobre una versión ampliada donde el vehículo ocupa más celdas.
- **`band`**: detectar solo en la franja de la vía. No mejora la exactitud
  sino la velocidad — mismos cruces que el cuadro completo en un tercio del
  tiempo, y eso es lo que vuelve asequible el `imgsz` alto.
- **`confidence_threshold: 0.25`** — valor de la PT-914 del IMT.
- **`iou_threshold: 0.5`** y no 0.7: medido, 0.7 deja 29 % más cajas
  duplicadas.

---

## Arquitectura en una pantalla

```
serve.py → src/api/app.py (FastAPI) → web/dist (React compilado)
                                    → src/engine/video_job_processor.py
                                         cola secuencial, un video a la vez
```

- **`src/detector.py`** — YOLO. `set_detection_band()` acota la inferencia
  a una franja y devuelve las cajas en coordenadas del cuadro completo.
- **`src/tracker.py`** — IoU + Kalman.
- **`src/counter.py`** — cruce por cambio de signo del producto cruzado.
- **`src/engine/zones.py`** — polígonos de calzada: filtran, atribuyen y
  acotan.
- **`src/storage/traffic_db.py`** — SQLite en WAL. Cada módulo crea sus
  tablas con `CREATE TABLE IF NOT EXISTS`; las columnas nuevas van con
  `_ensure_column`.

**Modelo de datos:** un `project` es una intersección y es dueño de todo.
Una **línea** dice *dónde* se cuenta; una **zona** dice *cuál calzada* es.
`lane_configs.zone_id` ata una línea a su calzada — sin eso, la línea de la
calzada del fondo también recoge los vehículos de la cercana.

---

## Herramientas de diagnóstico

Están en `tools/` y existen porque cada una respondió una pregunta que no
se podía contestar de otro modo:

| Herramienta | Para qué |
|---|---|
| `inspeccionar.py` | Ver cuadros con detecciones y carriles, como PNG |
| `trayectorias.py` | Medir por dónde y hacia dónde circulan los vehículos |
| `diagnostico_fallos.py` | Dónde falla el detector, cruzando movimiento contra detección |
| `verificar_conteo.py` | Clip con cada cruce numerado, para contar a mano |
| `comparar_aforo_real.py` | Contrastar contra el aforo real de campo (conteo manual o tubo) |
| `validar_clasificacion.py` | Validar la clasificación vehicular contra el conteo manual |
| `hoja_clases.py` | Ver los vehículos recortados con lo que el sistema dice de cada uno |
| `exportar_comparacion.py` | Sacar a JSON todo lo que el reporte necesita, acotable por calzada |
| `reporte_calibracion_pdf.py` | Reporte de calibración en PDF para presentar a la empresa |
| `mover_proyecto.py` | Llevar un proyecto calibrado de una máquina a otra |
| `calidad_video.py` | Medir si un video nuevo sirve ANTES de contarlo: resolución, bitrate, nitidez y alto de los vehículos |
| `extraer_trayectorias.py` | Guardar el recorrido completo de cada vehículo a JSON, con el rastreador propio o ByteTrack |
| `analizar_od.py` | Origen-destino sobre ese JSON en segundos: rastros partidos, accesos, matriz |
| `recontar_sin_guardar.py` | Medir un cambio del rastreador contra el conteo manual sin tocar la base |
| `diagnosticar_encuadre.py` | Calificar si un video sirve para aforar, antes de gastar horas contándolo |
| `probar_diagnostico_encuadre.py` | Regresión del diagnóstico sobre los ocho casos ya medidos, sin GPU |
| `comparar_od_real.py` | Contrastar el aforo direccional contra el conteo manual de la empresa, con GEH |
| `probar_accesos_od.py` | Probar otro dibujo de accesos sobre rastros ya extraídos, sin volver a detectar |
| `mapa_extremos_od.py` | Ver dónde nacen y mueren los rastros de una ventana completa |
| `hoja_uniones.py` | Revisar a ojo si las uniones de rastros partidos son el mismo vehículo |
| `firmas_color.py` | Color de cada rastro para la unión por apariencia (probado, hoy apagado) |

---

## Estado actual

El **día completo** está contado en el Jetson y contrastado contra el
aforo manual. Proyecto **2 del Jetson**, "Cd. Juárez — Aforo matutino":
**135 videos, 24 horas, 22 508 cruces, 0 errores**, dos líneas
(`Carril 1` → Calzada oriente, `Carril 2` → Calzada poniente) atadas a sus
zonas.

**Horario medible: 07:00 a 19:59.** Trece horas seguidas, 0.90× contra el
conteo manual. El corte de la tarde es brusco — 19:00 da 0.91× y 20:00 cae
a 0.04× — y el de la mañana tiene una hora de transición, las 06:00, en
0.59×.

El proyecto 11 de la base de desarrollo es el **mismo aforo con la
calibración vieja** (3 220 cruces). Se conserva solo como referencia
histórica; **las cifras buenas son las del Jetson.**

Trasladar un proyecto calibrado entre máquinas:

```bash
python tools/mover_proyecto.py exportar --proyecto 11 --salida data/p11.json
# copiar el JSON y los videos de data/uploads al destino
python tools/mover_proyecto.py importar --archivo data/p11.json
```

### Ya hay aforo real de contraste

El usuario entregó el aforo del **mismo video, del mismo día**, medido con
contador de ejes: `referencias/aforo_real/`, un archivo por sentido del
19-ago-2026. Se compara con:

```bash
python tools/comparar_aforo_real.py --proyecto 11
```

**Hay DOS mediciones de campo del mismo tramo y el mismo día, y no
coinciden entre sí:**

| | archivo | qué es |
|---|---|---|
| **Referencia** | `conteo_manual_24h.xlsx` | Aforo contado por una persona, 24 h, por cuartos de hora, por sentido y por clase |
| Secundaria | `miguel_de_la_madrid_*.xls` | Contador de ejes, uno por sentido |

Contrastados entre sí en la ventana del video:

| sentido | tubo | manual | razón |
|---|---|---|---|
| ote-pte | 1 996 | 2 100 | 0.95× |
| pte-ote | 1 916 | 2 777 | **0.69×** |

**El tubo perdió el 31 % del tránsito en un sentido** mientras acertaba en
el otro. Un tubo se afloja, se descentra o se queda sin batería, y no avisa.

Esto costó una conclusión equivocada: mientras se usó el tubo como
referencia se creyó que el sistema **sobrecontaba** la calzada del fondo en
un 36 %, y se llegó a documentar como causa probable que los rastros se
partían a 17.7 px. Contra el conteo manual esa misma calzada sale en
**0.94×**: no sobrecontaba, el tubo subcontaba.

**Lección: antes de explicar por qué nuestro número difiere de una
referencia, comprobar la referencia.** `--fuente auto` toma el conteo
manual cuando existe; `--fuente tubo` fuerza el otro.

**Resultado tras reprocesar en el Jetson con la línea corregida**
(proyecto **2** del Jetson, 07:00–09:59, 18 videos, 0 errores, 4 671 cruces):

Contra el **conteo manual**, que es la referencia:

| | nuestro | manual | razón | r |
|---|---|---|---|---|
| Calzada oriente (**cercana**) | 2 072 | 2 100 | **0.99×** | **+1.00** |
| Calzada poniente (**del fondo**) | 2 597 | 2 777 | 0.94× | +0.99 |
| Ambos sentidos | 4 669 | 4 877 | **0.96×** | +0.99 |

La calzada cercana cuadra **cuarto de hora por cuarto de hora**, no solo en
el total — nuestro/manual: 163/164, 180/184, 195/197, 217/223, 223/227,
178/184, 140/142, 151/152, 138/138, 133/135, 156/151, 198/203. La razón por
intervalo se mueve entre **0.97 y 1.03**; la de la calzada del fondo, entre
0.88 y 1.17 con mediana 0.93.

Reparto: **43/57 % manual contra 44/56 % nuestro.** No es solo que el total
se parezca: el sistema reparte el tránsito como está repartido.

Integridad sobre los 4 671 cruces: **0** vehículos contados en dos líneas,
**0** recuentos del mismo rastro, **0** fugas de zona. Tiempo: 2 h 03 min
para 3 h de video.

**Cuidado con los nombres de las zonas, que engañan.** "Calzada oriente" es
la **cercana** y "Calzada poniente" la **del fondo** — al revés de lo que
sugiere el orden en pantalla. Se comprueba con `crossings.bbox_height`
(40.9 px contra 17.7 px), no con el nombre.

### La clase `truck` de COCO no es un camión

Comparada en crudo, nuestra composición sale **66 % livianos / 34 %
pesados** contra **87 / 13 %** del conteo manual. Parece un desastre y no lo
es: son dos taxonomías distintas. La clase `truck` de COCO mete en el mismo
saco una pickup y un tractocamión, y en la clasificación SCT que usa la
empresa (A, B, C, T-S, T-S-R) la pickup es **A**, un automóvil.

La separación se hace por **alto en píxeles**, y aquí funciona por una razón
concreta del montaje: todos los vehículos se cuentan al cruzar una línea
fija, o sea a la misma distancia de la cámara. A distancia constante el alto
en píxeles es proporcional al alto real. En la calzada cercana la clase
`truck` sale **bimodal** — mediana 40 px pero p75 en 66 — que son las dos
poblaciones mezcladas.

El umbral se expresa como **múltiplo del alto mediano del automóvil de esa
calzada**, para que valga donde la escala es otra. Calibrado contra el
conteo manual da **1.55–1.61×** (53 px en la cercana, 24 px en la del
fondo).

```bash
python tools/validar_clasificacion.py --proyecto 2 --holdout
```

Validación con holdout temporal — se calibra con 07:00–08:30 y se mide con
08:30–10:00, que es la única cifra honesta para la calzada donde se calibra:

| | livianos | pesados |
|---|---|---|
| Calzada oriente (cercana) | **0.98×** | **1.09×** |
| Calzada poniente (fondo) | 1.03× | **0.63×** |
| Ambos sentidos | 1.01× | 0.82× |

**Los livianos quedan validados** (0.98–1.03× en las dos calzadas, y el
barrido de sensibilidad los deja entre 0.96 y 1.01 para cualquier múltiplo
entre 1.3 y 2.0: son robustos porque los pesados son pocos).

**Los pesados solo sirven en la calzada cercana.** En la del fondo, a 15–17
px de alto, un camión y un automóvil miden lo mismo y ningún umbral los
separa: el barrido va de 0.77× a 0.43× sin nunca acertar.

**No se intenta separar autobús de camión.** A este tamaño los `bus` de la
calzada cercana miden 65–90 px y los `truck` grandes también; YOLO no los
distingue de forma fiable. Separar C de T-S necesitaría el **ancho** de la
caja (un tractocamión es mucho más largo), y `crossings` hoy solo guarda
`bbox_height`.

#### Ya se probó un modelo de visión para las clases finas, y NO sirve

La idea era razonable: COCO no tiene clase "pickup", así que un modelo de
visión podría responder en la taxonomía SCT. Está probado con
`llama-3.2-11b-vision-instruct` (API de NVIDIA, nunca se descargó al
Jetson) sobre recortes reales de la línea de conteo. La herramienta de la
prueba se retiró del repo al descartarse; queda en el historial de git
(commit 3427af7) por si hiciera falta repetirla con otra cámara.

**A mediodía dio 36 de 36** en la taxonomía SCT, incluida la distinción
autobús / camión / tractocamión que YOLO no puede hacer. Prometedor.

**A las 07:00 dio 28 de 40.** No generalizó. Sobre 40 pesados:

| lo que es | lo que dijo |
|---|---|
| 4 autobuses blancos | MOTO |
| 3 autobuses blancos | AUTO |
| 2 camiones de caja | MOTO |
| 3 cajas de tráiler | MOTO o PICKUP |

**12 de 40 vehículos pesados quedaron como livianos.** Un tráiler contado
como pickup cambia la clase del entregable, no es un matiz.

El patrón: **falla con vehículos blancos y grandes**. A las 07:00 el sol
está bajo y de frente; esos autobuses y cajas salen lavados.

Comparado contra la regla del alto, sobre la misma muestra:

| | aciertos liviano/pesado |
|---|---|
| Modelo de visión | 28 / 40 (70 %) |
| **Regla del alto** | **38 / 40 (95 %)** |

La regla solo falla en dos casos frontera, una SUV de 53 px y una pickup de
54 px, justo encima del umbral de 52.1. De 56 px en adelante acierta los 32.

**La regla simple le gana al modelo avanzado, y le gana en hora pico.**

**Lección de método: una sola condición de luz no valida nada.** El 36/36
del mediodía llevaba a construir sobre arena; solo probarlo en otra hora lo
descubrió. Cualquier prueba de este proyecto que se haga sobre una sola
franja horaria hay que repetirla en otra antes de creerla.

#### Verificado mirando los vehículos, no solo los totales

Validar por agregados tiene un hueco: una troca contada como pesada y un
camión contado como liviano **se cancelan** y el total cuadra igual. La
comprobación de verdad es mirar los recortes uno por uno:

```bash
python tools/hoja_clases.py --proyecto 2 --zona "Calzada oriente" \
    --salida data/clases.png
```

Sobre 54 vehículos recortados **en la línea** de la calzada cercana, los 54
caen del lado correcto. Los casos frontera, que son los que importan,
también: camioneta de 46 px y van de pasajeros de 50 px del lado liviano;
camión con pipa de 53 px y autobús de 58 px del lado pesado.

**Cuidado al usar esa herramienta: hay que restringir a la línea.** La
primera versión tomaba detecciones de toda la zona y mezclaba distancias —
el mismo vehículo mide 19 px al fondo y 33 px en la línea— así que el alto
dejaba de decir nada del tamaño real, que es la premisa entera de la regla.
Con la hoja mal hecha parecía que la clasificación fallaba.

#### Tres niveles, y por qué NO son dos

`src/engine/clasificacion.py` traduce las clases de COCO a la taxonomía de
la empresa y declara **con cuánta confianza puede hacerlo**:

| nivel | condición | qué vale |
|---|---|---|
| `medido` | automóvil ≥ 25 px | conteo y proporción |
| `estimado` | automóvil ≥ 12 px | **solo la proporción** |
| `no_resoluble` | menos, o de noche | nada |

La primera versión era todo o nada, y **eso tiraba información buena**. En
la calzada del fondo, con el automóvil a 15 px, el conteo absoluto va corto
(0.84×) pero la proporción sale bien:

| | livianos / pesados |
|---|---|
| Calzada cercana (33 px) | 87.5 / 12.5 % contra 87.4 / 12.6 % → **0.1 puntos** |
| Calzada del fondo (15 px) | 89.2 / 10.8 % contra 87.4 / 12.6 % → **1.8 puntos** |

Negarse a dar 1.8 puntos era quedarse corto a propósito.

**Los umbrales son físicos, sobre la imagen.** Si llega una cámara mejor o
se acerca el encuadre, el vehículo ocupa más píxeles y la calzada **sube de
nivel sola**. El sistema no decide "esta no la veo bien y paso": mide lo que
tiene y declara hasta dónde llega.

#### Dos preguntas distintas, y mezclarlas costó una versión

1. **¿Se puede medir a esta HORA?** — lo dice la **confianza**, sobre el
   proyecto entero. Separa día de noche.
2. **¿Se puede clasificar en esta CALZADA?** — lo dice el **alto** del
   vehículo. Separa la cercana de la del fondo.

Usar la confianza para las dos **no funciona porque se solapan**:

| | de día | de noche |
|---|---|---|
| Calzada cercana | 0.76–0.86 | 0.54–0.69 |
| Calzada del fondo | **0.53–0.66** | 0.40–0.53 |

El día de la calzada del fondo cae dentro de la noche de la cercana. Con un
umbral único de confianza, la calzada del fondo se callaba a todas horas
aunque de día su proporción sale a 1.8 puntos. **El sistema se volvía
perezoso donde sí podía.**

Y calcular el nivel sobre las 24 h juntas tenía el mismo efecto: los pocos
cruces nocturnos, con confianza 0.45, hundían la media de un carril que de
día clasifica bien. **El nivel va por carril Y por hora.**

Resultado del arreglo, sobre el día completo:

| | antes | después |
|---|---|---|
| Vehículos clasificados | 55 % | **99.1 %** |
| Diferencia con el aforo manual | — | **0.5 puntos** |

#### La traducción se hace en un solo sitio

En `traffic_db.get_interval_counts`, que es por donde pasa todo lo que ve
el usuario — pantallas, gráficas y los dos CSV. Antes la interfaz traducía
`truck` como "Camión" y el reporte declaraba **1 501 camiones donde el
aforo manual contó 417**.

El umbral se calcula **por carril**, no por proyecto: cada carril cuenta
sobre una línea fija, o sea a distancia fija de la cámara, que es
exactamente la condición que hace comparable el alto en píxeles.

Resultado en la plataforma, contra el conteo manual:

| | plataforma | manual |
|---|---|---|
| Livianos | **87.5 %** | 87.4 % |
| Pesados | **12.5 %** | 12.6 % |

Los porcentajes van sobre los vehículos que **sí** se clasificaron. Los no
clasificados se declaran aparte con su cuenta (2 597, el 55.6 %) y su
motivo. Repartirlos sobre el total hacía que "sin clasificar" saliera
primera con 55.6 % y la pantalla la anunciara como el tipo predominante del
aforo.

### Cómo se pasó de 0.29× a 1.04×: era la línea, no el detector

Con la calibración anterior la calzada cercana daba **0.29×** (579 contra
1 996). No era ceguera del detector: `Carril 1` estaba en **x=210**, donde
esa calzada mide 34 px de alto, mientras que en **x=519** mide 71 px. Es la
misma calzada, que se acerca a la cámara hacia la derecha del cuadro — se
estaba contando **en su extremo lejano**.

Lo delató la fuga de la calibración vieja: los 221 cruces que `Carril 2`
atribuyó a la calzada oriente medían **73.5 px a 0.79 de confianza**, las
mejores detecciones del conjunto, contra los 20.8 px y 0.64 de los 361 que
sí contaba `Carril 1`.

Se movió `Carril 1` a `x=520`, `y` de 192 a 260. Resultado por línea:

| línea | | antes | después |
|---|---|---|---|
| `Carril 1` | cruces | 361 | **2 074** |
| | alto medio | 20.8 px | **40.9 px** |
| | confianza | 0.64 | **0.86** |

**Lección general: antes de tocar el modelo, comprobar dónde está la línea
respecto a la perspectiva.** Una calzada horizontal no mide lo mismo en los
dos extremos del cuadro, y la línea debe ir donde el vehículo es grande.

### Las líneas deben solaparse, no separarse

Medido sobre este video: **el 32.6 % de las cajas invaden las dos calzadas
a la vez.** No causa doble conteo porque lo que se prueba es el **punto de
apoyo** (centro del borde inferior), que cae en una sola zona, y porque
cada línea solo recibe los rastros de su zona atada
(`video_job_processor.py`).

Consecuencia contraintuitiva: **alargar una línea hasta invadir la calzada
vecina no duplica nada, y dejarla corta sí pierde vehículos.** `Carril 2`
terminaba en `y=190.3` y dejaba sin cubrir 5 px — el **33 %** del alto de su
calzada — sin dar ningún aviso. Se alargó a `y=198`.

**Al calibrar, comprobar que cada línea cruza el alto COMPLETO de su
calzada en el punto donde la corta.** Es un fallo que no produce error, solo
un conteo más bajo.

El emparejamiento calzada↔sentido lo hace la herramienta **por correlación,
no por el nombre**: "Calzada poniente" es ambiguo (¿la del lado poniente o
la que lleva al poniente?) y equivocarse invierte la comparación entera.

### Lo que falta, por orden de importancia

1. **Probar el obturador rápido de la cámara.** Es la única acción que
   podría recuperar las 11 horas no medibles, incluida la hora pico del día
   (05:00, con 2 038 vehículos). Es gratis y se verifica grabando diez
   minutos de noche.
2. **Reducir la oclusión en hora pico.** El 0.80× de las 15:00 es el peor
   dato del horario medible y la causa está identificada (r = −0.83 contra
   el volumen). Se ataca con el ángulo de cámara, no con software.
3. **El reporte por calzada.** `crossings.zone_id` ya guarda el dato; la
   pantalla todavía agrupa por línea.
4. **Velocidad con dos líneas** (lo pide la PT-914). Además de dato
   vendible sirve de control: una velocidad imposible delata un rastro mal
   armado. El contador de ejes trae su propia tabla de velocidad por
   intervalo para contrastar.
5. **Separar autobús de camión.** Hoy se entrega liviano contra pesado.
   El modelo de visión ya se probó y no sirve con esta cámara (ver arriba).
   Queda el **ancho** de la caja, que hay que guardar y reprocesar; medido,
   el ancho separa bien autobús de automóvil (171–218 px contra 73–90) pero
   **no** autobús de camión, que se solapan. Con esta cámara el techo real
   es liviano / pesado / moto.

Sin empezar: IA visual e IA validadora con las APIs gratuitas de NVIDIA. El
cliente NVIDIA (`src/ai/nvidia_client.py`) ya está construido y verificado,
y el RAG ya está en marcha sobre él. La idea que vale la pena es usar la IA
visual como **auditor** de cuadros con baja confianza, no como contador: no
puede seguir un vehículo entre cuadros, así que no puede contar cruces.
Antes de integrarla hay que **validar al validador** contra cuadros
contados a mano.

### La exactitud baja cuando la vía se llena

Medido sobre el día completo, hora por hora contra el conteo manual:

| tránsito real | razón media |
|---|---|
| menos de 1 600 veh/h | **0.95×** |
| 2 000 o más veh/h | **0.86×** |

**Correlación entre volumen y razón: r = −0.83.** No es ruido: cuanto más
tránsito hay, menor proporción capturamos.

La causa más probable es **oclusión**. Con la vía llena los vehículos se
tapan entre sí desde el ángulo de esta cámara, y el que va detrás no llega
a verse. Es un límite del punto de vista, no del modelo — y es justo lo que
mejora subiendo la cámara, haciéndola más perpendicular a la vía, o
poniendo una segunda.

**Consecuencia para el informe: la exactitud NO se puede declarar como un
número único.** Decir "0.96×" a secas es cierto para la mañana y optimista
para la hora pico de la tarde. Hay que declararla por tramo, o acompañarla
del volumen al que aplica.

### La noche no se mide, y no es por falta de luz

Las 24 horas contra el conteo manual, misma calibración
(faltan 00 y 01 porque el metraje está incompleto ahí):

| hora | nuestro | manual | razón | conf | |
|---|---|---|---|---|---|
| 02:00 | 5 | 104 | 0.05× | 0.58 | no medible |
| 03:00 | 4 | 81 | 0.05× | 0.44 | no medible |
| 04:00 | 20 | 314 | 0.06× | 0.47 | no medible |
| 05:00 | 58 | 2 038 | 0.03× | 0.49 | no medible |
| 06:00 | 1 204 | 2 043 | 0.59× | 0.71 | transición |
| 07:00 | 1 945 | 2 075 | 0.94× | 0.73 | **medible** |
| 08:00 | 1 363 | 1 420 | 0.96× | 0.76 | **medible** |
| 09:00 | 1 363 | 1 382 | 0.99× | 0.74 | **medible** |
| 10:00 | 1 231 | 1 242 | 0.99× | 0.74 | **medible** |
| 11:00 | 1 675 | 1 833 | 0.91× | 0.69 | **medible** |
| 12:00 | 1 666 | 1 802 | 0.92× | 0.75 | **medible** |
| 13:00 | 1 372 | 1 568 | 0.88× | 0.72 | **medible** |
| 14:00 | 1 625 | 1 716 | 0.95× | 0.73 | **medible** |
| 15:00 | 1 810 | 2 259 | 0.80× | 0.69 | **medible** |
| 16:00 | 1 820 | 2 144 | 0.85× | 0.69 | **medible** |
| 17:00 | 1 988 | 2 360 | 0.84× | 0.67 | **medible** |
| 18:00 | 1 906 | 2 164 | 0.88× | 0.70 | **medible** |
| 19:00 | 1 332 | 1 466 | 0.91× | 0.71 | **medible** |
| 20:00 | 52 | 1 222 | 0.04× | 0.57 | no medible |
| 21:00 | 23 | 879 | 0.03× | 0.50 | no medible |
| 22:00 | 24 | 744 | 0.03× | 0.48 | no medible |
| 23:00 | 16 | 998 | 0.02× | 0.45 | no medible |

**Horario medible 07:00–19:59: 0.90× sobre 21 096 vehículos.** Fuera de él,
0.03×. **La transición es de una hora, no gradual**: entre 19:00 (0.91×) y
20:00 (0.04×) no hay término medio.

**La causa NO es oscuridad — es sobreexposición.** Medido sobre la franja
de la vía:

| | brillo medio | contraste |
|---|---|---|
| Día 07:00 | 84 | 36 |
| Madrugada 05:00 | **177** | 70 |
| Noche 21:00 | **168** | 70 |

De noche la imagen es **el doble de brillante** que de día. La cámara abre
la exposición al máximo, los faros y el pavimento iluminado se queman a
blanco puro, y con el obturador abierto tanto tiempo **todo lo que se mueve
se convierte en una raya**. Un vehículo nocturno en este material no es un
objeto: es una estela de luz.

```bash
# Reproduce la comparación: recorta la franja de la vía en un instante
# con movimiento, de día y de noche, ampliada 4x
python tools/inspeccionar.py --job N --zoom-carriles
```

**Consecuencia práctica: lo primero que hay que probar es el ajuste de
obturador de la cámara**, no otro modelo ni más resolución. Forzar
obturador rápido en modo nocturno, aceptando más ruido a cambio de congelar
el movimiento. Es gratis y se verifica grabando diez minutos.

Ojo con el impacto en el entregable: **las 05:00 son la hora pico del día
entero** (2 038 vehículos contra los 2 075 de las 07:00), y hoy es
justamente una de las que no se pueden medir.

Detalle curioso y contraintuitivo: de noche la calzada **del fondo** cuenta
mejor que la cercana (0.048× contra 0.010×). Lo cercano se quema y se
barre más, porque cruza más rápido en píxeles.

---

## Aforo direccional (origen-destino)

La empresa mandó 30 videos de 5 aforos direccionales (feb y abr 2025). En
el Jetson están en `data/od/videos/`, y todo lo de prueba vive en
`data/od/` (herramientas, trayectorias, imágenes).

### Calidad de cada aforo, medida y mirando el cuadro

`tools/calidad_video.py`, sobre el mejor video de cada aforo:

| aforo | video | alto mediano | para origen-destino |
|---|---|---|---|
| Entrada y salida Altozano | 1280×720 | **52 px** | buena; hay autos detenidos que excluir y un letrero que tapa la calle del arco |
| Blvd Ind | 1280×720 | 36 px | buena, varios brazos bajo el puente; el lente tapa la esquina derecha |
| Fraccionamientos | 1280×720 | 29 px | regular: la carcasa de la cámara tapa ~35 % de la imagen |
| Glorieta Altozano | 1280×720 | 33 px | difícil: la glorieta casi fuera de cuadro y un estacionamiento lleno (conf 0.45) |
| Altozano y Blvd Independencia | **640×360** | 18 px | mala: el mismo límite de tamaño del aforo de Cd. Juárez |

Dos videos no dan ninguna detección (`BLVD IND 06-36`, `GLORIETA 06-44`):
de noche o desenfocados. Tres de la tarde vienen a 640×360.

### Hay conteo manual direccional para contrastar

`referencias/aforo_direccional/`: un Excel por aforo (7), el mismo formato
en todos. Movimientos en clave `origen_destino` (`2_3`) con clases A, B y C
por cuarto de hora, en bloques de una hora (6:45–7:45 y, en Blvd.
Independencia, también 16:45–17:45).

**Los números de acceso no están en la hoja: están en formas dibujadas
encima del croquis satelital** (círculos con 1, 2, 3… y flechas). openpyxl
las descarta en silencio ("Shapes and drawings will be lost"); hay que
leerlas de `xl/drawings/drawing1.xml`. Medido así:

- *Entrada y salida Altozano*: 1 = calle al sureste (entre el canal y la
  barda), 2 = calle del fraccionamiento (la del arco), 3 = calle al norte
  junto al canal. Domina `2_3` (499 veh/h de 6:45 a 7:45).
- *Blvd. Independencia*: 1 = Juárez Porvenir (norte), 2 = sur, 3 = Blvd.
  Independencia al oriente, 4 = al poniente. El tránsito de paso SOBRE el
  puente casi no figura (`3_4` y `4_3` < 10 por cuarto de hora): se cuenta
  lo de abajo.

`tools/comparar_od_real.py` contrasta un proyecto de la plataforma contra
ese Excel. Qué acceso dibujado es qué número no se adivina por el nombre:
prueba todas las asignaciones y se queda con la de menos error, igual que
el emparejamiento calzada↔sentido del aforo por línea. Reporta cada
movimiento por cuarto de hora y su **GEH** (criterio: 85 % de movimientos
con GEH < 5). Probado con verdad conocida: recupera la asignación exacta.

Para que haya cuartos de hora comparables hay que contar la ventana
completa del manual, no un tramo suelto de 5 minutos: en Blvd Ind, los 8
videos de 16:34 a 17:54.

**En curso en el Jetson (15-sep-2026)**, con el contenedor reconstruido
(ByteTrack, `lap`, rastreador corregido, filtro de pedazos quietos):

| proyecto | aforo | videos | cuartos comparables |
|---|---|---|---|
| 4 | Blvd Ind, tarde (26-feb-2025) | 8, 16:34–17:54 | 16:45, 17:00, 17:15, 17:30 |
| 5 | Entrada y salida Altozano, mañana (8-abr-2025) | 6, 06:56–07:56 | solo 7:30 (falta el video de 07:06) |

Se crearon con `data/od/herramientas/crear_aforo_od.sh` (API: proyecto,
subida con hora del nombre y fecha del OSD, accesos, "Empezar conteo") y
`comparar_al_terminar.sh` corre `comparar_od_real.py` sobre los dos al
terminar la cola (`data/od/comparacion.log`). Primera vez que el
direccional corre dentro de la plataforma y no en las herramientas.

**Lo primero que destapó correr en producción:** `filter_detections`
contaba los accesos como vía y, en un proyecto que solo tiene accesos,
borraba cada detección del centro del cruce. Primer video de Blvd Ind: 14
completos y 89 incompletos. Corregido (solo las calzadas acotan la vía),
el siguiente video dio 423 completos y 344 incompletos (55 %), igual que
el análisis. **Las herramientas de análisis no pasaban por ese filtro y por
eso no lo vieron: probar el camino de producción, no solo las piezas.**

### Resultado contra el conteo manual (primera medición real)

*Entrada y salida Altozano*, un solo cuarto de hora comparable (7:30):

| movimiento | plataforma | manual | GEH |
|---|---|---|---|
| 2_3 (dominante) | 222 | 252 (88 %) | 3.9 |
| 1_3, 3_1 | 0 | 9, 10 | > 8 |

El emparejamiento automático coincidió con el croquis (Arco = 2, calle
del canal = 3). El movimiento principal pasa; los chicos se pierden. Un
solo cuarto de hora no valida nada.

*Blvd Independencia*, 4 cuartos de hora (16:45–17:45): **no pasa.**
Completos 2 754 contra 5 374 del manual (51 %), 2 de 15 movimientos con
GEH < 5 (el criterio pide 85 %), 2 067 incompletos en la ventana. El
emparejamiento no tiene sentido geométrico: tres accesos dibujados cayeron
en el 3 y ninguno en el 4, así que todo movimiento del poniente salió en
cero. **Los accesos se dibujaron por dónde se veía pasar tránsito en la
cámara, sin saber qué brazo del croquis era cada uno.** Antes de afinar
nada más hay que establecer la orientación de la cámara sobre la foto
satelital y dibujar un acceso por brazo.

**Probar accesos ya no cuesta GPU.** Se extrajeron detecciones y rastros de
los 8 videos de Blvd Ind con la franja de producción (`extraer_trayectorias
--guardar-detecciones --banda 338 720`) y `tools/probar_accesos_od.py`
reproduce a producción sobre ellos: dio **exactamente los mismos 2 754
completos** que la plataforma (2 107 incompletos contra 2 067). Cada dibujo
de accesos se contrasta contra el Excel en minutos.

**No fue la orientación.** Con la cámara vista del puente de frente y la
calle norte-sur pasando por debajo solo caben dos orientaciones, y las dos
fallan igual: 1 y 2 de 15 movimientos con GEH < 5. Movimientos enteros en
cero en ambas (ningún vehículo registraba origen en los accesos de abajo).

`tools/mapa_extremos_od.py` pinta, sobre los 80 minutos, dónde nacen y
mueren los rastros ya unidos. Enseñó tres errores del dibujo:

1. Una **rampa** hacia el bulevar elevado (diagonal a la esquina superior
   derecha) quedaba dentro del acceso "Derecha": 848 rastros morían ahí sin
   haber salido de su acceso.
2. "Bajo puente" era demasiado alto: nacían en su parte baja y morían en la
   alta sin salir de él.
3. Los vehículos del lado de la cámara **aparecen a media imagen**
   (y 560–640), por encima de los accesos de abajo: sin origen.

Detalle del material: el video de 16:34 empieza con **el lente tapado**
(ropa del instalador); tiene 511 rastros contra ~2 400 de los demás. La
comparación empieza a las 16:45 y no lo usa.

Corregir esos tres errores **empeoró** el resultado (accesos v4: 43 % de
completos contra 51 %, 2 281 incompletos): con "Bajo puente" delgado los
vehículos que salen de debajo del puente dejaron de registrar origen y
aparecieron 1 089 movimientos falsos "Cerca → Abajo". Cada arreglo del
dibujo abría otro hueco.

**Conclusión: Blvd Independencia no se puede aforar direccionalmente con
esta cámara, y no es un problema de software.** Es un paso a desnivel: el
puente tapa las laterales del otro lado del bulevar, así que desde una
esquina un vehículo que va a la lateral del fondo y uno que sigue por la
calle norte-sur desaparecen igual, bajo el puente. Ningún dibujo de accesos
separa los cuatro brazos; por eso el emparejamiento nunca tuvo sentido
geométrico. Hacen falta dos cámaras (una a cada lado del puente) o una
vista elevada que vea las cuatro esquinas. **No seguir afinando accesos
sobre este material.** El proyecto 4 queda con los accesos v2, que fueron
los menos malos.

### El entregable que SÍ sale donde la matriz no: volumen por acceso

La matriz origen-destino exige seguir al vehículo de un extremo a otro del
cruce. El **volumen por acceso** (cuántos entraron y cuántos salieron por
cada brazo) solo exige verlo entrar o salir, así que **cuenta también los
movimientos incompletos**: uno del que no se vio el destino sigue diciendo
por dónde entró. Medido contra el conteo manual:

| aforo | entradas | salidas | accesos con GEH < 5 |
|---|---|---|---|
| Entrada y salida Altozano (7:30) | 308 contra 275 | 292 contra 275 | **5 de 6 (83 %)** |
| Blvd Independencia (4 cuartos) | 4 535 contra 5 374 | 3 040 contra 5 374 | 0 de 8 |

En Blvd Ind falla por lo mismo de siempre, y aquí se ve sin ambigüedad: el
**acceso 4 da 0 entradas y 0 salidas**. La cámara no lo ve; no es ajuste.

`get_matriz_od` devuelve `por_acceso`, y lo muestran el endpoint
`/direccional`, la sección del reporte y la hoja DIRECCIONAL del Excel.
`data/od/herramientas/comparar_accesos.py` lo contrasta contra el Excel de
la empresa emparejando accesos por datos.

**La Glorieta Altozano tampoco sirve, y por otra razón: no vemos el
tránsito.** Se contó su ventana completa (8 videos, 07:00–08:00, 4 cuartos
comparables): 124 movimientos completos y ~1 630 vehículos detectados
contra ~5 760 del conteo manual, un tercio. Los dos movimientos dominantes
del manual (`2_3` con 1 956/h y `3_2` con 1 325/h) salen en **cero**: esa
cámara mira al Blvd. Altozano y el flujo grande de la Y, el que va y viene
de Blvd. Independencia, pasa fuera del encuadre. Los incompletos se
amontonan a media imagen (x 320–560 y 960–1120), no en las orillas: el
vehículo aparece y desaparece en medio de la escena. **Si el vehículo no
está en el video no hay nada que afinar.**

**Qué se puede ofrecer hoy, por tipo de cruce:**

- Intersección plana, con los brazos a la vista: matriz origen-destino,
  con el movimiento dominante al 88 % (Entrada y salida Altozano).
- Cualquier cámara que vea el brazo completo: volumen por acceso.
- Paso a desnivel con una sola cámara: **nada fiable**; hacen falta dos
  cámaras.

### Diagnóstico de encuadre: calificar el video antes de contarlo

`src/engine/diagnostico_encuadre.py`, endpoint
`POST /api/videos/{job_id}/diagnostico`, botón "Revisar encuadre" en Subir.

Nace de lo caro que salió descubrirlo contando: Blvd Independencia costó 4 h
de proceso para concluir que el puente tapa dos accesos y la Glorieta 1.5 h
para ver que solo se veía un tercio del tránsito.

**Dos etapas, porque la primera sola miente:**

| aforo | solo imagen | con rastreo | resultado real |
|---|---|---|---|
| Entrada y salida Altozano | REGULAR (69) | **BUENO (80)** | sirvió |
| Blvd Independencia | BUENO (77) | **REGULAR (58)** | falló |
| Glorieta Altozano | REGULAR (66) | **NO RECOMENDABLE (42)** | falló |

La etapa por imagen mide tamaño del vehículo, exposición, nitidez y
confianza con los umbrales ya medidos contra conteos manuales. **Calificaba
mejor al cruce que falló** (41 px) que al único que funcionó (43 px con
menos confianza), porque lo que decide no es cómo se ve el vehículo sino si
se alcanza a ver por dónde entra y sale.

La etapa por rastreo (un minuto) mide dónde nacen y mueren los rastros:

| aforo | extremos en 6 celdas | en la orilla del cuadro |
|---|---|---|
| Entrada y salida Altozano | **81 %** | 36 % |
| Blvd Independencia | 54 % (repartidos en 72 celdas) | 30 % |
| Glorieta Altozano | 64 % | **1 %** |

Cada fracaso tiene su firma: Blvd Ind dispersa los extremos por toda la
escena (algo tapa la vía), la Glorieta casi no tiene extremos en la orilla
(el acceso queda fuera del encuadre).

**No inventa un porcentaje de exactitud**: entrega el rango esperado del
veredicto (verde 0.90–0.99×, ámbar 0.80–0.95×, rojo ninguno) y avisos
concretos. Son tres escenas validadas: alcanza para avisar, no para
prometer.

**Puesto a prueba sobre otro video de cada aforo** (16-sep-2026, uno por
uno en el Jetson; el segundo pasó por la API, que es el camino real):

| video | veredicto | imagen | rastreo | lo que ya se sabe del aforo |
|---|---|---|---|---|
| Entrada Altozano 07:26 | BUENO (78) | 78 | 87 % / 38 % | sirvió ✔ |
| Entrada Altozano 07:56 (API) | REGULAR (65) | 65 | 98 | sirvió ✔ |
| Entrada Altozano 06:56 (API) | NO RECOMENDABLE (0) | 23 | 0 | amanecer: 11 px y 0.5 detecciones por cuadro ✔ |
| Glorieta Altozano 07:14 | NO RECOMENDABLE (39) | 51 | 39 | falló ✔ |
| Altozano y Blvd Ind 07:49 (640×360) | NO RECOMENDABLE (38) | 38 | 77 | 48 % de los vehículos bajo 20 px ✔ |
| **Blvd Independencia 17:04** | **REGULAR (74)** | 74 | 77 | **falló ✘** |

**El diagnóstico NO detecta el paso a desnivel.** Con otro video del mismo
aforo, Blvd Independencia da 66 % de concentración y 28 % en la orilla —no
el 54 % / 30 % del video con el que se fijaron los umbrales— y aprueba como
"regular, 0.80–0.95×", cuando su matriz real salió al 51 % con 2 de 15
movimientos por debajo de GEH 5. Es otra vez la lección del modelo de
visión: **una sola condición no valida nada**, y aquí cada umbral se fijó
con un video por escena. **No se mueven los umbrales para que ese caso
cuadre**: con tres escenas eso es ajustar a la muestra, no medir. Lo que
queda es el aviso genérico del direccional —comprobar a ojo que los cuatro
accesos se vean completos y que nada los tape—, así que **para el aforo
direccional el diagnóstico avisa, no autoriza.**

**Pocos rastros no es mal encuadre.** La etapa de rastreo reprobaba con
0/100 cualquier video con menos de 10 rastros en el minuto de prueba, y eso
mezcla dos causas opuestas:

| video | detecciones por cuadro | rastros | qué es |
|---|---|---|---|
| Fraccionamientos 07:26 | 2.1 | 5 | calle tranquila, encuadre bien (30 px, conf 0.71) |
| Entrada Altozano 06:56 | 0.5 | 0 | amanecer: ahí de verdad no se ve nada |

Las separa **cuántos vehículos ve el detector en la imagen**, no cuántos
alcanza a seguir. Con menos de 10 rastros pero al menos 1 detección por
cuadro la etapa se declara **no concluyente**, manda la etapa por imagen y
el aviso dice que hubo poco tránsito y que conviene medir más minutos.
Fraccionamientos pasó de "NO SIRVE (0)" —por la razón equivocada— a
"REGULAR (50)" por las razones reales: sobreexpuesto (148), poco nítido
(1 298) y vehículo de 30 px.

**El veredicto solo no sirve; lo accionable es el aviso.** La cola mostraba
"Encuadre no recomendable · 39/100" y nada más. Ahora esa pill abre el
detalle con la exactitud esperable y los avisos, y **se abre sola cuando el
encuadre no sale bueno**: esconder "esta perspectiva va a costar exactitud"
detrás de un clic es no avisar.

Y para que el aviso exista siempre: **cada aviso llevaba su propio umbral,
más duro que el del puntaje**, así que un video podía salir en 49/100 sin
un solo aviso. Pasó con Fraccionamientos 06:46 —brillo 149 cuando el aviso
pedía 150, nitidez 1 180 cuando el aviso pedía menos de 1 000, y el cuartil
bajo del alto en 17 px, que ni siquiera tenía aviso— tres factores
puntuando casi cero y ninguno explicado. Ahora todo factor por debajo de
0.35 se explica, y la regresión lo comprueba:

```bash
python tools/probar_diagnostico_encuadre.py
```

Ocho casos con las cifras que se midieron de verdad en el Jetson, sin GPU y
en un segundo: cada uno conserva su color y **ningún video que no salga
"bueno" se queda sin un aviso concreto.** Sirve para tocar umbrales sin
volver a gastar horas de proceso.

**No corre si hay videos en la cola.** Dos trabajos de GPU a la vez dan
`NvMapMemAllocInternalTagged error 12` y dejan cuadros sin detección. Pasó
dos veces, la segunda por lanzar el diagnóstico durante el recuento de
Juárez; el endpoint ahora responde 409 y pide esperar.

### Cómo decide la plataforma

`src/engine/origen_destino.py`. Cada brazo es una zona de tipo `acceso`;
el primer acceso que pisa el vehículo es su origen y el último, después de
salir del origen, su destino. Los movimientos se deciden **al cerrar el
video**, para poder unir los pedazos de rastro que partió una oclusión. Los
incompletos (se vio origen o destino, no ambos) se declaran aparte y **no
se reparten**: repartirlos sería suponer a dónde iba el vehículo.

**Los accesos se dibujan, no se adivinan.** Se probó la agrupación
automática de extremos de rastro (arXiv 2607.10949, 3.4 % de error en
cámaras de orilla): en Entrada y salida Altozano el acceso del arco queda al
fondo de la imagen, los vehículos aparecen a distintas distancias, y el
acceso se partió en seis grupos.

### ByteTrack para el direccional, y la unión de pedazos verificada a ojo

En Entrada y salida Altozano (5 min, accesos dibujados), movimientos con
origen Y destino:

| rastreador | completos |
|---|---|
| propio (viejo o corregido) | 15–16 % |
| ByteTrack | 47 % |
| ByteTrack + unión de pedazos afinada | **71 %** |

ByteTrack gana porque su segunda pasada usa las detecciones de baja
confianza, que es lo que queda de un vehículo medio tapado; el propio las
descarta a 0.25. Con el propio, los rastros se parten a campo abierto a lo
largo de toda la calle.

Con ByteTrack, casi todo lo que quedaba incompleto moría detrás de **un
letrero de peatones** y renacía del otro lado a ~1.9 altos de caja. El
motor rechazaba esos pares por distancia (30 de 68) y por tamaño (15 de 68:
la caja medio tapada se encoge). Se afinó y **se verificó mirando cada
unión recortada** (`tools/hoja_uniones.py`), porque un total más alto no
dice si se unieron vehículos distintos:

| hueco | tolerancia | tamaño | completos | uniones erróneas a ojo |
|---|---|---|---|---|
| 2 s | 1.2 altos | 0.6–1.6 | 47 % | — |
| **1 s** | **2.0 altos** | **0.5–2.0** | **71 %** | **2 claras + 3 dudosas de 53** |
| 3 s | 3.0 altos | 0.5–2.0 | 75 % | ~5 claras + ~5 dudosas de 48 |

Los errores se concentran en huecos largos (16–41 cuadros). Quedan como
predeterminados del motor los de 1 s.

**Alargar el `track_buffer` de ByteTrack NO ayuda**, aunque parecía la
palanca obvia (a 15 fps el 30 por omisión conserva un rastro perdido solo
15 cuadros). Sobre las mismas detecciones: buffer 30 / 60 / 90 → 53 / 50 /
51 % completos, y los completos antes de unir no se mueven (46 / 45 / 46).
Al reaparecer detrás del letrero, la caja predicha ya no se solapa con la
detección; lo recupera la unión de pedazos, no el rastreador.

Para barrer parámetros del rastreador sin gastar GPU: detectar una vez con
`extraer_trayectorias.py --guardar-detecciones` y rastrear desde el archivo
con `--desde-detecciones` (~400 cuadros/s en el CPU del Jetson). Reproduce
la corrida en vivo: 435 rastros contra 434, el mismo 53 %.

**En el cruce sintético la conclusión es otra**, y hay que conocer por qué.
Ahí hay verdad por vehículo, 8 movimientos que se cruzan en el centro y
huecos de 3–20 cuadros (150 vehículos × 5 semillas):

| variante | correctos | equivocados | incompletos |
|---|---|---|---|
| 2 s / 1.2 / 0.6–1.6 | 147.2 | 0.0 | 5.6 |
| 2 s / 2.0 / 0.5–2.0 | 147.2 | 0.0 | 5.6 |
| 1 s / 2.0 / 0.5–2.0 | 135.8 | 0.6 | 27.2 |

La tolerancia amplia **no** junta vehículos distintos ni con tránsito
cruzado; lo que cuesta es el tope de 1 s, que deja incompletos a los
vehículos genuinos tapados más de un segundo. Con huecos de hasta 10
cuadros (la mediana real es 7) todas las variantes dan igual.

El choque con el video real tiene explicación: la simulación no tiene
vehículos parecidos que aparezcan cerca, así que ahí un hueco largo siempre
es el mismo vehículo; en Altozano casi nunca lo era.

**Blvd Ind lo decidió** (tránsito cruzado real, 5 min, 1280×720). Uniones
revisadas a ojo con `hoja_uniones.py`:

| hueco | uniones | juntan vehículos distintos |
|---|---|---|
| **1 s** | 22 | 3–5 |
| 2 s | 39 | **~15** (camioneta blanca con auto oscuro, autobús con pickup…) |

El tope queda en 1 s. **La simulación engañaba**: con tránsito cruzado y
vehículos parecidos, pasado un segundo el que reaparece suele ser otro.

ByteTrack también gana aquí, aunque por menos: 40 % de movimientos
completos contra 32 % del rastreador propio corregido.

**Lo que más pesó fue dibujar bien los accesos.** Con los primeros
polígonos muchos vehículos aparecían justo debajo de "Bajo puente" y morían
antes de llegar a "Derecha". Ampliándolos (que el acceso llegue hasta donde
el vehículo aparece y desaparece de verdad), ByteTrack pasó de **40 % a
57 %** y los "sin origen" de 24 % a 7 %. Al calibrar un aforo direccional,
mirar dónde nacen y mueren los rastros (`analizar_od.py` pinta los
extremos) antes de dar los accesos por buenos.

**Tres ideas más que se midieron y no sirvieron, o sirvieron al revés:**

1. *Unión especial para vehículos detenidos en la fila* (hueco de hasta 4 s
   si estaba quieto y reaparece a menos de 0.35 altos). Cero efecto en los
   dos aforos. El diagnóstico lo explicó: de los rastros sin destino de
   Blvd Ind, 82 % mueren dentro de un acceso pero solo 1 % iba quieto.
   Queda en el código, apagada (`hueco_detenido_s=None`).
2. *Accesos como "puertas" angostas en la orilla.* Achicar "Derecha" de
   x ≥ 960 a x ≥ 1100 bajó Blvd Ind de 57 % a 52 %. El acceso ancho, que
   llega a donde el vehículo de verdad aparece, es mejor.
3. *Conservar los pedazos cortos para la unión* (el motor de producción lo
   hacía): peor. Blvd Ind 56 % con 150 uniones contra 57 % con 20;
   Altozano 65 % contra 71 %. Los pedazos de vehículos estacionados o en
   fila encuentran pareja donde no deben. Ahora `AforoDireccional.cerrar`
   descarta los pedazos que no se movieron ANTES de unir, y también las
   cadenas incompletas que no se movieron después.
   `analizar_od.py --filtro-despues` reproduce exactamente a producción.

   **Cuidado con cómo se mide "se movió".** La primera versión usaba la
   distancia entre el primer y el último punto, y borró **19 de 21 vueltas
   en U** del cruce sintético: el vehículo sale de su acceso y vuelve al
   mismo, así que esa distancia es casi cero. `se_movio` usa el mayor
   alejamiento desde el primer punto (2 altos de caja): un estacionado solo
   tiembla, una vuelta en U se aleja antes de regresar.

**Se probó filtrar las uniones por color y NO se activa.** Idea razonable:
las uniones malas de Blvd Ind eran de colores obviamente distintos. Firma
Lab del centro de la caja, mediana de 5 muestras por extremo
(`tools/firmas_color.py`, `origen_destino.firma_color`), con el hueco en 1 s:

| aforo | sin color | umbral 45 | umbral 30 | umbral 20 |
|---|---|---|---|---|
| Blvd Ind: uniones / completos | 20 / 57 % | 17 / 56 % | 15 / 56 % | 13 / 55 % |
| Entrada Altozano: uniones / completos | 50 / 71 % | 48 / 69 % | 47 / 67 % | 45 / 65 % |

Mirando las hojas: en Blvd Ind el umbral 30 quitó 3–4 uniones malas, pero
la asignación global **reacomodó** y aparecieron otras igual de malas
(una camioneta blanca con un auto oscuro). En Altozano, donde casi todas
las uniones eran buenas, quitó uniones buenas: justo antes de perderse la
caja ya incluye el letrero amarillo y el color medido deja de ser el del
vehículo. Queda apagado (`max_delta_color=None`); el código se conserva
por si otra cámara, con más resolución, lo vuelve útil.

### El rastreador partía los rastros justo cuando la vía se llena

`VehicleTracker` llamaba a `predict()` dentro del doble ciclo detección ×
rastro: con D vehículos en pantalla, el Kalman avanzaba D pasos por cuadro
y `miss_streak` subía D. Un vehículo que el detector perdía unos cuadros se
borraba en 30/D cuadros en vez de 30. Medido con cajas sintéticas perdidas
5 cuadros:

| vehículos en pantalla | antes | corregido |
|---|---|---|
| 1 | 0 de 1 partidos | 0 de 1 |
| 8 | **8 de 8** | 0 de 8 |
| 15 | **15 de 15** | 0 de 15 |

Sin pérdidas no cambiaba nada (0 cambios de identidad antes y después), así
que la primera hipótesis —que la predicción se pasaba de largo— era falsa;
lo que pesa es la ausencia multiplicada.

**Toca el aforo por línea ya validado.** Antes de desplegarlo se mide con
`tools/recontar_sin_guardar.py`, que recuenta en memoria con los dos
rastreadores sobre la misma detección y compara contra lo guardado y el
conteo manual. La columna "viejo" tiene que reproducir lo guardado; si no,
la emulación no es fiel.

**Medido en la hora pico validada (15:00, la peor del día, 0.80×)**, con
la misma detección para los dos rastreadores:

| | guardado | viejo | corregido | manual |
|---|---|---|---|---|
| Calzada oriente (cercana) | 1 148 | 1 148 | **1 216** | 1 281 |
| Calzada poniente (fondo) | 659 | 659 | **706** | 978 |
| Ambas | 1 807 (80 %) | 1 807 (80 %) | **1 922 (85 %)** | 2 259 |

"Viejo" reproduce lo guardado al vehículo, así que la emulación es fiel.
El corregido sube en los 4 cuartos de hora y en las dos calzadas.

**Y en una hora tranquila (07:00), donde el viejo ya acertaba:**

| | guardado | viejo | corregido | manual |
|---|---|---|---|---|
| Calzada oriente (cercana) | 755 | 755 | **763** | 768 |
| Calzada poniente (fondo) | 1 187 | 1 187 | **1 246** | 1 307 |
| Ambas | 1 942 (94 %) | 1 942 (94 %) | **2 009 (97 %)** | 2 075 |

No sobrecuenta: los 4 cuartos de hora quedan por debajo del manual
(496/528, 512/534, 506/517, 495/496). Validado en la peor hora y en una
tranquila, se despliega.

**Desplegado y con el día completo recontado** (135 videos, 23 859 cruces
contra 22 508 antes), medido con `comparar_aforo_real.py` sobre la ventana
comparable 06:30–20:00 (54 cuartos de hora):

| | nuestro | manual | razón |
|---|---|---|---|
| Calzada oriente (cercana) | 12 623 | 12 647 | **1.00×** |
| Calzada poniente (fondo) | 10 639 | 11 793 | 0.90× |
| Ambos sentidos | 23 262 | 24 440 | **0.95×** |

Antes de la corrección ese total estaba en 0.90×. El reparto entre sentidos
sale 54/46 contra 52/48 real y la correlación del perfil por cuarto de hora
es r = +0.96. La calzada del fondo se queda en 0.90× por el tamaño del
vehículo (14–17 px), que es límite de cámara y no del rastreador.

Queda otro defecto sin tocar, a propósito para medir uno a la vez: una
detección cuyo mejor emparejamiento tuvo IoU bajo entra dos veces a la
lista de sin pareja y crea dos rastros.

### No correr dos trabajos de GPU a la vez en el Orin

Dos extracciones en paralelo dieron `NvMapMemAllocInternalTagged error 12`
y cuadros sin detección, que parten rastros artificialmente: la comparación
de rastreadores de esa corrida no valía. Solo, ByteTrack con cuadro completo
de 1280×720 va a 14.4 cuadros/s (5 min de video en 5.2 min).

---

## Al desplegar en el Jetson

Guía completa en [docs/JETSON_DEPLOY.md](docs/JETSON_DEPLOY.md). Lo
esencial:

**La velocidad ya está medida en el equipo real** (Orin Nano Super,
JetPack 6.2, modo MAXN): 37.3 ms por cuadro a `imgsz` 1280, y 40.7 ms de
punta a punta con tracker incluido — **6.1 min por cada video de 10 min**,
más rápido que el tiempo real. Un aforo de 24 h sale en unas 15 horas.

El Orin Nano resultó **1.3 veces más lento que la PC de desarrollo**, no
5 a 8 como se había estimado sin tenerlo. **No hace falta TensorRT**;
`use_tensorrt` y `half_precision` se quedan apagados.

Si aun así no alcanza, bajar `input_size` a 960 y luego a 640, en ese
orden. **No volver a `yolov8n`**: el equipo vería la mitad de los
vehículos y entonces la velocidad da igual.

El Orin Nano tiene 8 GB compartidos entre CPU y GPU. El contenedor está
limitado a 6 GB en `docker-compose.jetson.yml`; si se come toda la RAM se
cuelga el equipo entero, no solo la aplicación.

---

## Entorno de trabajo

Las **skills viven en el repo** (`.claude/skills/`, 138 instaladas), así
que un `git clone` las trae todas — no hay que descargarlas aparte en el
Jetson.

El entorno de Python de desarrollo es `venv/` y **no** viaja en el repo. En
el Jetson no se usa: ahí todo corre dentro del contenedor Docker, que trae
sus propias dependencias compiladas para el Orin (ver
`requirements-jetson-docker.txt`, que a propósito **no** incluye torch,
torchvision, ultralytics, opencv ni numpy — esos vienen en la imagen base y
reinstalarlos por pip los rompe).

Para levantar en la PC de desarrollo: `python serve.py`, en el puerto 8080.

## Cómo ejecutar cosas EN EL JETSON

En el Jetson no hay Python del proyecto en el host: torch, ultralytics y
opencv viven **solo dentro del contenedor**. Cualquier comando del
proyecto va con este prefijo, desde `~/vehicle-traffic-counter`:

```bash
docker compose -f docker-compose.jetson.yml exec aforo-vehicular   python3 tools/inspeccionar.py --job 1
```

Añade `-T` a `exec` cuando el comando no sea interactivo (scripts, tuberías,
todo lo que corra sin terminal). Sin eso falla con "the input device is not
a TTY".

**Solo tres carpetas están montadas desde el host y sobreviven a recrear el
contenedor: `data/`, `models/` y `configs/`.** El resto —`input/`, `tools/`,
`src/`, `web/`— está horneado en la imagen. Consecuencia práctica: **las
herramientas de diagnóstico tienen que escribir su salida en `data/`**, o
el PNG o el clip se pierden con el contenedor:

```bash
docker compose -f docker-compose.jetson.yml exec -T aforo-vehicular   python3 tools/inspeccionar.py --job 1 --salida data/inspeccion.png
```

Y como el contenedor corre como root, lo que escribe queda con dueño root:
para borrarlo desde el host hace falta `sudo`.

Al cambiar código hay que **reconstruir**, porque `COPY . .` lo hornea en la
imagen; editar el archivo en el host no cambia lo que corre:

```bash
git pull && docker compose -f docker-compose.jetson.yml up -d --build
```

Comandos de operación:

```bash
docker compose -f docker-compose.jetson.yml logs -f      # ver qué hace
docker compose -f docker-compose.jetson.yml restart      # reiniciar
docker ps                                                # estado y salud
```

La plataforma queda en el puerto 8080 del Jetson. Desde otra máquina, sin
exponer nada a internet:

```bash
ssh -L 8080:localhost:8080 apia@IP-DEL-JETSON
```

## Convenciones

- **Español** en código, comentarios, commits y interfaz.
- Los comentarios explican **por qué**, no qué. Si un valor está medido, el
  comentario lleva el número y contra qué se comparó.
- **`.env` nunca se commitea** — contiene la API key de NVIDIA. Verificar
  con `git check-ignore -v .env` antes de cada commit.
- Los `.pt` están en `.gitignore`; el `Dockerfile.jetson` descarga el
  modelo al construir.
- Antes de afirmar que algo mejora, **medirlo**. Este proyecto tiene un
  historial de suposiciones razonables que resultaron falsas: el problema
  nocturno no era falta de luz (el brillo es *mayor* de noche), SAHI no
  ayudó, y subir el NMS a 0.7 empeoró las cosas.
