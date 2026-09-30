# Guía para probar la beta

Qué hace el sistema, cómo levantar un aforo de prueba de principio a fin y qué
necesitamos de vuelta para medir qué tan bien cuenta. El manual completo está
en [MANUAL_DE_OPERACION.md](MANUAL_DE_OPERACION.md).

## Qué trae

| Parte | Qué entrega | Cómo salió contra el conteo manual |
|---|---|---|
| Conteo por sección | Vehículos por cuarto de hora y sentido al cruzar una línea | 1.00×, 53 de 54 cuartos con GEH < 5 (cámara frontal, 12–19 h) |
| Clasificación | A, B, C, T-S, moto y tractor sin caja; de día, la A en automóvil / camioneta / pickup | A 0.99–1.00×, autobús 1.02–1.08×; subtipos de A 95 % |
| Velocidad | Media, mediana y p85 por cuarto de hora y sentido, con un tramo de dos líneas | p85 en promedio a 1–1.5 km/h de las mangueras, de día y de noche |
| Aforo direccional | Matriz origen-destino y volumen por acceso | Movimiento principal 260 contra 252, total 97 % (un cuarto de hora) |

Todo sale en el Excel de la plataforma, con una hoja RESUMEN al frente. Corre
en el equipo, sin internet.

## Para empezar: el proyecto de ejemplo

En la plataforma está «Ejemplo beta — aforo frontal con velocidad (15 min)»:
un aforo terminado, con zonas, líneas, tramo de velocidad y el Excel completo.
Conviene abrirlo antes de levantar uno propio. Cuenta exactamente lo mismo que
el aforo validado (386 de 386, minuto por minuto).

## Entrar

**https://aforo.tail2bdded.ts.net** desde cualquier lugar, con el usuario y la
contraseña que te pasen (el navegador los pide una vez). En la oficina también
`http://10.197.1.156:8080`, con los mismos datos.

## Prueba 1: aforo por sección con velocidad

1. **Grabar bien:** cámara a lo largo de la vía, 1920×1080 o más, 4–8 Mb/s,
   reloj en hora, la hora de inicio en el nombre del archivo.
2. **Medir con cinta** al instalar o al recoger: una losa o la distancia
   entre dos marcas del pavimento visibles en la cámara, **a unos 8–12 m** de
   donde irá la línea de conteo. Foto de las dos marcas.
3. Nuevo proyecto, eligiendo **cómo se ven los vehículos** (grandes si la
   cámara va de frente o cercana) → **Subir** los videos.
4. **Revisar encuadre** sobre un video; leer los avisos si no sale bueno.
5. **Calibrar:** una zona por calzada; una línea de conteo por calzada donde
   el vehículo se vea grande, cruzando la calzada completa; «Medir velocidad
   en este carril» con la segunda línea sobre la marca medida y su distancia.
6. **Empezar conteo** (2 a 2.5 h de equipo por hora de video en alta
   resolución; si se va la luz, retoma solo).
7. **Reporte → Excel:** RESUMEN, clasificación y VELOCIDAD. Naranja = video
   incompleto.

## Prueba 2: aforo direccional

1. Un **cruce plano** con todos los brazos a la vista (con puente o brazos
   fuera del cuadro no sirve).
2. **Revisar encuadre.**
3. **Calibrar:** un **acceso** por brazo, con sus carriles de entrada y
   salida, hasta la orilla de la imagen.
4. **Empezar conteo** → Excel, hoja DIRECCIONAL.

## Lo que necesitamos de vuelta

- **Conteo manual** del mismo video, en el formato de siempre, de tres
  franjas: una normal, la hora pico y una de noche.
- **La distancia con cinta** del tramo de velocidad, con foto.
- **El reporte de mangueras**, si hubo contador de ejes ese día.
- **Lo que salga raro:** proyecto, video y hora; qué se hizo, qué se esperaba
  y una captura.

## Límites conocidos

- La noche se cuenta con la cámara frontal, pero falta conteo manual nocturno
  que la valide; las motos de frente de noche se pierden en parte.
- Automóvil / camioneta / pickup solo de día.
- Algún frente de autobús se cuenta como auto aparte (~0.15 %).
- El direccional está validado en un solo cuarto de hora.
- Con cámara de lado y baja, la calzada del fondo pierde hasta 10 %.

## Cuidar el equipo

Un video a la vez (lo demás espera turno); ventilación libre; si deja de
responder se reinicia solo en minutos. La base se respalda sola cada día.
Con cable de red es más estable que con WiFi.
