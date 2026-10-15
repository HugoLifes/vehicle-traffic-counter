# Precisión con las cámaras que hay, y una plataforma que crezca

*15-oct-2026. Para la empresa: somos independientes, no hay presupuesto para
cámaras nuevas por ahora, y la plataforma tiene que aguantar que mañana haya
más cámaras, más equipos o más visión.*

Regla de todo el documento: **nada de esto se da por bueno hasta medirlo
contra un conteo a mano**, con una hora para ajustar y OTRA hora para
comprobar. Cada propuesta dice cómo se mide.

---

## 1. Dónde estamos, medido

| Intersección | Cámara | Plataforma / a mano (6:45–7:45) | GEH < 5 | Qué limita |
|---|---|---|---|---|
| Calle terracería | 1280×720, vehículo de 40–70 px | 152 / 147 (103 %) | 6 de 6 | nada importante |
| Fraccionamiento | 1280×720, 16–20 px al fondo | 707 / 758 (93 %) | 5 de 5 | el carril del fondo se tapa; dos vueltas fuera de cuadro |
| Gómez Morín | 640×360 en blanco y negro | 1 380 / 3 014 (46 %) | 1 de 6 | la calzada lejana no está en el archivo |
| Frontal de Juárez (por línea) | 2560×1440, 115–150 px | 13 463 / 13 477 (1.00×) | 53 de 54 cuartos | — |

**Lo que dicen juntas:** cuando el vehículo mide 40 px o más y se ven los
brazos, la plataforma ya cuadra con el conteo a mano. Lo que se pierde se
pierde en vehículos de menos de 20 px, en lo que tapa otro vehículo y en lo que
pasa fuera de cuadro. Por eso abajo van primero los ajustes de **cámara que no
cuestan** y después los de software, y cada uno dice a cuál de esas tres
pérdidas ataca.

### La referencia también se equivoca

Antes de perseguir el último 5 %, conviene saber cuánto se equivoca el conteo
a mano. Lo poco publicado apunta a que no es exacto:

- En peatones, el conteo a mano contra video **subcuenta de 8 a 25 %**, más al
  principio y al final del turno
  ([Berkeley SafeTREC](https://its.berkeley.edu/node/3135),
  [eScholarship](https://escholarship.org/uc/item/208349wf)).
- Purdue midió la fiabilidad del conteo de vueltas en intersección: los
  aforadores mejoran del primer al tercer día, o sea que el primero se
  equivoca más ([Shoup et al., JTRP](https://docs.lib.purdue.edu/jtrpdocs/6)).
- Dos personas contando el mismo video difieren entre sí tanto como el conteo
  automático difiere de ellas ([arXiv 0810.4590](https://arxiv.org/pdf/0810.4590)).

Ya nos pasó: el cuarto de las 16:45 del frontal salió 249 contra 207, y los 28
vehículos del minuto más cargado, revisados uno por uno, eran reales. Por eso
la **aceptación va por GEH < 5 en el 85 % de los movimientos**, que tolera el
error de los dos lados, y no por igualar la cifra.

---

## 2. Cámara: ajustes gratis, sin comprar nada

Son ajustes del menú de la cámara o del grabador. Cada uno se comprueba
grabando 10 minutos y pasando el video por **Revisar encuadre** y por
`tools/calidad_video.py`, antes de ir a campo en serio.

| # | Ajuste | Por qué, con dato nuestro | Cómo se comprueba |
|---|---|---|---|
| 1 | **Grabar el flujo principal, no el secundario** | Gómez Morín llegó a 640×360. Muchos grabadores guardan el *substream* (640×360 o 704×480) aunque la cámara dé 1080p. Si fue eso, es un cambio de menú y Gómez Morín habría salido como Terracería. | Resolución del archivo en `calidad_video.py` |
| 2 | **Bitrate de 4–8 Mb/s a 1080p o más; 2–4 Mb/s a 720p** | El frontal grababa 2560×1440 a 817 kb/s: nitidez 1 109 contra 2 400–4 700 de los videos que cuentan bien. Ahí se pierde la resolución que la cámara sí entrega. | Nitidez en `calidad_video.py` |
| 3 | **Apagar el códec "inteligente"** (H.264+/H.265+, *smart codec*, GOP largo) | Ahorra disco cuando la escena está quieta y emborrona lo que se mueve, que es justo el vehículo. | Recortes de cruce con `hoja_cruces.py` |
| 4 | **Cuadros por segundo fijos** (sin "ahorro" de cuadros de noche) | Las cámaras de los direccionales declaraban 15 cuadros/s y de noche grababan 10: las horas se comprimían sin un solo error. Ya lo corrige `reloj_video.py`, pero un ritmo fijo quita el problema de raíz. | `reloj_video.medir_fps` |
| 5 | **Obturador rápido de noche** (1/250 s o menos) y ganancia máxima limitada | Con la cámara lateral la noche dio 0.03×. No era falta de luz sino sobreexposición: brillo 168–177 contra 84 de día, y el vehículo hecho una estela. | `inspeccionar.py --zoom-carriles` sobre 10 min nocturnos |
| 6 | **Color forzado, sin infrarrojo**, donde haya alumbrado público | Gómez Morín salió en blanco y negro: el infrarrojo se activó. Con alumbrado, el color se ve mejor. | Ver el cuadro |
| 7 | **Reloj en hora (NTP) y una foto de un reloj al instalar** | La leyenda del frontal saltó 22 días y 4 h 55 min. El nombre del archivo era el bueno, y solo se supo por el sol. | `revisar_reloj.py` |
| 8 | **Encuadre: el carril más lejano a 40 px o más** | La cámara puede quedar donde está y solo apretar el zoom o girarla hacia la zona donde se cuenta. En Juárez, la línea movida hacia donde el vehículo era más grande pasó de 0.29× a 1.04×. | "Alto del vehículo" en Revisar encuadre |
| 9 | **Altura: lo más alto que permita el poste** | La oclusión crece con el tránsito (r = −0.83 contra el volumen). Desde más arriba un vehículo tapa menos al de atrás. | Razón por hora contra el volumen |

Los puntos 1 a 4 se pueden revisar **hoy, en las cámaras que ya tienen**, sin
salir a campo: basta abrir el menú del grabador.

**Una hoja de instalación de una página** para quien monta la cámara
convertiría esto en costumbre. Hoy existe `docs/REQUISITOS_CAMARA.md`, pero es
para comprar cámaras; falta la de *configurar* las que hay.

---

## 3. Software: lo que más precisión da, por orden

### 3.1 Calibrar contra una hora contada a mano, desde la plataforma

**Qué:** generalizar lo que se hizo a mano en Fraccionamiento. Hoy los
umbrales por sentido (`umbral_linea_sentido`: sale 0.25, entra 0.10) se
fijaron a mano. La plataforma puede hacerlo sola:

1. La empresa sube el Excel de campo; eso ya existe en la tarjeta *Precisión
   contra el conteo a mano*.
2. Se detecta UNA vez a confianza baja (0.05) y se guardan las cajas. Ese
   mecanismo ya existe (`extraer_trayectorias.py --guardar-detecciones`) y
   filtrar después da lo mismo que producción.
3. En el CPU, sin GPU, se prueban umbrales por línea y sentido y se elige el
   que mejor cuadra el GEH **en una hora**.
4. Se comprueba en **otra hora**. Si no pasa ahí, no se aplica y se avisa.

**Por qué:** en Fraccionamiento, el umbral por sentido llevó 1_3 y 3_1 a
GEH 2.3 y 1.0 y el total a 707/758 con 5 de 5. Es la palanca más probada que
hay, y hoy depende de que alguien la mueva a mano.

**Cuánto:** en cámaras como Fraccionamiento, de 3 a 7 puntos de razón. En
Terracería, nada, porque ya cuadra.

**Riesgo:** ajustar al conteo. Si la empresa solo cuenta una hora, el ajuste
queda **sin comprobar** y el reporte lo tiene que decir. Una sola condición no
valida nada: el modelo de visión dio 36/36 a mediodía y 28/40 a las 7:00.

**Costo:** unos 3–4 días de trabajo y ninguna hora de GPU extra; la detección
se hace una vez.

### 3.2 Entrenar el detector con su propio video (adaptación al sitio)

**Qué:** afinar YOLOv8s con cuadros de sus cámaras. Las etiquetas salen del
propio sistema y una persona solo corrige:

- Las detecciones de alta confianza y las que el rastreador confirma en muchos
  cuadros se toman como etiquetas.
- Donde el rastro tiene un hueco (vehículo visto en el cuadro 10 y en el 20,
  perdido en medio), se rellena interpolando. Eso enseña justo los casos
  difíciles: el vehículo lejano y el medio tapado.
- Se revisa en **CVAT**, gratis y en la máquina propia, sin subir el video del
  cliente a nadie ([CVAT, auto-anotación](https://docs.cvat.ai/docs/annotation/auto-annotation/_print/)).

**Por qué:** un estudio sobre una plataforma embebida, con cámara fija,
afinó el detector con etiquetas generadas por fondo y rastreo, sin persona.
Reporta que la estimación de tránsito mejoró "de forma importante", y que
sobre todo **se reconocieron mejor los vehículos del fondo**
([Politécnica de Gdańsk](https://pub.pg.edu.pl/en/download/152874-vehicle-detection-with-self-training-for-adaptative-video-processing-embedded-platform)).
Ojo: si solo se usan las de alta confianza, el modelo aprende lo que ya sabe.
Los casos difíciles salen del rastreo, no del umbral
([arXiv 2103.02093](https://arxiv.org/pdf/2103.02093),
[arXiv 2103.14198](https://arxiv.org/pdf/2103.14198)).

**Cuánto:** no hay cifra publicada para un caso como el nuestro; **hay que
medirla**. Lo que más puede ganar es el carril del fondo de Fraccionamiento
(16–20 px) y la noche. En 640×360 no hace milagros: si el vehículo mide 14 px,
la información no está en el archivo, igual que con SAHI.

**Variante para objetos chicos:** una cabeza P2 (una escala más fina en
YOLOv8) dio +36 % de mAP en VisDrone, que son vehículos vistos desde arriba
([SOD-YOLO, arXiv 2507.12727](https://arxiv.org/abs/2507.12727)). Se
entrena junto con lo anterior. Cuesta tiempo de proceso y está sin medir con
nuestro video.

**Costo:** 1 000–2 000 cuadros revisados por tipo de cámara, uno o dos días de
una persona. Entrenar en la GTX 1650 de la PC son horas, y en el Orin, con la
cola parada. Ya se midió que entrenar no es el cuello de botella: lo es
etiquetar.

**Cómo se mide:** con el mismo conteo a mano y con una hora y un sitio que
**no** se usaron para entrenar. El aforo por línea validado (frontal 1.00×) no
debe moverse: modelo por proyecto, en el perfil.

### 3.3 Declarar la precisión de cada cifra

Ya existe a medias: "línea", "juntos". Falta un **nivel por movimiento y por
hora** que salga en el Excel y en la pantalla:

| Nivel | Cuándo | Qué se puede afirmar |
|---|---|---|
| Validado | Pasó GEH < 5 contra el conteo a mano, en una hora distinta a la de ajuste | La cifra |
| Medido | Seguido de punta a punta, vehículo ≥ 25 px, hora medible, sin conteo a mano | La cifra, con la exactitud típica de esa cámara |
| Por línea | Sale de la línea de la calle, menos las vueltas (1_3 y 3_1 en Fraccionamiento) | La cifra, con más error |
| Juntos | La cámara no separa los movimientos (2_1 y 2_3) | Solo la suma |
| No observable | Brazo fuera de cuadro, puente, noche no medible | Nada |

Es lo que le da al dueño un nivel de precisión que pueda sostener ante su
cliente, sin depender de nosotros para explicarlo. Costo: 2–3 días.

### 3.4 Lo que se puede probar barato, sin esperar mucho

Todo esto se prueba sobre detecciones ya guardadas, en el CPU:

- **Otro rastreador para el direccional** (OC-SORT, BoT-SORT). La evidencia es
  mixta: OC-SORT gana en movimiento no lineal
  ([arXiv 2203.14360](https://arxiv.org/abs/2203.14360)), y en tránsito
  ByteTrack sale igual o mejor
  ([TrafficMOT, arXiv 2311.18839](https://arxiv.org/abs/2311.18839)).
  Esperar poco.
- **El arranque de cada archivo en el direccional.** Hoy no se usa ahí; en
  línea recupera 0.3–0.5 %. En el direccional, el vehículo a medio cruce al
  cambiar de archivo queda incompleto.
- **Lazo virtual donde el detector no llega** (carril del fondo, entre el poste
  y los árboles de Fraccionamiento). No identifica el vehículo, pero sí lo
  cuenta, como el barrido de `barrido_linea.py`. Solo si 3.1 y 3.2 no bastan.

### Lo que ya se descartó (no repetir sin un dato nuevo)

SAHI y franja ampliada; ByteTrack para las líneas; bajar `min_hits`; mover
líneas donde el detector no ve; un modelo de visión para las clases finas;
saltar cuadros; el color para unir rastros; YOLO26 sin ajustar.

---

## 4. Una plataforma que crezca

Hoy la plataforma da por hecho tres cosas, y cada una se rompe al crecer:
**un proyecto es una cámara**, **un equipo procesa todo** y **un solo modelo
detecta**. Las tres se pueden aflojar sin rehacer nada, y en este orden.

### Etapa 1 — Varias cámaras por intersección (la más útil)

**El problema:** en Blvd. Independencia el puente tapa dos accesos, y la
conclusión fue "hacen falta dos cámaras". En Fraccionamiento, 2_1 y 2_3 doblan
fuera de cuadro. Con dos cámaras en un mismo proyecto, cada una aporta los
movimientos que sí ve.

**Cómo, sin romper nada:**

- Tabla nueva **`vistas`** (`id`, `project_id`, `nombre`, `ancho`, `alto`,
  `desfase_s`). Las zonas, líneas y videos llevan `vista_id`. Cada proyecto
  que ya existe recibe una vista única y todo sigue igual.
- **El número del acceso es del croquis, no de la cámara.** "1 · Avenida,
  norte" en la vista A y en la vista B es el mismo brazo 1.
  `numero_de_acceso` ya lee ese número del nombre.
- **Fuente por movimiento**, que generaliza `movimiento_por_linea`: el perfil
  dice de qué vista y de qué forma sale cada movimiento (punta a punta, línea,
  juntos). Nunca se suman dos vistas del mismo movimiento: se elige la que
  validó mejor. Sumarlas cuenta dos veces.
- **Reloj por vista.** Dos cámaras del mismo cruce tienen relojes distintos.
  Hay que alinearlas: con `reloj_video.py` y, si hace falta, con un
  vehículo grande que aparezca en las dos.

No encontré ningún trabajo publicado sobre fusionar el origen-destino de
varias cámaras. Los métodos del AI City Challenge cuentan por cámara
([AI City 2021](https://openaccess.thecvf.com/content/CVPR2021W/AICity/papers/Naphade_The_5th_AI_City_Challenge_CVPRW_2021_paper.pdf)).
"Elegir la mejor vista por movimiento" es lo sencillo y comprobable, y es lo
que se recomienda.

**Costo:** 1–2 semanas, sobre todo en Calibrar (elegir la vista) y en el
reporte.

### Etapa 2 — Más de un equipo procesando

**Hoy:** un Orin Nano.

- El frontal va a 1.1–1.4× el tiempo real, con TensorRT y el lector en otro
  hilo.
- El direccional de 1280×720 tarda 10–13 min por cada 10 de video.
- Un estudio de HMD (2 h × 3 intersecciones) son ~6–8 h de proceso. Un día
  completo de una cámara, ~20 h.

**Para crecer sin cambiar de base de datos:**

- El Jetson actual queda como **central**: base, pantalla y almacén.
- Cada equipo nuevo es un **trabajador** que pide un video por la API, lo
  procesa y devuelve cruces y movimientos en JSON.
- Ningún trabajador escribe en SQLite directamente. Así no hace falta
  PostgreSQL todavía, y la regla de "un trabajo de GPU por equipo" se cumple
  sola.
- El trabajador corre el mismo contenedor. El perfil del proyecto (modelo,
  `input_size`, umbrales) viaja con el trabajo, así que cuenta igual que el
  central. Eso se comprueba con la misma prueba de siempre: un video ya contado
  tiene que dar los mismos cruces.

**Qué equipo:** otro Orin Nano Super (USD 249 de lista de NVIDIA) duplica la
capacidad y ya está probado. Una PC con tarjeta de video de escritorio rinde
más por equipo, pero no encontré una comparación publicada y confiable a 1280
con el proceso completo. En el foro de NVIDIA, un mismo modelo pasa de ~35
cuadros/s solo detectando a ~25 con lectura y preparación
([foro NVIDIA, YOLOX-S en Orin Nano](https://forums.developer.nvidia.com/t/expected-fps-for-yolox-s-tensorrt-engine-on-jetson-orin-nano-jetpack-6-2/329875)).
Es lo mismo que medimos aquí: leer el video pesa casi tanto como detectar.
Antes de comprar se mide con un video nuestro.

**Almacén:** el disco USB de 2 TB alcanza para ~100 días de una cámara al
bitrate de hoy. Con varias cámaras, una carpeta compartida (NAS) a la que lean
todos los trabajadores. Y siempre la regla de no borrar lo que la plataforma
no copió.

**Cuándo pasar a PostgreSQL:** con 3 o más trabajadores, o varios usuarios
escribiendo a la vez. Antes no vale la pena.

### Etapa 3 — Cámaras en vivo

`tools/probar_camara_en_vivo.py` ya mide si una cámara RTSP o HLS sirve y si
el equipo alcanza su ritmo. Con las cámaras de los puentes: 19 cuadros/s
entrando, 12–13 procesados en el Orin a 1280.

- **Con una o dos cámaras en vivo:** el procesador de hoy alcanza, bajando
  `input_size` a 960.
- **Con más:** DeepStream decodifica y detecta varias cámaras a la vez en el
  mismo Jetson
  ([guía de Ultralytics para DeepStream](https://docs.ultralytics.com/guides/deepstream-nvidia-jetson)).
  No hay cifra publicada de cuántas cámaras aguanta un Orin Nano: se mide con
  sus cámaras antes de prometer.

En vivo no se guarda el video; el conteo se guarda igual que hoy.

### Etapa 4 — Más visión, sin rehacer

Hoy el perfil por proyecto ya elige el modelo, los clasificadores de pesados y
de livianos y los umbrales. Para que entren modelos nuevos sin tocar el resto:

- **Un contrato único:** todo detector devuelve cajas en coordenadas del
  cuadro completo, con clase y confianza. Todo lo demás (rastreador, conteo,
  clasificadores, reporte) solo consume cajas. Hoy `VehicleDetector` ya
  cumple eso.
- **Registro de modelos:** cada modelo con su archivo, licencia, contra qué se
  validó y con qué resultado. Un proyecto nuevo solo puede elegir modelos con
  validación.
- Así entran, cuando hagan falta: peatones y bicicletas (COCO ya trae
  `person` y `bicycle`), un detector propio afinado (3.2) o RF-DETR.

### La licencia: un riesgo de negocio, no técnico

**YOLOv8 (Ultralytics) es AGPL-3.0.** Si la plataforma se ofrece por internet
a terceros, que es como la usan hoy por Tailscale, la AGPL obliga a dar el
código fuente a esos usuarios, o a comprar la licencia Enterprise de
Ultralytics ([licencia de Ultralytics](https://www.ultralytics.com/license),
[resumen de Roboflow](https://roboflow.com/ultralytics)).

- Entregar el sistema con su código al cliente probablemente cumple.
- Venderlo como servicio cerrado a varias empresas no.

**Esto lo tiene que ver alguien con conocimiento legal; no es asesoría
legal.**

**La salida técnica, si hace falta: RF-DETR**, Apache 2.0, libre para uso
comercial. Corre a ~25 cuadros/s en el Orin Nano y tiene soporte de
DeepStream
([Roboflow, RF-DETR en Jetson](https://blog.roboflow.com/how-to-deploy-rf-detr-to-an-nvidia-jetson/),
[documentación](https://rfdetr.roboflow.com)). Ya está instalado aparte en el
Jetson y **sin evaluar**. Antes de cambiar:

1. Pasar por la misma prueba que YOLO26: los 4 minutos revisados a ojo, el
   conteo a mano del frontal y Terracería, de día y de noche.
2. Si 3.2 se hace, entrenar sobre RF-DETR y no sobre YOLO deja el modelo
   propio fuera de la AGPL.

---

## 5. Qué haría, en orden

| # | Qué | Costo | Gana |
|---|---|---|---|
| 1 | Revisar en el grabador: flujo principal, bitrate, códec inteligente, cuadros fijos (sección 2, puntos 1–4) | 1 hora, sin salir a campo | Puede convertir una cámara como Gómez Morín en una como Terracería |
| 2 | Hoja de configuración de cámara para el instalador | medio día | Que no se repita |
| 3 | Calibrar contra una hora a mano desde la plataforma (3.1) | 3–4 días | Lo de Fraccionamiento, sin depender de una IA |
| 4 | Nivel de precisión por movimiento en el reporte (3.3) | 2–3 días | Un nivel de precisión que el dueño pueda sostener |
| 5 | Vistas: varias cámaras por intersección (etapa 1) | 1–2 semanas | Cruces que hoy no se pueden aforar |
| 6 | Afinar el detector con su video (3.2), mejor sobre RF-DETR | 1–2 semanas, más etiquetar | Vehículos lejanos y licencia propia |
| 7 | Trabajadores por la API (etapa 2) | ~1 semana, cuando la cola no alcance | Capacidad |

Los puntos 1 y 2 son los más baratos y pueden ser los que más ganen. Lo que
falta saber es si Gómez Morín se grabó del flujo secundario. Eso lo dice el
menú del grabador, no el software.
