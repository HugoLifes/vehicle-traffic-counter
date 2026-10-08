# Manual de operación del aforo vehicular por video

Para quien levanta y entrega aforos con el sistema. No hace falta saber
programar: todo el flujo se hace desde la plataforma en el navegador. Lo que
necesita la terminal (respaldos, actualizar, la prueba de aceptación) está al
final, en "Mantenimiento".

---

## 1. Qué hace y qué entrega

El sistema cuenta los vehículos de un video grabado en campo cuando cruzan una
línea marcada sobre la calzada, y los clasifica. Entrega, por cuarto de hora y
por sentido:

- **Volumen** de vehículos, con la hora de máxima demanda.
- **Clasificación SCT**: A (automóviles, camionetas y pickups), B (autobús),
  C (camión unitario), T-S (tractocamión), más motocicleta y tractor sin caja
  como clases propias.
- **Velocidad** (media, mediana y percentil 85) si se calibró un tramo, o como
  estudio por muestreo (ver Mantenimiento).
- Un **Excel** en el formato de la empresa, con una hoja **RESUMEN** al frente
  (total, hora de máxima demanda, factor de hora pico y composición), y un
  reporte imprimible.

**Exactitud medida contra conteo manual** (cámara frontal, 19-sep-2026,
12:00–19:00): 1.00× en los dos sentidos, 53 de 54 cuartos de hora con
GEH < 5. Ver "Límites conocidos" para lo que todavía no está validado.

## 2. Antes de grabar

La exactitud la decide la cámara más que el programa. Lo que funciona,
medido:

| | Recomendado | Por qué |
|---|---|---|
| Posición | En el camellón o sobre la vía, **mirando a lo largo** de ella | De frente el vehículo mide 115–150 px en la línea; de lado, 14–41 px y se pierde |
| Resolución | 1920×1080 o más | El detector necesita unos 40 px de alto por vehículo |
| Calidad de video | **4–8 Mb/s** | A 0.8 Mb/s el compresor borra el detalle |
| Noche | Exposición baja u obturador rápido | Con obturador lento el vehículo sale barrido |
| Reloj | Fecha y hora correctas en la grabadora | La hora de cada cruce sale del nombre del archivo |
| Una medida con cinta | Al instalar o al recoger: el largo de una losa, o la distancia entre dos marcas que crucen la calzada, a la vista de la cámara | Es la escala de la velocidad; sin ella hay que calibrar contra las mangueras |

**Graba un minuto de prueba y revísalo** (paso 4) antes de dejar la cámara
24 horas.

Los archivos deben llevar la hora de inicio en el nombre (la grabadora ya lo
hace: `HH/MM.mp4` o `HH-MM-SS.mp4`).

## 3. Entrar a la plataforma

Con el Jetson encendido y en la misma red: `http://IP-DEL-JETSON:8080` en el
navegador. Desde fuera de la oficina, por túnel:

```bash
ssh -L 8080:localhost:8080 apia@IP-DEL-JETSON
```

y luego `http://localhost:8080`. La plataforma trae una guía de primeros pasos
que avanza sola conforme se completa cada paso.

### Compartir la plataforma por internet

Para que alguien fuera de la red la use con una dirección normal y fija
(`https://aforo.<tu-red>.ts.net`), sin túnel de Cloudflare y sin tocar el
router. La plataforma no se puede alojar en un servicio como Vercel: el
conteo necesita la GPU, los videos y la base del Jetson; lo que se publica es
una dirección que llega a él.

1. **Primero, usuario y contraseña.** Sin esto, quien tenga la dirección
   puede ver los aforos, subir videos y borrar proyectos:

   ```bash
   bash tools/poner_acceso.sh
   ```

2. **Instalar Tailscale** (una vez) e iniciar sesión con la cuenta que vaya a
   administrar el equipo; el comando da un enlace para entrar:

   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up --hostname=aforo
   ```

3. **Publicar la plataforma:**

   ```bash
   sudo tailscale funnel --bg 8080
   ```

   La primera vez da un enlace para activar HTTPS y Funnel en la cuenta; se
   abre, se activa y se repite el comando. `tailscale funnel status` enseña la
   dirección. Queda puesta aunque el equipo se reinicie.

Quien la abre no instala nada: el navegador pide el usuario y la contraseña
una vez. Para dejar de compartirla: `sudo tailscale funnel --bg 8080 off`.
Para cambiar la contraseña, otra vez `bash tools/poner_acceso.sh`.

## 4. Levantar un aforo

1. **Proyectos → nuevo proyecto.** Un proyecto es una intersección o un tramo.
   Elige **cómo se ven los vehículos en la cámara**:
   - *Grandes* (de frente o cercana, la recomendada): separa tractocamión,
     tractor sin caja y automóvil / camioneta / pickup, y no cuenta dos veces
     el vehículo que la IA marca con dos clases.
   - *Chicos* (lejana o de lado): liviano / pesado, sin esas dos cosas, que
     con vehículos chicos que se enciman borran vehículos distintos.
   Si te equivocas, no inventa clases: las finas solo salen donde el
   automóvil mide 100 px o más. Se cambia al editar el proyecto (afecta a lo
   que se cuente después). La casilla del video anotado sirve para revisar
   lo contado, pero el proceso tarda ~40 % más.
   Si la cámara no se movió desde otro aforo, **copia la calibración** de ese
   proyecto: trae las zonas, las líneas atadas a su calzada y el tramo.
2. **Subir.** Arrastra los videos. Revisa que el *inicio real* de cada uno sea
   el correcto antes de subir. Para muchos videos o internet lento, mejor por
   WinSCP (abajo).
3. **Calibrar.** La imagen de la cámara ocupa la pantalla; a la izquierda
   queda la lista de calzadas. Una **calzada** es una calle con un sentido de
   circulación: su zona y su línea de conteo, del mismo color.
   - **+ Calzada** (tecla N): primero rodea la calle con un polígono (clic en
     cada esquina; se cierra con Enter, doble clic o tocando el primer
     punto), luego cruza la calle con su **línea de conteo** (dos clics) y
     ponle nombre: es el que sale en el reporte y el Excel. La zona separa
     los sentidos y descarta lo que pasa fuera de la vía.
   - Pon la línea **donde el vehículo se ve grande** y haz que **cruce el
     ancho completo de su calzada**; alargarla un poco hacia la vecina no
     duplica nada, dejarla corta sí pierde vehículos. La lista lo revisa
     mientras dibujas: avisa si la línea deja fuera parte de la calle, si va
     a lo largo del tránsito en vez de cruzarlo, o si está pegada a la orilla
     de la imagen.
   - **Corregir**: arrastra un vértice, el extremo de una línea o la figura
     entera. Del punto medio de un borde sale un vértice nuevo; clic derecho
     quita uno. La rueda del ratón acerca la imagen (y `0` la ajusta de
     nuevo) para atinarle a calzadas angostas. Los cambios quedan pendientes
     hasta **Guardar cambios**; Ctrl+Z deshace. Al guardar, los videos ya
     contados quedan con la calibración anterior hasta volver a contarlos.
   - Si una línea aparece en **Líneas sin calzada**, átala a la suya con el
     selector: sin calzada, cuenta los vehículos de todas las calles.
   - **Tramo de velocidad** (opcional, «+ medir velocidad» en la tarjeta de
     la calzada): una segunda línea sobre una marca
     del pavimento que cruce la calzada, **a unos 8–12 m** de la línea de
     conteo, con la distancia medida con cinta. Medido en Cd. Juárez: a
     ~8.5 m el percentil 85 quedó a 0.6–1.5 km/h de las mangueras y de noche
     se midió al 79 % de los vehículos; a ~17 m, solo al 36 % hacia la
     cámara, porque los faros cortan el recorrido antes de la segunda línea.
   - La capa **Rastro** muestra por dónde pasan los vehículos (de lo ya
     contado) para comprobar que la línea los corta de través; **Detecciones**
     enseña lo que ve la IA en el cuadro en pausa.
4. **Empezar conteo.** Los videos entran a la cola y se procesan uno por uno.
   Con la cámara frontal va algo más rápido que la grabación: una hora de
   video en ~45–55 minutos.
5. **Reporte.** Volumen por intervalo, composición, velocidad y hora pico.
   Desde ahí se descarga el Excel.

### Subir muchos videos por WinSCP

Por la página, desde fuera de la casa, los videos pasan por el relevo público
y suben lento. Por WinSCP van a la velocidad del internet de quien sube,
retoman solos si se corta y se arrastran carpetas enteras.

1. Instala **Tailscale** (tailscale.com/download) y entra con la invitación.
2. Instala **WinSCP** (winscp.net). Nueva conexión: protocolo **SFTP**,
   servidor **100.107.72.1**, puerto **22**, usuario **juarez** y la
   contraseña que te dieron.
3. Arrastra las carpetas a la ventana de la derecha. Si van por hora y
   minuto (`2026-10-05/14/00.mp4`, `14/01.mp4`…), la plataforma toma la fecha
   y la hora solas.
4. En la plataforma: **Subir → Videos en la carpeta de entrada**. Revisa la
   hora de cada uno, elige y pulsa **Importar**. Se copian al disco de los
   videos y quedan listos para calibrar y contar.

Esa cuenta solo puede subir y bajar archivos de su carpeta: no ve nada más
del equipo ni puede ejecutar nada. Lo que subes ahí no se borra al importar;
bórralo tú desde WinSCP cuando ya esté contado.

## 5. Revisar antes de entregar

El sistema avisa cuando un dato no es confiable; hay que leer los avisos:

- **Cuartos en naranja** en el Excel: el video no cubrió el cuarto completo.
- **Horas no medibles**: de noche con una cámara que no la resuelve, el
  sistema no da clasificación ni velocidad en vez de dar cifras malas.
- **Nivel de clasificación** por calzada: `medido`, `estimado` (solo vale la
  proporción) o `no resoluble`.

Si hay un conteo manual o de mangueras del mismo día, compáralo (ver
Mantenimiento). Contra mangueras el sistema sale 10–20 % arriba en hora
cargada: es el aparato, que registra como uno a dos vehículos que pisan la
manguera a la vez.

## 6. Límites conocidos

Dilo en la entrega; son medidos, no supuestos:

- **Noche con la cámara frontal**: se cuenta, pero todavía **no hay conteo
  manual nocturno** para validarla. Las **motos que vienen hacia la cámara** de
  noche se pierden en buena parte (el faro de frente las vuelve una mancha).
- **Automóvil, camioneta y pickup**: se separan de día (hoja LIVIANOS). De
  noche los faros no dejan ver la forma y van en SIN SUBTIPO.
- **Origen-destino**: solo en cruces planos con todos los brazos a la vista.
  Con un puente o un brazo fuera de cuadro no sirve, con ningún ajuste.
- **Cámara de lado y baja**: la calzada del fondo queda chica y se pierde
  hasta 10 %.

## 7. Mantenimiento

Todo se corre en el Jetson, desde la carpeta del proyecto:

```bash
cd ~/vehicle-traffic-counter
```

**Prueba de aceptación** (después de cada actualización, o si algo se ve
raro). Dice PASA o FALLA para cada parte:

```bash
docker compose -f docker-compose.jetson.yml exec -T aforo-vehicular python3 tools/prueba_aceptacion.py
```

Con un conteo de campo para medir la exactitud:

```bash
docker compose -f docker-compose.jetson.yml exec -T aforo-vehicular python3 tools/prueba_aceptacion.py --proyecto 7 --referencias data/nuevos/aforo_frontal_manual
```

**Ajustes finos por cámara (perfil de detección, avanzado).** Lo normal es el
tipo de cámara de la pantalla. Además, cada proyecto puede llevar ajustes
medidos para su cámara. El de la cámara frontal de Cd. Juárez (proyecto 7)
es:

- motos desde confianza 0.10 (recupera motos de noche);
- clasificador de pesados propio (autobús, camión, tractocamión, tractor sin
  caja) y de livianos (automóvil, camioneta, pickup), sin internet.

Los clasificadores ya los pone el tipo "grandes"; el umbral de motos no,
porque solo se validó con esa cámara de noche. Para darle el perfil completo
a un proyecto nuevo con esa misma cámara (cambia `7` por su número):

```bash
curl -X PUT http://localhost:8080/api/projects/7 -H "Content-Type: application/json" -d '{"perfil_deteccion": {"umbral_clase": {"motorcycle": 0.10}, "clasificador_pesados": "models/pesados_v1.pt", "clasificador_livianos": "models/livianos_v3.pt"}}'
```

Con el clasificador de livianos, el Excel trae la hoja **LIVIANOS (15MIN)**:
la clase A abierta en automóvil, camioneta y pickup. Sus columnas suman la
A; lo que el modelo no distingue con seguridad va en SIN SUBTIPO.

Sin perfil, un proyecto cuenta con la configuración general, que es la
validada para la cámara de lado. El perfil solo afecta los videos que se
cuenten después; lo ya contado no cambia. Los modelos `models/pesados_v1.pt`
y `models/livianos_v3.pt` viven en el equipo; hay copia en `data/respaldos/`.

**Estudio de velocidad sin recontar.** La velocidad cruce por cruce solo sale
si el tramo se puso antes de contar. Si no, se hace un estudio por muestreo
sobre unos minutos de cada hora (así se hacen los estudios de velocidad de
punto). Se extraen los recorridos de nueve minutos por hora (unas 2 h por
cada 12 h de video; no correrlo mientras la cola cuenta):

```bash
docker compose -f docker-compose.jetson.yml exec -T aforo-vehicular sh tools/muestra_velocidad.sh data/nuevos/20260919 data/nuevos/vel/tray
```

y con la distancia del tramo (medida con cinta, o calibrada contra las
mangueras con `tools/calibrar_velocidad.py`):

```bash
docker compose -f docker-compose.jetson.yml exec -T aforo-vehicular python3 tools/estudio_velocidad.py --proyecto 7 --tray data/nuevos/vel/tray --calibracion data/nuevos/vel/calibracion.json --salida data/nuevos/vel/estudio_velocidad.xlsx
```

Con una medida de cinta se agrega `--distancia "Calzada alejandose=17.2"`.
Las horas donde no se alcanza a medir al 70 % de los vehículos (de noche,
hacia la cámara) salen en gris, sin cifra.

**Respaldos.** La plataforma respalda la base sola una vez al día en
`data/respaldos/` y conserva los últimos 14. Para restaurar uno:

```bash
docker compose -f docker-compose.jetson.yml stop
sudo cp data/respaldos/traffic_AAAA-MM-DD_HHMM.db data/traffic.db
sudo rm -f data/traffic.db-wal data/traffic.db-shm
docker compose -f docker-compose.jetson.yml start
```

La hora del nombre del respaldo es UTC (6 horas adelante de Cd. Juárez en verano): el de las 08:39 se hizo a las 02:39 de Juárez. Una copia hecha a mano con otro nombre (`traffic_antes_de_algo.db`) se conserva y no cuenta para la rotación de los 14.

Copia de vez en cuando `data/respaldos/` a otro equipo: un respaldo en el
mismo disco no protege de que se dañe el disco.

**Actualizar el programa:**

```bash
git pull && docker compose -f docker-compose.jetson.yml up -d
```

Si el cambio es de la interfaz (carpeta `web/`), hay que reconstruir, y
después limpiar lo que deja la construcción (llena el disco en silencio):

```bash
git pull && docker compose -f docker-compose.jetson.yml up -d --build
docker builder prune -f && docker image prune -a -f --filter "until=24h"
```

**Ver qué está haciendo, reiniciar:**

```bash
docker compose -f docker-compose.jetson.yml logs -f
docker compose -f docker-compose.jetson.yml restart
```

**Si algo falla:**

| Síntoma | Qué hacer |
|---|---|
| La página no abre | `docker ps`: el contenedor debe decir *healthy*. Si no, `restart`. |
| Un video queda en "error" | Leer el error en Subir. Casi siempre es un archivo cortado (le falta el índice): se descarta. El resto de la cola sigue sola. |
| La cola no avanza | `logs -f`. Si el equipo se reinició, la cola se retoma sola al arrancar. |
| Un conteo sale muy bajo | Revisar la calibración: línea corta o zona mal dibujada. El sistema avisa en el registro si la zona descarta más del 40 % de las detecciones. |
| Disco lleno | `docker system df` y la limpieza de arriba. |
| El equipo deja de responder (ni la página ni `ssh`) | Se calentó o se quedó sin memoria. Con el watchdog activo (abajo) se reinicia solo en un minuto y la cola sigue; sin él, desconectarlo y volver a conectarlo. Revisar que el ventilador no tenga polvo y que el equipo no esté encerrado. |

**Ajustes del equipo, una sola vez al instalar.** El Jetson se congeló una vez
tras horas de carga continua: miles de alertas de superficie caliente con el
ventilador en su perfil silencioso, que es el de fábrica. Estos dos ajustes
lo dejan enfriando a fondo y, si aun así se congela, reiniciándose solo:

```bash
sudo sed -i 's/FAN_DEFAULT_PROFILE quiet/FAN_DEFAULT_PROFILE cool/' /etc/nvfancontrol.conf && sudo systemctl stop nvfancontrol && sudo rm -f /var/lib/nvfancontrol/status && sudo systemctl start nvfancontrol
sudo sed -i 's/^#\?RuntimeWatchdogSec=.*/RuntimeWatchdogSec=60/' /etc/systemd/system.conf && sudo systemctl daemon-reexec
```

**La red.** Con cable Ethernet no hace falta nada. Por WiFi con repetidores
(mesh), el 27-sep el equipo cambió de repetidor, el router no le volvió a dar
dirección y quedó inaccesible aunque seguía funcionando. Si tiene que ir por
WiFi, fijarle la IP (y reservarla en el router) y poner una revisión que
reconecte si se pierde la salida a la red:

```bash
sudo nmcli con mod "NOMBRE-DEL-WIFI" ipv4.method manual ipv4.addresses IP/24 ipv4.gateway ROUTER ipv4.dns ROUTER
printf '#!/bin/sh\nping -c2 -W3 ROUTER >/dev/null || nmcli con up "NOMBRE-DEL-WIFI"\n' | sudo tee /usr/local/bin/revisar_red
sudo chmod +x /usr/local/bin/revisar_red
```

y un temporizador de systemd (`revisar-red.timer`) que la corra cada 2
minutos. En el Jetson de Cd. Juárez ya está: `systemctl status revisar-red.timer`.

Si en el equipo corren otros contenedores con GPU, pónganles techo de memoria
(`docker update --memory 2g --memory-swap 2g NOMBRE`): en el Jetson la
memoria de la GPU es la misma RAM, y la que pide CUDA no cuenta dentro del
límite de 6 GB del contenedor del aforo.
