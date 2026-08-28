# Referencia metodológica: Publicación Técnica 914 del IMT

**Documento**: [`referencias/PT914-IMT-monitoreo-trafico-vision-computadora.pdf`](referencias/PT914-IMT-monitoreo-trafico-vision-computadora.pdf)
Hernández Sánchez, B.; Montiel Moctezuma, C. J.; Martner Peyrelongue, C. D.;
Cervantes Camacho, I. (2026). *Metodología para el monitoreo del tráfico urbano
mediante visión por computadora*. Publicación Técnica No. 914, Instituto Mexicano
del Transporte, Querétaro. ISSN 0188-7297.

Es la referencia metodológica del proyecto: describe un sistema prácticamente
igual al nuestro (visión por computadora en el borde, para tráfico urbano en
México) y publicado por el instituto de referencia del sector en el país. Sirve
para dos cosas: **validar** las decisiones que ya tomamos y **corregir** las que
se apartan de la práctica documentada.

## Lo que confirma de nuestra implementación

| Nuestra decisión | Qué dice la PT-914 |
|---|---|
| **YOLOv8n** con pesos COCO, sin ajuste fino | Usa exactamente lo mismo (§2.2.2) |
| Filtrar a **auto, motocicleta, autobús, camión** | Mismas cuatro clases (§2.2.2) |
| **Líneas virtuales** para contar por cruce | Mismo mecanismo: `line_crossing` (§2.2.3) |
| **Producto cruzado** para determinar el lado/dirección | Idéntica fórmula y misma interpretación de signo (§2.2.5) |
| **Tracking por IoU** con `track_id` persistente | Mismo enfoque *tracking-by-detection* (§2.2.3) |
| Cámara **IP por RTSP** | Es la fuente que usan (§2.2.2) |
| **No guardar el video**, solo eventos estructurados | "sin depender del almacenamiento del video" (§3.3) |
| Carriles **calibrados por el usuario antes de contar** | ROI, umbrales y divisores se definen y **versionan** antes de medir (§2.2.1) |

## Parámetros concretos que conviene adoptar

La PT-914 documenta valores de inferencia distintos a nuestros defaults:

| Parámetro | PT-914 | Nuestro valor actual |
|---|---|---|
| Umbral de confianza | **τ = 0.25** | 0.4 |
| IoU para NMS | **θ = 0.70** | 0.5 |
| Tamaño de entrada | 640 px (letterbox) | 640 px ✓ |

Su umbral de confianza es bastante más bajo que el nuestro. Vale la pena
probarlo contra el footage real antes de cambiarlo: con confianza más baja se
detectan más vehículos, pero también más falsos positivos.

## Exactitud esperable (referencia para comparar la nuestra)

Validaron contra conteo manual en 36 clips de 1 minuto:

- **MAE: 1.25 veh/min**
- **MAPE: 3.89 %**
- **Sesgo: −0.75 veh/min** (el automático cuenta *de menos*)

El sesgo negativo se explica por pérdidas de continuidad del seguimiento en
cruces con oclusión o *headways* cortos. Es la cifra contra la cual deberíamos
medir nuestro propio conteo cuando hagamos la validación manual pendiente.

También reportan que solo el **85.9 %** de las mediciones de velocidad se
aceptan; el resto se descarta por pérdida de identidad del track o cruces en
orden inválido.

## Mejoras que sugiere y todavía no implementamos

1. **Continuidad mínima alrededor de la línea** (§3.4) — la recomendación
   explícita del documento para reducir conteos dobles y cruces perdidos: exigir
   que la trayectoria sea continua en una ventana de cuadros *antes y después*
   de la línea, no solo en el instante del cruce.
2. **Estimación de velocidad con dos líneas** (§2.2.4):
   `v = d / Δt` (m/s), o `v = 3.6 · d / Δt` (km/h), donde `d` es la distancia
   real en metros entre dos líneas y `Δt` el tiempo entre ambos cruces del mismo
   `track_id`. Se acepta la medición solo si: cruza en el orden esperado,
   `Δt > 0` con trayectoria continua, ocurre dentro de la ROI, y la velocidad
   cae en un rango plausible `[v_min, v_max]` del sitio.
3. **Detección de cambio de carril** (§2.2.5–2.2.6) — mismo producto cruzado,
   pero exigiendo que el cambio de signo **persista N cuadros consecutivos** y
   con una **zona muerta** alrededor del divisor, para no disparar el evento
   cuando el vehículo circula pegado a la línea.
4. **ROI (polígono de análisis)** — nosotros solo tenemos líneas; ellos delimitan
   además un área válida, lo que evita activaciones fuera de escena.
5. **Versionado de la geometría** — registrar qué configuración de carriles
   produjo cada medición, para que los aforos sigan siendo comparables entre
   sesiones aunque después se recalibre.
6. **Trazabilidad del pipeline** — guardar versión del modelo y parámetros de
   inferencia junto con los resultados.

## Limitaciones que también aplican a nosotros

Las causas de error que documentan son las mismas que veremos en campo:
oclusiones en tráfico denso, solapamiento entre vehículos de carriles contiguos,
y variaciones de iluminación y sombras. Todas degradan la continuidad de las
trayectorias, y eso impacta directo en los conteos.
