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
| `reporte_avance_pdf.py` | Reporte de avance en PDF para presentar a la empresa |
| `mover_proyecto.py` | Llevar un proyecto calibrado de una máquina a otra |

---

## Estado actual

El aforo **ya está contado en el Jetson y contrastado contra medición de
campo**. Es el proyecto **2 del Jetson**, "Cd. Juárez — Aforo matutino":
18 videos de 07:00 a 09:59, **4 671 cruces**, dos líneas (`Carril 1` →
Calzada oriente, `Carril 2` → Calzada poniente) atadas a sus zonas.

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

#### El módulo, y por qué se niega a clasificar

`src/engine/clasificacion.py` traduce las clases de COCO a la taxonomía de
la empresa. Lo importante es lo que **no** hace:

| calzada | umbral | resultado |
|---|---|---|
| Oriente (cercana) | 52.1 px | A 0.98×, PESADO 1.01× |
| Poniente (fondo) | ninguno | **todo SIN_RESOLVER** |

Sin umbral no se clasifica **nada**, ni siquiera lo que COCO llama `car`.
Es deliberado: donde el vehículo mide 15 px la etiqueta de COCO tampoco es
de fiar (confianza media 0.66). Clasificar solo los `car` dejaba escapar una
cifra parcial que se lee como total — daba "A = 1 800" en la calzada del
fondo cuando el conteo manual dice 2 420.

**Es preferible no dar el dato que darlo mal.**

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

1. **Marcar las horas nocturnas** (20:00–05:00) como no medibles en el
   reporte, en vez de omitirlas. Es el mismo principio que ya aplica la
   clasificación: declarar lo que no se puede medir.
2. **Extender a las 24 horas.** El conteo manual cubre el día completo, así
   que hay contra qué contrastar cada hora. Un día entero sale en unas 15 h
   de proceso en el Jetson.
3. **El reporte por calzada.** `crossings.zone_id` ya guarda el dato; la
   pantalla todavía agrupa por línea.
4. **Marcar las horas nocturnas** (20:00–05:00) como no medibles en el
   reporte, en vez de omitirlas.
5. **Velocidad con dos líneas** (lo pide la PT-914) — además de dato
   vendible, sirve de control: una velocidad imposible delata un rastro mal
   armado. El contador de ejes trae su propia tabla de velocidad por
   intervalo, así que aquí también hay contra qué contrastar.
6. **Validar la clasificación de vehículos.** El reporte dice "73.8 %
   automóviles" y eso nunca se ha comprobado. Ahora sí hay referencia: el
   contador reparte ote-pte en 5 % `Cars` + 57 % `2A-4T` (camionetas) +
   20 % `2A-SU`. Ojo al comparar: la clase `car` de YOLO cubre a la vez
   `Cars` y `2A-4T`, así que lo comparable es la suma, ~62 %.

Sin empezar: IA visual e IA validadora con las APIs gratuitas de NVIDIA. El
cliente NVIDIA (`src/ai/nvidia_client.py`) ya está construido y verificado,
y el RAG ya está en marcha sobre él.

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
