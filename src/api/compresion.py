"""
Compresión de las respuestas de datos, no de los videos ni de los cuadros.

Por internet la plataforma pasa por el relevo de Tailscale (~4.5 Mb/s
medidos) y las listas en JSON se comprimen unas diez veces. El video y las
imágenes ya vienen comprimidos, y comprimir un video que se pide por rangos
rompería el Content-Length de cada pedazo: esos pasan tal cual.
"""
from starlette.middleware.gzip import GZipMiddleware

# Rutas que devuelven video o imagen.
_MEDIOS_FINAL = ("/video", "/original", "/live-frame", "/live-stream")
_MEDIOS_EXACTOS = ("/api/frames/frame",)


class GzipSoloDatos:
    def __init__(self, app, minimum_size: int = 1024):
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=minimum_size)

    async def __call__(self, scope, receive, send):
        ruta = scope.get("path", "") if scope["type"] == "http" else ""
        if (ruta.startswith("/api/") and not ruta.endswith(_MEDIOS_FINAL)
                and ruta not in _MEDIOS_EXACTOS):
            await self.gzip(scope, receive, send)
        else:
            await self.app(scope, receive, send)
