# Dictamen Técnico: Precisión, Generalización y Robustez del Aforo Direccional

> **Propuesta de otra IA, sin medir (nota del 16-oct-2026).** Las ganancias
> de la tabla (+15–25 %, +10–18 %, +2–4 %…) son estimaciones, no mediciones
> de este repositorio. Ninguna se toma como dato hasta compararla contra un
> conteo a mano, como manda `CLAUDE.md`. Del punto 1, el umbral por sentido
> ya existe (`umbral_linea_sentido`); el 4 está pendiente en
> `docs/RELEVO_2026-10-16.md`, y el 2 (arranque en el direccional) no se
> ha medido.

**Fecha:** 13 de octubre de 2026  
**Destinatario:** Equipo de Ingeniería y Operaciones / Claude en sesión paralela  
**Referencia:** Proyectos 2, 7, 26 (Gómez Morín), 27 (Fraccionamiento), 28 (Terracería)  
**Contexto base:** `CLAUDE.md`, `docs/RELEVO_2026-10-09.md`, `docs/REQUISITOS_CAMARA.md`, `docs/DETECCION.md`

---

## 1. Dónde se pierde precisión hoy y lista ordenada por impacto

| Prioridad | Intervención | Ganancia esperada | Costo dev / GPU | Riesgo |
|---|---|---|---|---|
| **1** | Calibración guiada de `umbral_linea_sentido` por carril | **+15 % a +25 %** en flujos lejanos | 8 h / 0 h GPU (con `det_*.json`) | Bajo |
| **2** | `arranque.py` adaptado a aforos direccionales | **+2 % a +4 %** movimientos completos | 5 h / <1 % overhead | Bajo |
| **3** | Unir pedazos con constricción cinemática ($t$, $v$, vector) | **+10 % a +18 %** en vías con obstáculos | 10 h / 0 h GPU | Medio |
| **4** | Declaración de confiabilidad por movimiento en Reportes/Excel | Certeza técnica y legal | 5 h / 0 h GPU | Nulo |
| **5** | Optimización de tiempo: unificar ByteTrack y ROI acotada | Reducción de 1.36× a **~0.8× tiempo real** | 8 h / 1 h GPU | Bajo |
| **6** | Blindaje en `tools/prueba_aceptacion.py` y reloj de video | 0 fallos silenciosos por FPS/Locks | 4 h / 0 h GPU | Nulo |

---

### Detalle de cada propuesta

#### 1. Calibración guiada/semiautomática de umbrales de confianza por sentido (`umbral_linea_sentido`)
* **Qué cambiar:**
  Crear una herramienta/rutina (`tools/calibrar_umbrales_sentido.py` y soporte en API/Calibrador) que, usando un lote con detecciones ya extraídas (`data/fr/det_08_*.json`), barra automáticamente una rejilla de umbrales (0.10, 0.15, 0.20, 0.25) para cada sentido de las líneas del cordón.
  - Si hay conteo a mano: busca el umbral que minimice el error cuadrático y GEH.
  - Si no hay conteo a mano: usa el apilado temporal sin detector ([`barrido_linea.py`](../tools/barrido_linea.py)) como referencia física para hallar el umbral máximo que captura los cruces reales sin disparar dobles conteos.
  - El resultado se inyecta en `projects.perfil_deteccion -> umbral_linea_sentido`.
* **Por qué (dato medido en repo):**
  En Fraccionamiento (Adenda 13-oct), bajar el umbral global a 0.15 infló la salida del carril cercano un +22 % (549 → 668) por dobles detecciones de vehículos grandes bien iluminados, mientras que el carril tapado al fondo requería 0.10 para subir de 96 a 128 (siendo 183 el valor real). Un umbral simétrico destruye un carril para arreglar el otro.
* **Cuánto se espera ganar:**
  Recuperar entre **+15 % y +25 %** de vehículos en flujos lejanos/ocultos sin sobredimensionar (+20 %) los flujos cercanos. En Fraccionamiento esto cierra la brecha entre el 69 % y >88–92 % global.
* **Cómo medirlo:**
  Sin GPU: emular en CPU sobre `data/fr/det_08_*.json` y comparar contra [`tools/comparar_od_real.py`](../tools/comparar_od_real.py) usando `data/fr/manual_fraccionamiento.xlsx`.
* **Costo y riesgo:**
  8 h dev; 0 h GPU. Riesgo bajo (si no se define en el perfil, se mantiene el comportamiento estándar).

---

#### 2. Llevar `arranque.py` al flujo direccional (empalme entre archivos de 10 min)
* **Qué cambiar:**
  Extender la inicialización de rastreo en [`src/engine/video_job_processor.py`](../src/engine/video_job_processor.py) y [`src/engine/origen_destino.py`](../src/engine/origen_destino.py). Cuando un video tenga un antecesor continuo inmediato (`HOLGURA_S <= 1.0 s` vía [`src/engine/arranque.py`](../src/engine/arranque.py)), decodificar los últimos 3 segundos (45 cuadros) del video anterior para alimentar el tracker ByteTrack sin registrar cruces.
* **Por qué (dato medido en repo):**
  En conteo por línea ya se demostró que el segundo 0 de cada archivo pierde el 20 % de sus cruces (0.3–0.5 % del total diario). En aforos direccionales el impacto es más severo: un vehículo tarda de 8 a 20 s en cruzar una intersección. Todo vehículo que esté dentro del cruce en el minuto 09:55 queda partido: el primer video registra un rastro sin destino (`X ·`) y el segundo video registra un rastro que nace en el centro (`· X`). En 90 videos de 10 min (15 horas), son **90 eventos de ruptura sistemática** que degradan la matriz.
* **Cuánto se espera ganar:**
  Entre **+2 % y +4 %** de movimientos directos rescatados sin requerir deducción de cordón, y eliminación de rastros huérfanos nacidos en el centro.
* **Cómo medirlo:**
  Contar la proporción de rastros nacidos en los primeros 3 segundos (`t0 < 3.0 s`) clasificados como `· X` (sin origen) antes y después en 6 videos consecutivos de Terracería o Fraccionamiento.
* **Costo y riesgo:**
  5 h dev; <1 % de sobrecosto de cómputo (solo decodifica 45 cuadros por video). Riesgo bajo siempre que se valide estrictamente la continuidad temporal.

---

#### 3. Unir pedazos con constricción cinemática ($t$, $v$, vector de avance) en [`od_trayectoria.py`](../src/engine/od_trayectoria.py)
* **Qué cambiar:**
  En [`src/engine/od_trayectoria.py`](../src/engine/od_trayectoria.py), la unión y asignación de pedazos hoy depende de la distancia de Hausdorff y plantillas previas de completos. Se debe condicionar la unión temporal de fragmentos (`dt = t_ini2 - t_fin1`) evaluando la velocidad requerida $v = \Delta \text{distancia} / \Delta t$. Si $v$ es físicamente coherente con el corredor (ej. 15–60 km/h) y el vector de avance no invierte el rumbo, el fragmento se une al movimiento sin exigir que existan decenas de recorridos completos de referencia.
* **Por qué (dato medido en repo):**
  - El filtro de color (`firmas_color.py`) falló y está apagado porque los cambios de luz y vehículos blancos lavados distorsionan el espacio Lab.
  - En Fraccionamiento la matriz por zonas solo vio 50 de 758 movimientos porque el camellón y los postes parten invariablemente el rastro transversal en 3 pedazos. El vehículo desaparece 1.5 a 2.5 segundos y reaparece en el mismo carril.
* **Cuánto se espera ganar:**
  Recuperar entre **+10 % y +18 %** de movimientos completos en intersecciones con obstrucciones centrales fijas.
* **Cómo medirlo:**
  Correr [`tools/od_por_trayectoria.py`](../tools/od_por_trayectoria.py) sobre rastros extraídos (`data/fr/tray_*.json`) y contrastar contra `data/fr/manual_fraccionamiento.xlsx`.
* **Costo y riesgo:**
  10 h dev; 0 h GPU (cálculo vectorial geométrico en CPU). Riesgo medio: requiere mantener los candados anti-vuelta en U para no inventar giros indebidos.

---

#### 4. Declaración formal de nivel de confiabilidad por movimiento
* **Qué cambiar:**
  En [`src/reports/aforo_excel.py`](../src/reports/aforo_excel.py) (`_hojas_formato_empresa`), [`src/reports/validacion_od.py`](../src/reports/validacion_od.py) y la vista de Reporte en web, asignar a cada movimiento de la matriz una clasificación explícita:
  1. `medido_completo`: Rastreado continuo de acceso a acceso.
  2. `medido_por_cordon`: Resuelto mediante ecuación de flujo en línea (`movimiento_por_linea`).
  3. `agrupado`: Movimientos indistinguibles combinados formalmente (`movimientos_juntos`, ej. `[2_1, 2_3]`).
  4. `no_observable`: Movimiento oculto o fuera de cuadro.
  Cuando no hay conteo manual de contraste, generar un indicador de auditabilidad: tamaño promedio en píxeles del flujo, índice de fragmentación (rastros partidos / vehículos entrantes) y estabilidad de FPS.
* **Por qué (dato medido en repo):**
  En Gómez Morín (640×360) el sistema entregó 1 380 movimientos totales con formato idéntico a un estudio validado, cuando el movimiento 3_2 aportaba apenas 11 contra 599 reales. Mezclar cifras inferidas por cordón con mediciones de trayectoria pura sin declararlo compromete la credibilidad de los estudios entregados.
* **Cuánto se espera ganar:**
  Elimina rechazos de auditoría por parte del cliente y da certeza jurídica a los entregables.
* **Cómo medirlo:**
  Generar los Excel de los proyectos 26, 27 y 28 y verificar que la hoja `METODO` y los encabezados identifiquen automáticamente la procedencia de cada cifra sin intervención manual.
* **Costo y riesgo:**
  5 h dev; 0 h GPU. Riesgo nulo.

---

#### 5. Optimización del tiempo de procesamiento en el pipeline direccional
* **Qué cambiar:**
  Actualmente un video de 10 min a 1280×720 tarda entre 10 y 13.6 min (1.0× a 1.36× tiempo real):
  1. **Acotar inferencia a ROI envolvente de accesos y cordones:** No inferir cielo ni áreas estáticas marginales fuera del polígono convexo envolvente de accesos.
  2. **Unificar rastreador en memoria:** Actualmente Fraccionamiento ejecuta ByteTrack para la matriz direccional y de forma paralela el rastreador propio (IoU + Kalman) para las líneas del cordón. El módulo de cruce de líneas debe consumir los tracks suavizados e interpolados que ya produce ByteTrack.
* **Por qué (dato medido en repo):**
  Documentado en `docs/RELEVO_2026-10-09.md` (Adenda 11-oct): *"El ritmo (1.36x tiempo real) es lento y no está perfilado: 1280x720 con ByteTrack a confianza 0.1 más el rastreador propio de las líneas"*.
* **Cuánto se espera ganar:**
  Reducir el tiempo de cómputo de 1.36× a **~0.75×–0.85× tiempo real** (~7 a 8 min por video de 10 min en Jetson Orin Nano).
* **Cómo medirlo:**
  Benchmark cronometrado de un video de Fraccionamiento (10 min) antes y después, asegurando coincidencia binaria de cruces e identificadores.
* **Costo y riesgo:**
  8 h dev; 1 h GPU profiling. Riesgo bajo.

---

#### 6. Robustez operativa y ampliación de `tools/prueba_aceptacion.py`
* **Qué cambiar:**
  1. Incorporar a `REGRESIONES` en [`tools/prueba_aceptacion.py`](../tools/prueba_aceptacion.py):
     - Detección de discrepancia de FPS en cabecera vs timestamp real (`reloj_video.py`).
     - Validación sintáctica de `perfil_deteccion.py` (`movimiento_por_linea`, `umbral_linea_sentido`, `movimientos_juntos`).
     - Verificación de que actualizar nombres de líneas/zonas no marque videos como desactualizados (`updated_at`).
  2. Fijar `busy_timeout = 60000` (60 s) en todas las conexiones SQLite de herramientas y scripts auxiliares.
* **Por qué (dato medido en repo):**
  El desajuste de 15 fps declarados vs 10 fps reales en modo nocturno afectó a 52 de 90 videos de Gómez Morín, comprimiendo la hora en 6 min 44 s y distorsionando la HMD por días.
* **Cuánto se espera ganar:**
  Prevención del 100 % de fallos silenciosos en la base de datos y en las marcas de tiempo.
* **Cómo medirlo:**
  Correr `python tools/prueba_aceptacion.py` verificando que repruebe ante un video sintético con desfase de FPS o sintaxis corrupta en perfil.
* **Costo y riesgo:**
  4 h dev; 0 h GPU. Riesgo nulo.

---

## 2. Generalización: De ajustes a mano a plataforma guiada

Para que un técnico de campo calibre un aforo direccional sin requerir un especialista en IA:

1. **Sugerencia automática de polígonos de acceso con el mapa de extremos:**
   - La plataforma ya cuenta con la herramienta de visualización de recorridos (`data/recorridos/{job}.json`).
   - Aplicar un agrupamiento espacial sencillo (DBSCAN o K-Means sobre puntos verdes de inicio y rojos de fin) para sugerir polígonos convexos preliminares en los accesos.
   - El operador únicamente ajusta bordes finos y asigna el identificador numérico de la empresa ("1", "2", "3").
2. **Asistente de diagnóstico y detección de necesidad de cordón:**
   - Al procesar el minuto de prueba, la plataforma evalúa la tasa de completitud:  
     $$\text{Tasa de completitud} = \frac{\text{Rastros que tocan 2 accesos}}{\text{Total de rastros con más de 15 cuadros}}$$
   - Si la tasa es $< 40\,\%$, la interfaz alerta: *"Se detectan obstrucciones centrales severas o vehículos <25 px. Se recomienda activar cordón de líneas en los accesos de paso directo"*.

---

## 3. Delimitación estricta: Software vs. Cámara / Instalación

| Problema observado | ¿Se arregla con Software? | ¿Se arregla con Cámara / Instalación? | Justificación empírica |
|---|---|---|---|
| **Vehículos lejanos (14–20 px al fondo)** | **NO** | **SÍ** | Medido: SAHI y franja ampliada bajaron detecciones de 24 a 17. No hay información en el archivo. Requiere resolución 1080p o lente con zoom. |
| **Noche / Faros barridos (20:00 a 05:00)** | **NO** | **SÍ** | Brillo nocturno medido: 177 vs 84 de día. La autoexposición barre los objetos en estelas de luz. Se corrige forzando obturador rápido (1/100s mínimo) en la cámara. |
| **Paso tapado por camellón / arbusto (Fraccionamiento)** | **Parcialmente** | **SÍ** | Mitigado por software vía cordón (`movimiento_por_linea`); solución definitiva: elevar la cámara (>5 m) para librar la jardinera. |
| **Paso a desnivel / Puente ciego (Blvd. Independencia)** | **NO** | **SÍ (Multicámara)** | Una cámara en esquina no ve a través del concreto. Requiere dos cámaras o toma cenital. |
| **Discrepancia de FPS día/noche (10 vs 15 fps)** | **SÍ** | Recomendable en cámara | Corregido en software con `reloj_video.py`, pero la cámara debe configurarse en CFR (tasa constante). |
| **Confusión COCO Camioneta vs Camión** | **SÍ** | No necesario | Resuelto con la regla de altura calibrada por línea (1.55–1.61× del automóvil mediano). |

---

## 4. Recomendaciones técnicas de instalación para la empresa

A partir de los aforos de Juárez (Proyectos 2, 7, 26, 27 y 28):

1. **Regla física de los 40 píxeles:**
   El vehículo más lejano de cualquier movimiento debe medir como mínimo **40 px de alto**.
   - En intersecciones medianas o grandes (>25 m de claro), **queda prohibido grabar a 640×360** (caso Gómez Morín: 46 % de captación).
   - Estándar obligatorio: **1920×1080 (1080p) con bitrate de 4 a 8 Mb/s**.
2. **Altura y ángulo de montaje:**
   - Montaje a **mínimo 5.0 a 6.0 metros de altura** con ángulo descendente de 25° a 35°.
   - Esto minimiza la oclusión mutua en filas de semáforo (correlación volumen-pérdida $r = -0.83$ medida en CLAUDE.md) y libra obstáculos como jardineras y barandales.
3. **Ajuste de obturación nocturna:**
   - Desactivar la autoexposición lenta. Fijar la velocidad de obturador en **1/100 s o 1/125 s** en modo nocturno. El detector tolera ruido de sensor, pero no tolera estelas de barrido de movimiento.
4. **Protocolo obligatorio del "Minuto de Prueba":**
   - Una vez montada la cámara, el instalador debe subir un clip de 1 minuto a la plataforma y ejecutar `tools/calidad_video.py` y `tools/diagnosticar_encuadre.py`.
   - Si el diagnóstico arroja vehículos $<30\text{ px}$ en accesos críticos o esquinas ciegas, la cámara debe reubicarse en ese momento antes de abandonar el sitio.
