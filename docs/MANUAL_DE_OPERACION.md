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
- **Velocidad** (media, mediana y percentil 85) si se calibró un tramo.
- Un **Excel** en el formato de la empresa y un reporte imprimible.

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
- **Automóvil contra camioneta/pickup**: no se separan (van juntas en A, que es
  como las pide la SCT).
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
