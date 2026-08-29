# Frontend

Interfaz de la plataforma de aforo: **React 19 + TypeScript + Vite**.

El resultado del build son archivos estáticos que FastAPI sirve tal cual
(`src/api/app.py` monta `web/dist`). En el Jetson **no corre Node**: el
bundle se construye antes, en la etapa `frontend` del `Dockerfile.jetson`,
y a la imagen final solo pasan los archivos ya compilados.

## Trabajar en el frontend

```bash
cd web
npm install
npm run dev
```

Vite queda en http://localhost:5173 y manda `/api/*` a FastAPI en el 8000,
que hay que tener corriendo aparte:

```bash
python -m uvicorn src.api.app:app --reload --port 8000
```

## Construir para servir desde FastAPI

```bash
cd web && npm run build
```

Deja el resultado en `web/dist`. A partir de ahí la plataforma completa
se ve en http://localhost:8000 sin necesidad de Vite.

## Cómo está organizado

| Carpeta | Qué hay |
|---|---|
| `src/styles/` | Tokens de diseño y hojas compartidas. `tokens.css` es la única fuente de color. |
| `src/lib/` | Cliente de la API, tipos, formato en español, consultas y hooks. |
| `src/components/` | Kit de interfaz (`ui.tsx`), navegación, guía, gráficas, iconos. |
| `src/pages/` | Una pantalla por archivo. |

Tres reglas que sostienen el resto:

1. **El color solo sale de tokens semánticos.** Un componente nunca
   escribe un valor de color; usa `--text-muted`, `--accent-ink`, etc.
   Eso es lo que hace que el tema oscuro funcione sin auditar cada uso.
   Los pares texto/fondo están medidos: todos pasan el mínimo de
   contraste de WCAG AA en ambos temas.

2. **Elementos nativos antes que reconstrucciones.** `<button>`,
   `<dialog>`, `<label>`, `<details>`. El teclado, el foco y el anuncio
   en lector de pantalla vienen incluidos; una versión con `<div>` habría
   que reimplementarlos.

3. **El estado del servidor lo maneja TanStack Query.** No hay
   `setInterval` propios ni comparaciones manuales para evitar repintar:
   el sondeo se declara con `refetchInterval` y React reconcilia el DOM.
   El sondeo se detiene solo cuando la pestaña está en segundo plano, así
   que la plataforma deja de pedirle datos al Jetson mientras nadie mira.

## La intersección viaja en la URL

`?project=<id>` es el estado compartido entre subir → calibrar → reporte.
Así el enlace se puede compartir y recargar, y las tres pantallas hablan
siempre del mismo aforo.
