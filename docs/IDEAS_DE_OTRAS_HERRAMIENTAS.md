# Lo que hacen otras herramientas de aforo, y qué nos sirve

*16-oct-2026. Estudio de la competencia para que la plataforma sea un producto
que el dueño pueda operar y hacer crecer.*

**Cómo se hizo, y el límite.** Se leyó el código de una herramienta de código
abierto y lo que las comerciales publican: páginas, manuales y preguntas
frecuentes. **No se copió código.** OpenTrafficCam es GPL-3.0, y copiar su
código obligaría a publicar el nuestro con la misma licencia. Se toman ideas y
se escriben desde cero. No se descompiló software comercial: Miovision y
GoodVision corren en sus servidores, y de ellos solo se mira lo público.

---

## 1. Lo que ya hacemos igual o mejor

| | OpenTrafficCam | GoodVision | Miovision | Nosotros |
|---|---|---|---|---|
| Accesos dibujados a mano | sí ("sections") | sí | técnico de ellos | sí, con el mapa de recorridos |
| Movimientos (origen-destino) | par de secciones, gana el de mayor duración | sí | sí | por trayectoria, con plantillas aprendidas del propio aforo |
| Rastros partidos | se cuentan como incompletos | no lo dice | revisión manual | se unen, verificado a ojo |
| Exactitud declarada | no declara | "hasta 99.7 %" (suya) | "95 % o más, garantizado" (suya) | **medida contra conteo a mano**: 1.00× frontal, 103 % Terracería, 93 % Fraccionamiento |
| Sin internet ni nube | sí | no | no | sí, en el Jetson |
| Formato de la empresa (Hr/Mov, A/B/C) | no | Excel genérico | Excel genérico | sí |

**Para venderlo:** Miovision cobra por garantizar el 95 %
([Miovision Scout](https://miovision.com/scout)) y su cifra es de "datos en
archivo", sin auditoría de terceros. GoodVision dice hasta 99.7 %, también
cifra suya ([GoodVision](https://goodvisionlive.com/goodvision-video-insights/)).
Nosotros tenemos el **conteo a mano de la propia empresa** al lado de cada
cifra. Eso vale más que una cifra de folleto, siempre que se declare por
cámara: Gómez Morín dio 46 %.

## 2. Ideas que sí nos faltan, por orden de valor

### 2.1 Revisar solo los vehículos dudosos

**Quién lo hace:**
- **OpenTrafficCam** calcula para cada vehículo qué tan segura es su clase:
  junta las confianzas de todos sus cuadros y mira cuántos coinciden con la
  clase ganadora. Marca para revisión a mano los que quedan bajo un umbral por
  clase, tomado del censo vial alemán (SVZ): auto 0.90; camión, autobús y moto
  0.80; tractocamión 0.85. Su panel dice "a revisar: N de M vehículos".
- **Miovision**: el video pasa por su sistema y después "se revisa a mano en
  busca de anomalías"
  ([Miovision, preguntas frecuentes](https://miovision.com/lp/data-collection/)).

**En nosotros:** el voto de clase pesado por confianza ya existe
(`tools/probar_rastreador.py`), y los recortes del cruce también
(`hoja_cruces.py`, `recortes_sin_posicion.py`). Falta juntarlo en la
plataforma:

1. Una cola **"Vehículos a revisar"** con el recorte de cada uno y su clase.
   Entran los de voto dividido, los cruces dobles muy juntos y los pesados con
   probabilidad baja.
2. Quien opera confirma o corrige con un clic. La corrección va a
   `clase_revisada`, que ya gana sobre todo en `get_interval_counts`.
3. El reporte dice "N revisados a mano".

**Por qué primero:** la clasificación es entregable y hoy solo se revisa con
herramientas de línea de comandos. Revisar 50 dudosos sale más barato que
contar una hora a mano, y las correcciones son etiquetas para entrenar el
clasificador.

### 2.2 Un panel de calidad por video

**Quién lo hace:** OpenTrafficCam da, por video:
- cuántos rastros hubo dentro del área;
- cuántos quedaron asignados a un movimiento;
- cuántos cruzaron una sección pero no quedaron asignados;
- cuántos ni siquiera cruzaron;
- cuántos pisaron dos secciones a la vez, que es señal de accesos mal
  dibujados.

**En nosotros:** los datos ya están. Son los completos, los incompletos y los
sin decidir del direccional, y los avisos por video. Falta un número que se lea
solo: "**82 % de los vehículos con movimiento completo**" en verde, ámbar o
rojo. Que salga en la cola de Subir y en el Reporte, con un aviso cuando un
acceso nace o muere a media imagen. Es lo que habría avisado de Blvd.
Independencia antes de gastar 4 h.

### 2.3 Comprobar entre accesos vecinos (conservación de flujo)

**Quién lo hace:** Miovision compara los conteos de tramos comunes: lo que sale
de un cruce hacia el siguiente tiene que coincidir con ±5 vehículos o al 95 %.

**En nosotros:**
- Ya existe dentro de un cruce: el volumen por acceso, entradas contra salidas.
- Falta entre cruces: cuando la empresa afore dos intersecciones seguidas de la
  misma avenida, la salida de una debe cuadrar con la entrada de la otra. Es una
  validación **sin conteo a mano**, justo lo que falta cuando no lo hay.

Encaja con las "vistas" del informe de crecimiento
(`docs/INVESTIGACION_PRECISION_Y_CRECIMIENTO.md`).

### 2.4 Exportar la lista de eventos

**Quién lo hace:** OpenTrafficCam exporta, además de los conteos, la lista
cruda: un renglón por vehículo y sección, con hora exacta, clase y sentido.
Miovision vende lo "auditable": el auditor puede ver el mismo video que vio el
sistema.

**En nosotros:** `crossings` y `movimientos` ya guardan todo.
1. Un CSV de eventos con la hora interpolada, la clase y un enlace al recorte.
2. En el Reporte, "ver el cuadro" de cualquier vehículo contado.

Con eso la empresa puede defender cada cifra ante su cliente.

### 2.5 Coordenadas del mundo, no de la imagen

**Quién lo hace:** OpenTrafficCam pasa los rastros a vista de pájaro con una
foto satelital georreferenciada (UTM), así que cada punto está en metros sobre
el mapa.

**En nosotros:** es la base para tres cosas que ya están en la lista:
- la velocidad sin calibrar contra el tubo (las losas de concreto ya dieron la
  escala);
- juntar varias cámaras del mismo cruce en un solo plano;
- dibujar los accesos sobre el croquis de la empresa y no sobre la imagen.

Es trabajo grande. Va después de 2.1–2.4 y junto con las vistas.

### 2.6 Esquema de clases configurable

**Quién lo hace:** GoodVision deja elegir el esquema por proyecto (FHWA, Reino
Unido) y hace modelos a pedido.

**En nosotros:** la traducción a A/B/C/T-S está fija en `clasificacion.py`. Si
la empresa entra a otro cliente u otro estado con otra taxonomía, conviene que
el esquema sea del perfil del proyecto. Es barato si se hace antes de que haya
muchos proyectos.

## 3. Lo que NO conviene copiar

- **Elegir el movimiento por "mayor duración entre dos secciones"**, como
  OpenTrafficCam. Ya lo superamos: decidir por trayectoria subió Altozano de
  0.74× a 0.99×.
- **Prometer una cifra única de exactitud.** Miovision la garantiza para todos
  sus estudios. Nuestra experiencia dice que depende de la cámara (46 % a
  103 %), y declararla por cámara es lo honesto. Lo comercial es ofrecer "95 % o
  más **con una cámara que pase Revisar encuadre**".

## 4. Dónde entra REA (la ingeniería inversa)

No hay en esta PC software de la competencia, del contador de ejes ni del
grabador. Cuando lo haya, en este orden:

1. **El programa del contador de ejes** (RoadRunner3, de Diamond Traffic).
   Equipo de la empresa: leer sus archivos crudos para conectarlo con lo
   nuestro es el uso más defendible.
2. **La interfaz web del grabador o la cámara**, con la empresa conectada a su
   red: sacar el flujo principal, el bitrate y las URL de RTSP.
3. Programas comerciales que la empresa tenga **con licencia**. Antes, leer si
   la licencia prohíbe la ingeniería inversa; casi todas lo hacen.

Las herramientas de REA solo aparecen en una sesión nueva de Claude, abierta
después de registrarla.

## Fuentes

- [OpenTrafficCam OTAnalytics (GitHub, GPL-3.0)](https://github.com/OpenTrafficCam/OTAnalytics):
  `plugin_number_of_tracks_to_be_validated`,
  `application/use_cases/track_statistics.py`,
  `application/analysis/traffic_counting.py`, `domain/georeference.py`
- [OpenTrafficCam, documentación](https://opentrafficcam.org/OTAnalytics/)
- [Miovision Scout](https://miovision.com/scout) ·
  [Miovision, recolección de datos y preguntas frecuentes](https://miovision.com/lp/data-collection/)
- [GoodVision Video Insights](https://goodvisionlive.com/goodvision-video-insights/) ·
  [Parámetros de tránsito de GoodVision](https://help.goodvisionlive.com/en/articles/3323611-traffic-parameters-provided-by-video-insights)
