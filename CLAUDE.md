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

**La clase del vehículo se congelaba en el primer cuadro.** `Track` fijaba
`class_name` al crear el rastro y no lo tocaba nunca. Un vehículo que entra
al cuadro como una rebanada se detecta un instante como `motorcycle`, y así
se reportaba aunque el detector dijera `car` con 0.90 durante cien cuadros.
Medido en la cámara frontal: **113 de 709 cruces de una calzada salieron como
motocicleta**, con 162 px de alto medio —más grandes que los automóviles—, y
al mirarlos con `hoja_cruces.py --clase motorcycle` eran minivans, sedanes,
un tractocamión y una pipa. Eso ensucia la composición vehicular entera, que
es un entregable. Ahora cada detección vota pesada por su confianza y gana la
más apoyada; está en `tools/probar_rastreador.py`.

**Un video que fallaba se llevaba la cola entera.** Al subir los 741 videos
del aforo frontal, las inserciones de la subida dejaron la base bloqueada
unos segundos, el borrado de cruces previos falló con `database is locked` y
la excepción mató el hilo de la cola: los 741 quedaron "en cola", sin nadie
que los procesara y sin ningún aviso en la interfaz. Ahora el fallo de un
video se registra, marca ese video como error y la cola sigue; y la conexión
SQLite espera hasta 60 s por el bloqueo en vez de 5.

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
| `silueta_clases.py` | Si la regla de liviano/pesado tiene sentido en una cámara nueva, antes de entregar |
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
| `od_por_trayectoria.py` | Contrastar la decisión por trayectoria contra el conteo manual, sobre rastros ya extraídos |
| `firmas_color.py` | Color de cada rastro para la unión por apariencia (probado, hoy apagado) |
| `velocidad_contra_tubo.py` | Velocidad por tramo sobre recorridos ya extraídos, contra el contador de ejes, con horas de calibración y de prueba |
| `probar_camara_en_vivo.py` | Si una cámara en vivo (RTSP, HTTP, HLS) sirve y el equipo alcanza su ritmo, sin guardar video |
| `revisar_escena.py` | Qué videos de una entrega miran de verdad a la vía y cuáles son de instalación |
| `barrido_linea.py` | Referencia sin detector: apila la franja de la línea cuadro a cuadro y marca encima los cruces contados |
| `hoja_cruces.py` | El cuadro exacto de cada cruce contado, para cazar dobles conteos uno por uno |
| `probar_rastreador.py` | Regresión sin GPU de los tres defectos que causaron conteos dobles o partidos |
| `unir_segmentos.py` | Pegar los segmentos de un minuto en tramos, comprobando que no se corran las horas |
| `probar_clasificacion.py` | Regresión sin GPU de las clases, con los vehículos reales ya verificados a ojo |
| `silueta_clases.py` | Si la regla de liviano/pesado tiene sentido en una cámara nueva |
| `exportar_recortes.py` | Sacar el recorte de cada vehículo contado, repartido por hora, para etiquetar |
| `entrenar_clasificador.py` | Entrenar auto contra camioneta sobre esos recortes, con su prueba de humo |

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

#### El umbral se calibró con la cámara de lado, y eso no viaja solo

El múltiplo 1.58 se midió contra el conteo manual **con la cámara lateral**.
Viaja bien entre calzadas de esa cámara —está medido— pero nadie había
comprobado que viaje entre **cámaras**, y de frente la silueta es otra: de
lado un camión se ve larguísimo, de frente se ve alto y ancho.

`tools/silueta_clases.py` enseña lo que hay antes de entregar un desglose:
alto y ancho de cada clase de COCO **en la línea**, el umbral que la regla
va a aplicar, y de qué lado cae cada vehículo. Contesta tres preguntas:

- **¿El umbral lo alcanza alguien?** Si ningún `truck` lo pasa, o no hubo
  pesados en la muestra o el múltiplo no aplica a esa cámara.
- **¿Los `truck` salen en dos grupos?** El corte natural se busca con Otsu,
  que no mira ningún umbral nuestro, así que sirve de segunda opinión.
- **¿Las motos tienen silueta de moto?** Una moto es **angosta**. Una "moto"
  tan ancha como un automóvil es un automóvil mal etiquetado.

**Dos grupos pueden ser dos tipos o dos distancias, y confundirlos manda a
arreglar lo que no es.** Lo que los separa es el automóvil: un automóvil
siempre mide lo mismo, así que si el automóvil **también** sale en dos
grupos, lo que hay es una línea recogiendo dos calzadas. Probado contra el
proyecto 11, la calibración vieja: la herramienta avisa de la fuga de
`Carril 2` —207 cajas de mediana 76 px entre 783 de 17 px— **sin que nadie
le dijera que esa fuga existía.**

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
4. ~~Velocidad con dos líneas~~ — hecho, ver "Velocidad por tramo". Falta
   medir en campo la distancia de un tramo real para validar la cifra
   absoluta sin calibrar contra el tubo.
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

Esa tabla es de antes de corregir el rastreador. **Con el día recontado**
(horario medible, ambos sentidos): en las 5 horas con menos de 1 600
veh/h, **0.99×**; en las 5 con 2 000 o más, **0.91×**. La brecha se achicó
pero sigue, y casi toda está en la calzada del fondo (0.72× a las 15:00).

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

Las cámaras públicas de los puentes Juárez–El Paso (HLS, 1920×1080) se ven
nítidas y bien expuestas a la 01:00: la noche se puede grabar con otra
configuración de cámara.

**Esas mismas cámaras sirven para probar el modo en vivo**
(`tools/probar_camara_en_vivo.py`, URLs en la página oficial del
Fideicomiso de Puentes Fronterizos). De día, 2 min cada una: puente Zaragoza
15 vehículos por cuadro a 71 px, calle Stanton 5 por cuadro a 71 px. Llegan
19 cuadros por segundo y el Jetson procesa 12–13 a `imgsz` 1280 sobre el
cuadro completo: alcanza para rastrear, pero con una cámara en vivo de esa
resolución conviene bajar `input_size`.

### Velocidad por tramo (PT-914)

`src/engine/velocidad.py`. Como el contador de ejes: dos mangueras a una
distancia conocida y el tiempo que tarda el vehículo en pasar de una a otra.
Aquí la primera manguera es la línea de conteo y la segunda, una línea del
**tramo** que se dibuja en Calibrar ("Medir velocidad en este carril") con
la distancia en metros medida en el pavimento. Se usa el punto de apoyo,
igual que el contador y las zonas, e interpola el instante del cruce entre
cuadros.

- `lane_configs.tramo_json` = `{"linea": [[x, y], [x, y]], "distancia_m": 15}`.
- `crossings.tiempo_tramo_s` guarda el **tiempo**, no la velocidad. La
  velocidad sale al reportar con la distancia vigente, así que **corregir
  una distancia mal capturada corrige todo sin volver a contar** ("Corregir
  distancia" no marca los videos como desactualizados; "Mover la línea" sí).
- Fuera de 3–160 km/h no se reporta: es un rastro mal armado.
- Sale en `get_interval_counts` (por intervalo y por carril), el Reporte y
  la hoja VELOCIDAD del Excel. Solo en horas medibles.

**Lo que enseñó el contador de ejes de Juárez.** Los dos equipos del mismo
tramo no coinciden: pte-ote da 40.8 km/h de media y 46.7 de percentil 85
(creíble); **ote-pte da 93.3 km/h y clasifica casi todos los automóviles
como "2A-4T"**: tenía mal capturada la separación entre mangueras. Un error
en la distancia escala todas las velocidades por el mismo factor y no avisa.

**Control automático: el automóvil como regla.** Con la distancia del tramo
y lo que mide el recorrido en píxeles sale la escala, y con ella el alto de
los automóviles (`control_distancia`). Con la distancia buena salen de 1.39
y 1.54 m; con la del contador ote-pte habrían salido de 4.1 m. Fuera de
1.1–2.1 m el Reporte y el Excel piden revisar la distancia. Solo aplica si
el tramo corre de lado en la imagen (≤ 30°).

**Validación contra el contador pte-ote** (calzada del fondo, 14–17 px),
`tools/velocidad_contra_tubo.py` sobre recorridos de un video por hora. No
hay distancia medida en campo, así que se fija con la mediana de las 07:00 y
**se miden las otras 12 horas** (08:00–19:00, un video de 10 min por hora):

| | nuestro | contador de ejes |
|---|---|---|
| Percentil 85, error medio | **+0.8 km/h** | |
| Percentil 85, error absoluto medio | **1.3 km/h** | (46.4–47.1 km/h por hora) |
| Mediana, diferencia por hora | −0.3 a −2.4 km/h (≈ −4 %) | 40.6–42.7 km/h |
| Vehículos medidos por hora | 64–137 en 10 min | 115–167 en 15 min |

La bajada de las 11:00 la registran los dos (38.5 y 40.6 km/h de mediana).
El perfil por hora correlaciona r = +0.60, poco porque la velocidad real casi
no cambia en el día. La distancia implícita del tramo es 11.2 m para 112 px.
Contra el contador ote-pte (descompuesto, ×2.35) la calzada cercana solo
sirve para la forma: percentil 85 a ~1.5 km/h reales.

**El reparto sale más ancho que el real** (12 % bajo 32 km/h contra 4 %,
13 % entre 48 y 56 contra 4 %). No es el instante del cruce (ajustar una
recta al recorrido no lo angosta) ni un sesgo de pesados. Es geometría:
**las líneas se trazaron verticales en la imagen y no siguen la
perspectiva**, así que cada carril queda con otra distancia real. La
velocidad sube con cada carril más cercano a la cámara en las DOS calzadas
(37 → 45 km/h en la del fondo, 39 → 47 en la cercana), justo al revés de
lo que haría el comportamiento de los conductores en una de ellas.
Consecuencias:

- Se entregan media, mediana y percentil 85; **el percentil 15 no**, porque
  la cola lenta no aguanta.
- La pantalla pide trazar las dos líneas sobre marcas que crucen la
  calzada (raya de alto, paso peatonal, juntas), no a ojo.

Los **pesados son más lentos de verdad**: cajas de 22 px o más en la
calzada del fondo, mediana 34 km/h contra 42 de los automóviles. Borde
delantero, trasero y centro de la caja dan lo mismo, así que no es la caja
que cambia de tamaño.

Largo del tramo, sobre las mismas horas: de 5 a 29 m el percentil 85 queda
a ≤ 2.6 km/h; uno largo baja el ruido pero pierde vehículos (los rastros se
parten antes de cruzar las dos líneas). 10–20 m es el punto razonable.

---

## La cámara nueva de Cd. Juárez: de frente y a 2560×1440

El 19-sep-2026 la empresa volvió a grabar el mismo tramo con la cámara
**montada de frente a la vía** en vez de de lado, y a **2560×1440 a 20
cuadros por segundo** (16 veces más píxeles que los 640×360 anteriores). En
el Jetson está en `data/nuevos/20260919/HORA/MINUTO.mp4` y en la plataforma
es el **proyecto 7**, con dos zonas (una por calzada) y dos líneas atadas a
ellas.

Lo que cambia respecto al material viejo:

| | cámara vieja (de lado) | cámara nueva (de frente) |
|---|---|---|
| Resolución | 640×360 | **2560×1440** |
| Alto del vehículo en la línea | 14 px (fondo) / 41 px (cercana) | **115–150 px en las dos** |
| Confianza en el cruce | 0.55 / 0.86 | **0.85** |
| De noche | estelas, 0.03× del real | **se ven los vehículos** (20:00–23:59) |

**Cuidado con la hora: la leyenda de la cámara miente.** Desde las 12:25 la
fecha y hora impresas en la imagen se atrasaron cerca de un mes. Los videos
están completos, así que la hora de cada uno sale de **la carpeta y el
nombre del archivo**, nunca del OSD.

Otras cosas que aparecieron al cargarlo, y que conviene mirar en cualquier
entrega nueva:

- **Los primeros minutos no son de la vía.** De 10:40 a 11:47 la cámara
  grabó dentro del carro del instalador. Se detectan comparando una
  miniatura en gris de un cuadro de cada video contra uno de la escena buena
  (`data/nuevos/revisar_escena.py`): la correlación pasa de 0.15 a 0.55 en
  cuanto queda montada. Ojo, esa correlación también baja de día a noche por
  la luz, así que sirve para el arranque, no para separar escenas a ciegas.
- **Un archivo cortado.** El de las 12:25 pesa 2.3 MB contra 6–7 MB y no
  abre: a un MP4 interrumpido le falta el índice (`moov atom not found`). El
  script de carga revisa los 742 y descarta el que no abre.
- **El bitrate es bajo para esa resolución**: 817 kb/s. La nitidez sale en
  1 109 (los videos que cuentan bien andan en 2 400–4 700). Subirlo a 4–8
  Mb/s aprovecharía la resolución que la cámara ya entrega.
- **El brillo alto de mediodía no es sobreexposición.** Sobre la vía da 158
  con contraste 28; la noche mala de la cámara vieja daba 168–177 con
  contraste **70**. El diagnóstico ya distingue los dos casos.

### Cómo se verifica un aforo sin conteo manual de campo

Del 19-sep-2026 no hay aforo de campo, así que la referencia se fabrica del
propio video y **sin usar el detector**: `tools/barrido_linea.py` apila la
franja de píxeles que cae sobre la línea de conteo, cuadro a cuadro. Cada
vehículo que cruza deja una raya, y los cruces del sistema se marcan encima:
mancha sin marca es un vehículo no contado, marca sin mancha es un conteo de
más. Un lazo virtual (resta del fondo sobre esa misma imagen) cuenta las
rayas solo para **tamizar** qué minutos hay que mirar.

Lo que sí adjudica es `tools/hoja_cruces.py`: el recorte del cuadro exacto de
cada cruce. Así se vio, vehículo por vehículo, que una pickup salía dos veces
con los rastros 5802 y 5814 en el mismo segundo.

**Tres defectos encontrados así, en orden de tamaño:**

1. **El detector entregaba dos cajas del mismo vehículo** (IoU 0.97), una
   como `car` y otra como `truck`: el filtro de repetidas de YOLO compara
   solo dentro de cada clase. Ver `projects.nms_agnostico` — **es por
   proyecto**, porque en el material viejo (vehículo de 15 px, cajas que se
   enciman) comparar entre clases borra vehículos distintos.
2. **El rastreador creaba dos rastros de una misma detección** cuando su
   mejor emparejamiento quedaba bajo el umbral de IoU: entraba dos veces a
   la lista de "sin pareja".
3. **El antiduplicado del contador estaba en 6 px fijos**, medidos sobre
   640×360. Con 2560×1440 el vehículo mide 150 px y sus cajas duplicadas
   quedan a 20-40 px. Ahora es el mayor entre 6 px y 0.2 altos de caja; sobre
   el aforo viejo ya validado cambia como mucho 2 cruces por video (−0.36 %).

Resultado medido sobre los mismos minutos: los pares de cruces separados por
menos de 0.6 s en el mismo carril bajan de **10.7 % a 6.0 %**, y lo que queda
son vehículos de verdad juntos (revisados a ojo). Contra el lazo virtual el
sistema queda entre 1.03 y 1.06, y el lazo pierde motos y junta vehículos
pegados, así que esa diferencia es su límite, no necesariamente el nuestro.

### La regla de clase SÍ viaja a la cámara frontal, y ahora hay motos

La duda era legítima: el múltiplo 1.58 que separa liviano de pesado se
calibró contra el conteo manual **con la cámara de lado**, y de frente la
silueta del vehículo es otra. Medido con `tools/silueta_clases.py` sobre
2 675 cruces del proyecto 7:

| | hacia la cámara | alejándose |
|---|---|---|
| Automóvil mediano | 126 px | 124 px |
| Nivel del desglose | **medido** | **medido** |
| Umbral de la regla (1.58×) | 199 px | 196 px |
| **Corte natural de los `truck`** (Otsu, sin mirar nuestro umbral) | **213 px** | **211 px** |

**La regla corta a un 7 % del sitio donde los datos se parten solos.** Con
la cámara vieja la calzada del fondo era `estimado` (automóvil de 15 px) y
sólo valía la proporción; aquí las dos calzadas suben a `medido` por el
tamaño, sin tocar ningún umbral — que es justo lo que se esperaba de unos
umbrales físicos sobre la imagen.

Y los `truck` de COCO se parten en las dos poblaciones que la taxonomía SCT
necesita: **102 de mediana 150 px** (la troca, que es **A**) contra **78 de
mediana 306 px** (el camión de verdad), y 101 contra 61 en la otra calzada.

**La moto ahora se puede separar, y con la cámara vieja no se podía.** La
distingue el **ancho**, no el alto:

| | ancho/alto | ancho |
|---|---|---|
| Moto | **0.75–0.79** | 56–72 px |
| Automóvil | 1.35–1.68 | 173–217 px |

`crossings.bbox_width` se guarda desde el 23-sep-2026. Se captura al contar
porque **la clasificación se calcula al leer**: la regla se afina después
sin volver a procesar, pero la medida cruda se toma una sola vez.

**Así se verificó que el arreglo de la clase congelada funciona en
producción.** Las "motos" de 214 px de media que quedaban en la base
estaban **todas** en videos aún sin recontar; en lo ya recontado la moto
mide 75–93 px de alto y 64–90 de ancho. Se comprueba con una consulta que
cruza `crossings` contra `video_jobs.status`, no con el total.

**Cuidado al mirar las hojas de cruces con esta cámara.** `crossings.timestamp`
guarda sólo hasta el segundo, así que el recorte puede caer hasta un segundo
después del cruce; a 2560×1440 el vehículo ya se fue del sitio. Se compensa
con una banda alta (`--alto-banda`), y la celda ya no se encoge a 390 px
fijos (`--celda`), que hacía que una moto y un peatón se vieran igual.

### Contar por instante o por trayectoria: medido, dan lo mismo

`src/engine/conteo_trayectoria.py` cuenta al cerrar el video sobre el
recorrido completo —une los pedazos del mismo rastro y cada vehículo cuenta
una vez por línea—, que es la práctica aceptada para que un cambio de
identidad sobre la línea no cuente dos veces. Es la misma idea que subió el
direccional de Altozano de 0.74× a 0.99×.

Medido con `tools/comparar_metodo_conteo.py`, que corre los dos métodos
sobre la MISMA detección:

| minutos | instante | trayectoria | lazo virtual |
|---|---|---|---|
| 6 de mediodía tranquilos | 144 | **144** | — |
| 11:55, el más cargado (32 vehículos en un minuto) | 32 | **32** | 27 |
| 22:30, de noche | 12 | **12** | 12 |

**Con el detector ya corregido no hay rastros partidos que arreglar**, así
que los dos métodos coinciden y no vale la pena volver a contar el aforo
entero para cambiar de método. Queda como propiedad del proyecto
(`projects.conteo_trayectoria`, apagada) para una cámara donde el rastro sí
se parta. Sus umbrales de unión son propios —0.5 s de hueco y 0.8 altos de
caja, contra 1 s y 2 altos del direccional— porque con los del direccional
**dos vehículos que se siguen a medio segundo se fusionan en uno**; está en
la regresión `tools/probar_conteo_trayectoria.py`.

### Cuánta exactitud se puede sostener sin conteo manual

`tools/auditar_conteo.py`. Cuatro evidencias independientes, ninguna
sustituye a un aforo de campo pero juntas acotan el error:

| comprobación | resultado |
|---|---|
| Precisión, revisada vehículo por vehículo (`hoja_cruces.py`) | **81 de 81 cruces reales y distintos**, en tres minutos: uno cargado de día, uno normal y uno de noche |
| Conservación de flujo: cruzar la línea y también 60 px antes y después | **0.96** en 8 minutos repartidos (con el sesgo de las orillas del video dentro; ya se corrigió) |
| Estabilidad con la línea a otra altura (860 / 900 / 960 / 1020) | 33 / 33 / 32 / 32 y 17 / 17 / 17 / 18 → **±3 %** |
| Referencia ajena que sí existe: AI City cam_5 | **0.95×**, 9 de 12 movimientos con GEH < 5 |

Lo que ninguna ve es el vehículo que el detector **nunca** vio; para eso hace
falta el conteo manual. El lazo virtual del barrido sirve solo para tamizar:
en el minuto más cargado marcó 21 donde hay 32 verificados a ojo, porque
junta a los que cruzan pegados.

### Cada archivo que empieza cuesta ~1 % del conteo

Medido sobre 52 videos ya contados del aforo frontal, contando los cruces
por segundo **dentro** de cada archivo:

| | cruces respecto a lo normal |
|---|---|
| segundo 0 del archivo | **48 %** |
| segundo 1 | **76 %** |
| segundo 2 en adelante | normal |
| segundos 58 y 59 | 112 % |

El vehículo que va cruzando la línea justo cuando **empieza** el archivo no
se cuenta: el rastreador necesita ver la caja unos cuadros antes de la línea
para registrar el cruce, y al arrancar el archivo ese pasado no existe. El
repunte del final es el mismo vehículo, contado por el archivo siguiente,
pero no alcanza a compensar: el neto es **alrededor del 1 % hacia abajo**.

Con 730 archivos de un minuto ese 1 % se paga 730 veces. `unir_segmentos.py`
los pega en tramos de 10 minutos y lo baja a una décima parte.

**Lo que unir los segmentos NO arregla, también medido:**

- **No acelera.** La cola no tiene un segundo muerto entre videos: el
  `finished_at` de uno es el `started_at` del siguiente. No hay costo fijo
  por archivo que ahorrar; el trabajo es por cuadro (159–165 s por minuto
  de video, o sea 2.7× tiempo real).
- **No ahorra disco.** Los mismos bytes en menos archivos.

**El riesgo de pegarlos es que se corran las horas, y es serio.** La hora de
cada cruce sale de la hora de inicio del archivo más el número de cuadro. Si
falta un minuto en medio, todo lo que sigue queda corrido **sin un solo
error en el log**. En este material ya hay un archivo cortado (el de las
12:25). Por eso la herramienta solo pega minutos consecutivos, exige que
cada parte dure lo que dice, y **comprueba la duración del tramo contra la
suma de sus partes**, descartándolo si no cuadra. Nunca borra los originales.

### Cuatro clases con la cámara frontal, y una que NO se puede

Con el automóvil a 123–126 px (contra 15–41 px de la cámara vieja) se midió
qué se puede separar de verdad. Sobre **10 146 cruces**, el alto de cada
vehículo como múltiplo del automóvil mediano de su calzada:

| razón del alto | hacia la cámara | alejándose |
|---|---|---|
| 0.50–0.80 | **120 motos**, 23 autos | **101 motos**, 2 autos |
| 0.80–1.40 | 4 230 autos + 35 `truck` | 4 118 autos + 330 `truck` |
| 1.40–1.60 | 38 autos + 21 `truck` | 15 autos + 39 `truck` |
| 1.60 o más | 3 autos + **289 pesados** | 0 autos + **298 pesados** |

**Entre automóvil y troca NO hay valle, y por eso no se separan.** La clase
`car` de COCO ya trae SUV, crossovers y minivans, que miden lo mismo que una
pickup: los automóviles se extienden de 0.80 a 1.40 sin ningún hueco donde
poner un umbral. En la clasificación SCT la pickup es **A** de todos modos,
así que el entregable no lo necesita.

**Y la etiqueta `truck` de COCO tampoco sirve para contarlas, aunque acierte
cuando la da.** Mirando los recortes, `truck` bajo el umbral de pesado salió
**8 de 8** camioneta de verdad (cinco pickups, un Bronco, una Ranger, una
Traverse): tiene buena precisión. Lo que no tiene es cobertura, y se mide en
una sola línea:

| calzada | qué se ve del vehículo | COCO dice `truck` |
|---|---|---|
| Hacia la cámara | el frente | **1.2 %** (55 de 4 465) |
| Alejándose | la parte de atrás | **7.6 %** (367 de 4 856) |

Misma vía, mismo día, los mismos vehículos yendo y volviendo: **seis veces
más "trocas" en un sentido que en el otro.** Por detrás se le ve la caja a
la pickup y YOLO dice `truck`; de frente parece un automóvil grande y dice
`car`. **La etiqueta mide el ángulo, no el vehículo**, así que contar
camionetas con ella daría un número que cambia con la dirección.

En la hoja de los `car` altos (145–175 px) se ve el otro lado del mismo
problema: 4 de 5 eran camionetas y SUV etiquetadas `car`, una de ellas una
pickup clarísima a 0.67 de confianza.

**Separar automóvil de camioneta necesita otro modelo, no otro umbral.** Lo
que hay hoy es un detector entrenado en COCO, que no tiene la clase. Antes de
intentarlo, medir contra recortes etiquetados a mano en DOS horas distintas:
el modelo de visión ya dio 36/36 a mediodía y 28/40 a las 07:00.

**El entrenamiento NO es el cuello de botella, y está medido.** Un
`mobilenet_v3_small` de dos salidas (auto / camioneta) sobre recortes, en la
GTX 1650 de la PC de desarrollo:

| lote y tamaño | imágenes/s | pico de memoria | 10 000 recortes × 30 épocas |
|---|---|---|---|
| 64 a 128 px | 1 803 | 0.37 GB | **2.8 min** |
| 32 a 224 px | 678 | 0.53 GB | 7.4 min |

Son **minutos y medio giga**. El Orin Nano es 1.3 veces más lento, así que
ahí serían 4–10 min y cabe de sobra en los 6 GB del contenedor — pero **no
mientras la cola cuenta**, por el conflicto de GPU ya documentado.

Consecuencias:

- **No hace falta la nube.** Con esto no hay motivo para subir el video del
  cliente a un servicio de terceros.
- **El cuello de botella es ETIQUETAR**, no entrenar. Un clasificador binario
  sobre el recorte del cruce (moto, autobús y camión ya los resuelve la regla
  del alto) necesita del orden de 1 000–2 000 ejemplos por clase.
- Conviene partir de pesos **preentrenados de torchvision** (ImageNet), que
  además son de licencia libre para uso comercial, a diferencia de
  Ultralytics, que es AGPL-3.0.
- El clasificador corre **solo en el instante del cruce**, no en cada cuadro:
  unas decenas de inferencias por minuto de video contra 1 200 del detector.

**Lo que sí se puede, verificado mirando los recortes (15 de 15):**

| clase | cómo se decide | verificado |
|---|---|---|
| `MOTO` | `motorcycle` de COCO **y** silueta angosta | 221 motos; el corte rechaza 1 de 133 falsa |
| `A` | todo lo demás bajo el umbral de pesado | 5 trocas de 5 (RAM, GMC, F-150…) |
| `B` autobús | `bus` de COCO | 4 de 4, a 0.93 de confianza y 240–257 px |
| `C` camión | sobre el umbral de pesado | 6 de 6 (Freightliner, International, volteo Scania…) |

El **autobús aparte es nuevo**: con la cámara vieja medía 65–90 px y YOLO no
lo separaba del camión, y estaba documentado como imposible. A 245 px sí.

**La moto la distingue el ANCHO, no el alto.** Una moto es angosta: razón
ancho/alto de **0.68–0.81** contra **1.37–1.69** del automóvil. El corte va
como fracción de la silueta del automóvil **de esa misma calzada**
(`MOTO_RAZON = 0.7`), no en un número fijo, porque la razón depende del
ángulo: el mismo automóvil da 1.69 en una calzada y 1.37 en la otra.

**Las clases finas sólo salen donde están medidas.** `ALTO_FINO = 100` px de
automóvil mediano — que es donde se verificaron, no un número elegido. Entre
25 y 100 px no está probado, y se prefiere no dar la clase a darla mal: una
clase equivocada cambia el entregable. Con la cámara vieja el sistema sigue
entregando `A` / `PESADO` exactamente como antes, y eso está en la
regresión (`tools/probar_clasificacion.py`, 30 casos con los vehículos
reales de las hojas).

### El video anotado cuesta 25 % del tiempo y más disco que el original

Medido en el aforo frontal: el anotado ocupa **31.3 MB por minuto** contra
los 16 MB del archivo de la cámara, así que con 730 videos son **23 GB** —
más que el material original. Y cuesta 22 ms de dibujo + 15 de escritura de
los ~150 ms por cuadro, **más una pasada entera de ffmpeg** al terminar cada
video.

`projects.video_anotado` lo apaga por proyecto. Apagado, el visor en vivo
sigue funcionando (se dibuja un cuadro por segundo). Vale la pena encendido
para revisar un aforo nuevo; no para un día entero ya calibrado.

**Medido al apagarlo, en el mismo material y la misma máquina:**

| | por minuto de video |
|---|---|
| Con video anotado | 163, 163, 165 s |
| **Sin video anotado** | **97, 98 s** |

**40 % menos**, más de lo estimado (25 %) porque además desaparece la pasada
de ffmpeg. De 2.7× tiempo real a 1.6×: las 677 horas de video que quedaban
pasan de ~30 h de proceso a ~18 h.

Un video que ya se contó antes conserva el anotado de **esa** vez, así que al
recontarlo con la opción apagada **se borra y se limpia la ruta**: dejarlo
sería ofrecer en la pantalla un video cuyas cajas y totales dibujados son los
del conteo viejo.

**Al agregarlo aparecieron dos valores que existían y no se leían**, la
misma trampa de `input_size` de la que ya hay sección: la API aceptaba
`nms_agnostico` y `conteo_trayectoria` al **crear** un proyecto y nunca los
pasaba a la base, y `update_project` los filtraba de los campos permitidos.
O sea que no había forma de encenderlos desde la plataforma, ni al crear ni
después. Al agregar una bandera nueva, **seguirla hasta la base y hasta el
procesador.**

### Dónde poner la línea, medido

Sobre el minuto más cargado, detectando una sola vez y moviendo solo la
línea (calzada hacia la cámara):

| altura | cruces | alto del vehículo |
|---|---|---|
| y = 900 | 33 | 104 px |
| **y = 960 (la puesta)** | **32** | **128 px** |
| y = 1020 | 32 | 156 px |
| y = 1080 | **24** | 182 px |

A y=1080 se pierden 9 vehículos: a esa altura ya salen del cuadro por la
orilla izquierda antes de cruzar. El cruce de más de y=900 no es un vehículo
perdido — es una pickup que cruza en el último segundo del minuto, y con la
línea en 960 la cuenta el video siguiente. En un aforo continuo se cuenta una
sola vez igual.

### La noche SÍ se puede contar con esta cámara

Lo que con la cámara vieja era 0.03× del tránsito real. Minuto de las 22:30,
contado y revisado vehículo por vehículo con `hoja_cruces.py`:

- **12 vehículos, los 12 reales y distintos** (4 hacia la cámara, 8
  alejándose). Instante, trayectoria y lazo virtual coinciden en los tres.
- El vehículo mide **116–144 px** en la línea y el detector lo ve con
  **0.63–0.89** de confianza, aunque en la imagen sea una mancha de luces.

El obturador sigue siendo lento (el vehículo sale barrido), pero a esta
resolución y con el encuadre de frente la caja es lo bastante grande para
contar. Es el cambio más valioso del aforo nuevo: recupera las horas que
antes se declaraban no medibles.

**Sin conteo manual de campo no hay razón que reportar.** Lo verificable hoy
es que no sobrecuenta (38 cruces revisados uno por uno, todos vehículos
distintos y reales) y que el tamaño del vehículo en la línea pasó de 14-41 px
a 115-150 px. Para dar una razón hace falta que la empresa cuente a mano unos
cuartos de hora de este video.

**Cuánto tarda** (Orin Nano, cuadro de 2560×1440 con la franja de la vía):
49 ms detectar + 22 dibujar + 15 escribir + 14 rastrear + 13 leer = ~150 ms
por cuadro, o sea **~2.5 min por cada minuto de video** y unas 30 h para las
12 h de grabación. Dos cosas medidas al respecto:

- El video anotado se escribe a **1280 de ancho** y no a 2560: escribirlo y
  recodificarlo a resolución completa costaba más que detectar (4 min por
  minuto de video contra 2.5). La detección sigue sobre el cuadro completo.
- Bajar `input_size` de 1280 a 960 ahorra 18 ms por cuadro y conserva las
  detecciones grandes (83 de 83 por encima de 100 px), pero pierde las del
  fondo (4.56 contra 5.30 vehículos por cuadro). **No se cambió**: ahorra
  12 % del total y toca un parámetro validado.

---

## Estado de la beta (23-sep-2026)

Lo que está corriendo y verificado en el Jetson, proyecto **7**
("Cd. Juárez — frontal 19-sep-2026"):

| | |
|---|---|
| Videos | 730 de un minuto, 11:00–23:59 |
| Contados | ~390 al momento de escribir, el resto en cola |
| Ritmo | **112 s por minuto de video** (1.9× tiempo real) |
| Clasificación | **MOTO / A / B / C**, las dos calzadas en nivel `medido` |
| Composición | A 92.1 %, C 3.7 %, MOTO 2.3 %, B 1.9 % |
| Regresiones | 30 + 9 + 9 + 4 casos, **0 fallos**, corriendo dentro del contenedor |

**Lo que NO se puede declarar todavía:** una razón contra el aforo real. De
este video no hay conteo manual de campo, así que lo verificable es que no
sobrecuenta (cruces revisados uno por uno) y que la clasificación acierta
(15 de 15 a ojo). **Para dar una razón hace falta que la empresa cuente a
mano unos cuartos de hora de este mismo video.**

Pendiente inmediato, con las herramientas ya listas: etiquetar recortes y
entrenar el clasificador de automóvil contra camioneta. El exportador ya
deja recortes utilizables —se ven perfectamente— y de los primeros 12, todos
marcados `car` por COCO, **al menos 4 son camionetas**, que es exactamente
el problema que el clasificador viene a resolver.

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

### Decidir por trayectoria: Entrada y salida Altozano de 0.74x a 0.99x

El motor decidía cada movimiento **solo por las zonas** que pisaba el
vehículo. Mirando los recorridos de los 5 videos de 07:16 a 08:06 aparecieron
dos fallas, y ninguna era de detección:

1. **Exige ver al vehículo entrar Y salir.** El letrero de peatones que hay
   justo después del arco parte casi todos los rastros; el pedazo de antes y
   el de después quedaban como dos incompletos.
2. **Una zona que roza el carril de otro flujo inventa un movimiento.** La
   esquina de "Derecha" alcanza el carril derecho de la salida del arco: **92
   vehículos del movimiento principal** la tocaban antes de que el letrero
   los tapara y quedaban como si fueran a ese acceso.

**El emparejamiento "de menos error" escondía la segunda.** Mandaba
"Derecha" al acceso 3 para rescatar esos 92. Por geometría —croquis del
Excel, sombras de la mañana, el canal a la izquierda al fondo— la cámara
está sobre la calle 3 mirando al sur: **Arco = 2, Fondo izq = 1 (camino junto
al canal), Izquierda y Abajo = 3, y Derecha es un camino de terracería que
el manual no cuenta.** Con pocos cuartos de hora, el emparejamiento libre
rescata dibujos equivocados; `comparar_od_real.py` y `od_por_trayectoria.py`
aceptan `--asignacion` para fijarlo por geometría.

**Cómo decide ahora** (`src/engine/od_trayectoria.py`), como los mejores
equipos del AI City Challenge 2021 en conteo por movimiento (en Jetson):
cada vehículo se compara contra los recorridos representativos de cada
movimiento, sacados de los completos del propio aforo.

- Hasta 12 recorridos por movimiento, no uno: un movimiento es una franja
  (dos carriles). Con un solo medoide, que "Arco -> Derecha" se reconociera
  como parte de "Arco -> Izquierda" dependía del carril del medoide.
- Separación = el punto **más** alejado, en altos de caja. Con el percentil
  90, "hacia Derecha" cabía dentro de "vuelta al camino del fondo" porque
  solo sus últimos puntos se apartan.
- Una plantilla contenida en otra es esa otra vista a medias, **salvo** que
  sus rastros mueran dentro de su zona de destino: los de "Abajo -> Derecha"
  mueren ahí (se van detrás del árbol, 100 %), los de "Arco -> Derecha" no
  (5 %: solo la rozan).
- Un incompleto va al movimiento más probable (cercanía × cuántos lo hacen)
  si pasa por la franja, en su sentido, cubre un cuarto del recorrido y la
  probabilidad pasa de 0.9. Sin contar cuántos lo hacen, 112 de 116 quedaban
  ambiguos entre el principal (553 completos) y uno de 4 que comparte la cola.
- Los pedazos de un mismo movimiento que pueden ser el mismo vehículo
  cuentan una vez. **Para contar no importa confundir a dos vehículos del
  mismo movimiento**, así que aquí se tolera el hueco largo que en la unión
  de rastros juntaba vehículos distintos. Revisado a ojo: los pares son el
  pedazo que muere en el letrero y el que sigue del otro lado.
- Los completos de una zona rozada son PEDAZOS, no completos: contados como
  completos, el mismo vehículo se contaba otra vez al reaparecer tras el
  letrero (2_3 salía en 1.13x hasta corregirlo).

Medido con `tools/od_por_trayectoria.py` (7:15 al 91 % cubierto y 7:30),
con plantillas de **otros videos** del mismo aforo (07:46 y 07:56) para no
medir sobre lo aprendido:

| | total | razón | GEH < 5 | 2_3 |
|---|---|---|---|---|
| manual | 468 | | | 434 |
| zonas (asignación geométrica) | 346 | 0.74x | 2 de 6 | 334 (GEH 7.4) |
| **trayectoria** | **462** | **0.99x** | **4 de 6** | **457 (GEH 1.6)** |

Por cuarto de hora: 7:15 193 / 157 / 198 y 7:30 275 / 189 / 264. Con las
plantillas de todos los videos da lo mismo (463). Y por el camino de
producción de punta a punta —el motor real alimentado con los rastros,
`record_movimientos`, `get_matriz_od` y `comparar_od_real.py` sobre una base
de prueba— el cuarto de las 7:30 pasa de **193/275 (70 %) a 266/275 (97 %)**.

**Dos candados, medidos donde la cámara NO cubre el cruce.** Sin ellos, en
la Glorieta el método **inventó 421 vueltas en U**: pedazos de movimientos
que la cámara nunca ve completos se pegaban a la única plantilla parecida.

- Una vuelta en U nunca se completa con pedazos: se define por el regreso.
- Un movimiento no se completa con más pedazos que completos vistos. En
  Altozano el principal usó 0.4 por completo; en la Glorieta, 59.

Con los candados la Glorieta queda **exactamente igual** que por zonas
(0.03x, 5 de 9) y Blvd Independencia no empeora (0.51x → 0.60x, 2 de 16
igual). **El método no arregla una cámara que no ve el cruce; recupera lo
que una buena cámara pierde por un obstáculo.**

**Lo que no sale: 1_3 y 3_1** (14 y 13 en la ventana). Pasan por el camino
del fondo, donde el vehículo mide ~15 px, y la vuelta la comparten con el
tránsito del arco: extender ahí el acceso 1 le pondría origen falso a 41
rastros del movimiento principal. Es límite de la cámara, no del método.

En producción, `AforoDireccional.cerrar` guarda un recorrido de 48 puntos
por vehículo (`movimientos.recorrido`) y `get_matriz_od` decide por
trayectoria por omisión (`metodo=zonas` para lo de antes, y lo que se contó
sin recorrido se sigue decidiendo por zonas). El Excel y el reporte dicen
cuántos se decidieron de cada forma.

**Verificado en el Jetson con el proyecto 5 recontado** (6 videos, 1 081
movimientos, todos con recorrido), con `comparar_od_real.py --asignacion`,
que lee por `get_matriz_od` igual que el informe:

| 7:30 | zonas | trayectoria | manual |
|---|---|---|---|
| total | 194 (71 %) | **266 (97 %)** | 275 |
| 2_3 | 186 (GEH 8.9) | **260 (GEH 1.0)** | 252 |
| sin decidir | 144 | 66 | |

Idéntico a la prueba sin GPU. Decidir cuesta 5.7 s la primera vez en el
Jetson y 0.02 s después: se guarda mientras los movimientos no cambien.

**El volumen por acceso NO se pasa a trayectoria**, y está medido: a las
7:30 por trayectoria el arco daba 306 entradas contra 253 del manual (el
pedazo sin decidir y el completado de un mismo vehículo contaban cada uno
su entrada); por zonas, 271. Se queda por zonas (5 de 6 cifras con GEH < 5
con la asignación geométrica) y solo se toma una corrección de la
trayectoria: **una zona rozada no es una salida**. Las salidas falsas hacia
el camino que el manual no cuenta bajan de 34 a 9 sin mover ninguna otra
cifra.

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

### Contra una referencia ajena: AI City 2021, cam_5

El conjunto AI City 2021 Track 1 está en el Jetson
(`data/aicity/AIC21_Track1_Vehicle_Counting/`: 31 videos de 20 cámaras de
EE. UU., con lluvia, nieve y amanecer). **No trae el conteo de referencia
completo**: los organizadores lo guardaron para calificar y solo publicaron
el primer minuto de cam_5 (96 vehículos, 12 movimientos). Se buscó y ningún
equipo lo publicó; no volver a buscarlo.

cam_5 es un ojo de pez de 1280×960 a 10 cuadros por segundo, un cruce de
cuatro brazos. Rastros con ByteTrack, accesos dibujados donde nacen y mueren
los rastros (`data/aicity/accesos_cam_5.json`, sin mirar la referencia), y
los 12 movimientos asignados por la geometría de sus flechas:

| | total | GEH < 5 | error sumado |
|---|---|---|---|
| referencia AI City | 96 | | |
| solo por zonas | 78 (0.81×) | 6 de 12 | 18 |
| **por trayectoria (producción)** | **91 (0.95×)** | **9 de 12** | **9** |

Los cuatro movimientos grandes casi exactos (38/38, 27/25, 12/13, 10/10); se
pierden los chicos que salen por la orilla inferior derecha del ojo de pez.
La misma ganancia de la trayectoria que en Altozano, en otra cámara, otro
país y otro lente. Es **un minuto**, con plantillas del mismo minuto: indica,
no valida.

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

**Puesto a prueba en 20 cámaras ajenas (AI City, 31 grabaciones, 22-sep-2026)**,
todas elegidas por el reto para contar movimientos: **15 salían "no
recomendable"**, incluida cam_5, cuyo direccional dio 0.95× contra la
referencia humana. Dos defectos, medidos:

1. **Calificaba todo el cuadro.** Más de la mitad de las detecciones caían en
   estacionamientos y calles que no se cuentan. Alto mediano en el cuadro
   contra dentro de la región de conteo: cam_5 26 → 35 px, cam_4 24 → 41,
   cam_10 23 → 106. Ahora, con zonas dibujadas, mide solo dentro de ellas
   (la API usa las del proyecto; la herramienta acepta `--zona`, también el
   formato ROI de AI City). Sin zonas mide todo y lo dice (`region`).
2. **La concentración en 6 celdas castiga cualquier cruce grande**: muchos
   carriles y la fila del semáforo reparten los extremos aunque el vehículo
   se vea completo. Sola ya no reprueba (tope ámbar); sigue reprobando lo
   fatal, casi nada en la orilla (Glorieta, 1 %).

Con los dos arreglos: 0 rojos, 22 regular, 9 bueno; los rojos de nuestros
casos malos se conservan y cam_5 entró como noveno caso de la regresión.
Ojo con el ojo de pez: la "orilla" es la del círculo, no la del rectángulo,
y la medida de borde sale baja aunque el vehículo sí entre por ahí.

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

**Un cambio de Python ya NO necesita reconstruir.** `src/` y `tools/` se
montan desde el host de solo lectura, así que lo que corre es el checkout:

```bash
git pull && docker compose -f docker-compose.jetson.yml up -d
```

Eso tarda segundos. Antes iba todo horneado con el argumento de que así no
se desincroniza — y la experiencia dijo lo contrario: reconstruir aquí tarda
una o dos horas (42 GB compitiendo con la cola por CPU) y **`up -d --build`
falla en silencio**. Pasó dos veces el mismo día, una por el disco lleno y
otra por una caída de red, y las dos veces el contenedor siguió con código
viejo pareciendo sano. Montado se comprueba con un `git log`.

**El frontend sí se construye dentro de la imagen**, así que un cambio de
interfaz (`web/`) sigue necesitando reconstruir:

```bash
git pull && docker compose -f docker-compose.jetson.yml up -d --build
```

**Cada reconstrucción deja basura, y `docker image prune` no la quita
toda.** El disco del Jetson llegó al **100 %** y `up -d --build` empezó a
**fallar en silencio**: la salida dice "Building" y el contenedor sigue con
el código viejo, así que un arreglo parece desplegado y no lo está.

Lo que llena el disco son **dos** cosas y sólo se ve pidiéndolas por
separado con `docker system df`:

| | medido el 23-sep-2026 |
|---|---|
| Imágenes colgadas (18 GB cada una) | 10 GB |
| **Caché de construcción** | **134.6 GB** |

`docker image prune -f` reportó **0 B** recuperados con 134 GB de caché
esperando: no la toca. Las dos, siempre, después de reconstruir:

```bash
docker builder prune -f && docker image prune -a -f --filter "until=24h"
```

Eso dejó el disco en 27 % (327 GB libres) desde 57 %.

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
