# Plan de mejora de apia_vision

*24-oct-2026. Qué hacer con la plataforma en los próximos meses: lo que
mejora el conteo y lo que abre servicios de ingeniería vial que la empresa
hoy no puede vender.*

## De dónde parte

apia_vision ya cuenta y clasifica en video, por línea y por movimiento:

| Tipo de aforo | Resultado contra el conteo a mano |
|---|---|
| Por línea, cámara frontal de Juárez | 1.00× |
| Direccional, Calle terracería | 103 %, 6 de 6 movimientos con GEH < 5 |
| Direccional, Fraccionamiento | 93 %, 5 de 5 |

Además entrega:
- el Excel en el formato de la empresa;
- la hora de máxima demanda y el factor de hora pico;
- la velocidad por tramo;
- la cola de revisión de dudosos y la lista de vehículos con foto;
- todo en un Jetson, sin nube.

Tres reglas que este plan no rompe:
1. **Medir antes de afirmar.** Cada punto dice contra qué se valida, con una
   hora para ajustar y OTRA para comprobar.
2. **No mover lo validado.** Una mejora entra apagada, por proyecto, y con una
   regresión que demuestre que lo ya entregado no cambia.
3. **El dato manda, no la herramienta.** Si una función no se puede validar
   con los datos que hay, se anota como pendiente y no se construye a ciegas.

La guía de lo que se puede vender: **la empresa ya vende aforos.** Cada
estudio de ingeniería vial de abajo es un aforo más un cálculo. Si la
plataforma hace el cálculo con el mismo video, la empresa vende más por el
mismo trabajo de campo.

---

## Parte A — La plataforma

### A1. Que aprenda de lo que se revisa (prioridad 1)

Hoy cada corrección de la pestaña Revisar arregla el conteo y se pierde como
conocimiento.

- **Cada decisión es un ejemplo.** Guardar el recorte, la clase corregida,
  quién y cuándo en `data/aprendizaje/`, con un contador en pantalla:
  "312 ejemplos de pesados, 48 de dobles".
- **Calibración por sitio desde el conteo a mano.** Al subir el Excel de
  campo, la plataforma prueba umbrales por línea y sentido sobre detecciones
  guardadas, ajusta con una hora y comprueba con otra. Solo aplica el ajuste
  si pasa la comprobación. Es lo que en Fraccionamiento se hizo a mano.
- **Reentrenar con candado.** Un botón "Entrenar con lo revisado" para los
  clasificadores de pesados y livianos, que tardan minutos en el Orin. El
  modelo nuevo solo se usa si pasa la prueba de aceptación y no empeora ningún
  aforo validado (frontal, Terracería, Fraccionamiento).
- **Memoria por intersección.** Si regresan a un sitio, se cargan sus accesos,
  umbrales, croquis y advertencias.

*Se valida:* cada modelo nuevo contra recortes etiquetados de horas que no vio
y en dos condiciones de luz.

### A2. Cerrar los dobles conteos de Fraccionamiento (prioridad 1)

La revisión destapó que en el carril tapado un pedazo de vehículo y el
vehículo entero se cuentan aparte: 4.8 % de los cruces de esa línea. Pasos:
1. revisar una muestra en la pestaña Revisar;
2. medir la fracción real;
3. probar sin GPU, con las detecciones guardadas, una regla que no cuente un
   rastro nuevo que nace encimado sobre otro que ya cruzó;
4. comparar otra vez contra el conteo a mano.

Ojo: hoy esos dobles **tapan** pérdidas, así que corregirlos baja la cifra
antes de subirla.

### A3. Nivel de precisión en cada cifra (prioridad 1)

Cada movimiento y cada hora del Excel lleva su nivel:

| Nivel | Qué quiere decir |
|---|---|
| validado | comparado contra conteo a mano y pasó GEH < 5 |
| medido | seguido de punta a punta, vehículo de ≥ 25 px, hora medible |
| por línea | sale de la línea de su calle, menos las vueltas |
| juntos | la cámara no separa esos movimientos; vale la suma |
| no observable | no se puede dar |

Es lo que deja al dueño sostener una cifra ante su cliente sin llamarnos.

### A4. Que opere más solo (prioridad 2)

- **Asistente por pasos para un aforo nuevo:**
  1. subir los videos;
  2. Revisar encuadre (si sale rojo, lo dice antes de contar);
  3. dibujar los accesos sobre el mapa de recorridos;
  4. contar;
  5. ver la calidad del seguimiento;
  6. revisar los dudosos;
  7. sacar el Excel.

  Cada paso dice qué falta.
- **Avisos al terminar.** Correo o WhatsApp de la empresa: "terminó el aforo
  X, calidad verde, 13 dudosos". Hoy alguien tiene que entrar a mirar.
- **Servidor MCP sobre la API**, para que un agente (ADK de Google, Claude u
  otro) pueda operar la plataforma con permisos: preparar, lanzar, comparar,
  redactar.
  - El modelo de lenguaje **no** corre en el Jetson, que comparte la memoria
    con la GPU que cuenta.
  - Nada destructivo sin confirmación.

### A5. Varias cámaras y más equipos (prioridad 2, cuando crezcan)

Detallado en `INVESTIGACION_PRECISION_Y_CRECIMIENTO.md`:
- **"Vistas":** varias cámaras por intersección, con el número de acceso del
  croquis y cada movimiento tomado de la vista que mejor lo ve.
- **Trabajadores** que piden videos por la API.
- **Almacén compartido** para los videos.
- **PostgreSQL**, solo con tres o más equipos.

### A6. Modelo propio y licencia (prioridad 2)

- Afinar el detector con su propio video. El objetivo es el vehículo chico y
  el medio tapado.
- Evaluar RF-DETR (Apache 2.0) contra YOLOv8 en los mismos minutos revisados.
- Si la plataforma se va a vender como servicio a terceros, que un abogado
  revise la AGPL de Ultralytics.

### A7. Robustez (continuo)

- **Corte de luz** (pasó el 21-oct): el Jetson volvió solo y la prueba salió
  ACEPTADO. Faltan dos cosas:
  - un no-break pequeño para el Jetson y el disco USB, para que un corte no
    sorprenda a la base a media escritura;
  - que el reloj se sincronice antes de arrancar la plataforma, porque el
    equipo no tiene pila de reloj.
- **Respaldo fuera del equipo:** hoy los respaldos viven en el SSD y en el
  disco USB, los dos pegados al Jetson. Una copia semanal a otra máquina o a
  la nube de la empresa.
- **Prueba de aceptación programada** cada noche, con aviso si algo falla.

---

## Parte B — Ingeniería vial con el mismo video

Lo que la empresa podría vender con los datos que la plataforma ya saca, o
casi. Ordenado por cercanía a lo que ya existe.

### B1. Nivel de servicio de una intersección (prioridad 1)

Con los volúmenes por movimiento y la hora de máxima demanda, aplicar el
método del Highway Capacity Manual:
- capacidad por acceso;
- grado de saturación (v/c);
- demora media;
- nivel de servicio A–F.

Es el entregable que más piden los **estudios de impacto vial**.
- *Falta:* la geometría (carriles por acceso, el ciclo del semáforo) como
  datos del proyecto. Se captura una vez por sitio.
- *Se valida:* contra un cálculo hecho a mano o con software comercial en un
  sitio conocido.

### B2. Colas y demoras medidas, no estimadas (prioridad 1)

El video ve la fila. Con una zona "fila" por acceso se mide:
- cuántos vehículos esperan;
- hasta dónde llega la fila;
- cuánto tarda cada vehículo desde que se detiene hasta que cruza.

Es el dato que calibra el nivel de servicio de B1 en vez de solo calcularlo.
- *Base:* los recorridos ya guardan tiempo y posición; un vehículo detenido se
  reconoce porque no se mueve.
- *Se valida:* contando a ojo la fila en cuadros sueltos (`inspeccionar.py`).

### B3. Tiempos de semáforo (prioridad 2)

Con el flujo de saturación medido en video y los volúmenes por movimiento se
propone un ciclo y su reparto: método de Webster, o el del HCM.
- *Flujo de saturación:* separación entre vehículos que salen en fila al
  ponerse el verde. Se mide sobre los recorridos.
- *Falta:* saber cuándo está en verde, que se infiere de cuándo arranca la
  fila o se captura a mano.
- *Se valida:* el flujo de saturación contra valores típicos (1 700–1 900
  autos por hora de verde y carril) y en dos horas distintas.

### B4. Seguridad vial sin esperar accidentes (prioridad 2)

Los **conflictos** se miden en video: tiempo a la colisión (TTC) y tiempo
posterior a la invasión (PET) entre trayectorias. Es la técnica actual para
evaluar un cruce sin esperar a que haya choques.

Sirve para:
- justificar un semáforo, una vuelta protegida o un reductor;
- comparar antes y después de una obra.

- *Base:* los recorridos por vehículo ya están; hacen falta coordenadas en
  metros (A5, vista de pájaro) para que TTC y PET sean de verdad.
- *Se valida:* revisando a ojo los conflictos que marque, uno por uno.

### B5. Peatones y ciclistas (prioridad 2)

El detector ya ve `person` y `bicycle`. Un aforo peatonal por cruce y por
cuarto de hora lo piden los estudios de impacto y el diseño de pasos
peatonales.
- *Se valida:* contra un conteo a mano de una hora. Las publicaciones dicen
  que el conteo a mano de peatones subcuenta 8–25 %, así que la referencia
  también se revisa a ojo.

### B6. Velocidad como estudio propio (prioridad 2)

Ya se mide por tramo. Falta empaquetarlo como el estudio que se entrega:
- percentil 85 por hora y sentido;
- distribución por clase;
- comparación con el límite;
- recomendación de límite por el criterio del percentil 85.

*Falta:* la distancia medida en el pavimento en cada sitio: una losa o dos
marcas con cinta al instalar.

### B7. Tránsito diario promedio anual y pronóstico (prioridad 3)

Con aforos de 24 h y factores de ajuste por día y mes, el aforo de un día se
convierte en tránsito diario promedio anual. Con una tasa de crecimiento,
sale el pronóstico a 5, 10 y 20 años. Es la base de cualquier proyecto de
vialidad.
- *Falta:* factores de la región. Los publica la SCT en sus datos viales o
  salen de los propios aforos de la empresa repetidos en el tiempo.

### B8. Diseño de pavimentos (prioridad 3)

La composición por clase (A, B, C, T-S, T-S-R) es justo lo que pide el
cálculo de ejes equivalentes para diseñar o revisar un pavimento. La
plataforma ya separa autobús, camión, tractocamión y tractor con la cámara
frontal.
- *Falta:* el número de ejes por clase, que se puede tomar del tubo cuando
  esté bien instalado, y los factores de daño.
- *Cuidado:* solo donde las clases finas están medidas (automóvil ≥ 100 px).

### B9. Estacionamiento (prioridad 3)

Ocupación y rotación de un estacionamiento o una calle, cuadro por cuadro:
vehículo quieto en un cajón. Lo piden los desarrollos comerciales.
- *Se valida:* contando a ojo en horas sueltas.

### B10. Antes y después (prioridad 3)

Comparar dos aforos del mismo sitio, antes y después de una obra o un cambio
de semáforo: volumen, velocidad, colas y conflictos, con su margen de error.
Es lo que convierte a la empresa en la que mide si una obra funcionó.

---

## Orden propuesto

Los costos de la tabla son de programación a mano. Con IA, programar cada punto toma de horas a unos días. Lo que de verdad marca el paso es conseguir los datos de campo y comprobar cada mejora contra un conteo a mano, así que el orden importa más que las fechas. La versión para compartir está en el documento "Plan de mejora apia_vision", que trae las fases y qué necesita cada una.

| # | Qué | Costo aproximado | Por qué en este orden |
|---|---|---|---|
| 1 | A2 dobles de Fraccionamiento | 1–2 días | corrige un entregable ya enviado |
| 2 | A1 aprender de lo revisado (ejemplos + calibración por sitio) | 1 semana | cada aforo nuevo deja la plataforma mejor |
| 3 | A3 nivel de precisión por cifra | 2–3 días | el dueño defiende sus cifras solo |
| 4 | B1 + B2 nivel de servicio con colas medidas | 1–2 semanas | el estudio que más se vende sobre lo que ya hay |
| 5 | A4 asistente por pasos y avisos | 1 semana | opera sin nosotros |
| 6 | B6 estudio de velocidad empaquetado | 3–4 días | ya está medido, falta presentarlo |
| 7 | B5 peatones y ciclistas | 1 semana | lo piden los estudios de impacto |
| 8 | B3 tiempos de semáforo | 1–2 semanas | sale casi gratis después de B2 |
| 9 | A7 respaldo fuera del equipo y no-break | 1 día + compra | protege todo lo anterior |
| 10 | B4 seguridad vial (conflictos) | 2–3 semanas | necesita coordenadas en metros |
| 11 | A5, A6, B7–B10 | según crezcan | dependen de más cámaras, datos o clientes |

## Lo que hace falta pedirle a la empresa

- **Un conteo a mano de una hora por cada sitio nuevo**, de preferencia en dos
  horarios. Con eso todo lo de A1 y A3 se vuelve automático.
- **La geometría de cada intersección:** carriles por acceso, el ciclo del
  semáforo si lo hay, y una distancia medida con cinta. Es lo que falta para
  B1, B3 y B6.
- **Qué estudios les piden sus clientes y el municipio.** Así se decide si B1,
  B4 o B5 va primero.
- **En el grabador de las cámaras:** flujo principal, bitrate de 4–8 Mb/s y
  cuadros fijos. Es gratis y vale más que cualquier punto de esta lista.
