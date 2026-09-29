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

## 4. Levantar un aforo

1. **Proyectos → nuevo proyecto.** Un proyecto es una intersección o un tramo.
2. **Subir.** Arrastra los videos. Revisa que el *inicio real* de cada uno sea
   el correcto antes de subir.
3. **Revisar encuadre** (en Subir, sobre un video). Califica en un minuto si
   el video sirve: tamaño del vehículo, exposición, nitidez. Si sale "no
   recomendable", lee los avisos: casi siempre es la cámara, y contar no lo
   arregla.
4. **Calibrar.**
   - **Zonas de calzada**: rodea cada calzada con un polígono. Sirven para
     separar los sentidos y descartar lo que pasa fuera de la vía.
   - **Líneas de conteo**: una por calzada, atada a su zona. Ponla **donde el
     vehículo se ve grande** y haz que **cruce el ancho completo de su
     calzada**; alargarla un poco hacia la vecina no duplica nada, dejarla
     corta sí pierde vehículos.
   - **Tramo de velocidad** (opcional): una segunda línea sobre una marca
     del pavimento que cruce la calzada, con la distancia medida con cinta.
   - "Ver por dónde pasan los vehículos" muestra los rastros para comprobar
     que la línea los corta de través.
5. **Empezar conteo.** Los videos entran a la cola y se procesan uno por uno.
   Con la cámara frontal tarda del orden de 1.6 horas por hora de video.
6. **Reporte.** Volumen por intervalo, composición, velocidad y hora pico.
   Desde ahí se descarga el Excel.

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

**Ajustes por cámara (perfil de detección).** Cada proyecto puede llevar los
ajustes medidos para su cámara. El de la cámara frontal de Cd. Juárez
(proyecto 7) es:

- motos desde confianza 0.10 (recupera motos de noche);
- clasificador de pesados propio (autobús, camión, tractocamión, tractor sin
  caja) y de livianos (automóvil, camioneta, pickup), sin internet.

Para darle el mismo perfil a un proyecto nuevo con esa cámara (cambia `7`
por el número del proyecto):

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
