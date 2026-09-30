"""
Usuario y contraseña para la plataforma.

Hasta la beta la plataforma solo se usaba dentro de la red de la oficina o por
un túnel SSH, y no tenía ningún candado: quien llegara al puerto 8080 podía
ver los aforos, subir videos y borrar proyectos enteros. Para compartirla por
internet (ver docs/MANUAL_DE_OPERACION.md, «Compartir la plataforma») eso no
puede quedar abierto.

Se usa la autenticación básica del navegador: pide usuario y contraseña una
vez, y el navegador los manda solo en cada petición a la misma dirección, así
que ninguna pantalla, descarga ni video tuvo que cambiar. Viaja cifrada por
el HTTPS de la dirección pública.

Se enciende SOLO si están AFORO_USUARIO y AFORO_CONTRASENA en el entorno (el
.env del Jetson, que nunca se sube al repositorio); sin ellos todo queda como
antes. `tools/poner_acceso.sh` los escribe sin que la contraseña pase por la
pantalla ni por el historial.

Es un middleware ASGI puro y no BaseHTTPMiddleware: este envuelve el cuerpo de
la petición y de la respuesta, y aquí pasan subidas de video de cientos de
megas y el video anotado en streaming.
"""
import asyncio
import base64
import binascii
import logging
import secrets

# Libres del candado: la revisión de salud del contenedor y de la prueba de
# aceptación, que corren dentro del equipo y no llevan contraseña.
RUTAS_LIBRES = ("/api/status",)
# Freno a quien prueba contraseñas: cada intento fallido tarda un segundo.
ESPERA_FALLO_S = 1.0


class AccesoBasico:
    def __init__(self, app, usuario: str, contrasena: str):
        self.app = app
        self._usuario = usuario.encode("utf-8")
        self._contrasena = contrasena.encode("utf-8")

    def valida(self, cabecera: bytes) -> bool:
        if not cabecera.lower().startswith(b"basic "):
            return False
        try:
            usuario, _, contrasena = base64.b64decode(cabecera[6:].strip(),
                                                      validate=True).partition(b":")
        except (binascii.Error, ValueError):
            return False
        # compare_digest en los dos: comparar con == deja adivinar por tiempos.
        ok_u = secrets.compare_digest(usuario, self._usuario)
        ok_c = secrets.compare_digest(contrasena, self._contrasena)
        return ok_u and ok_c

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") in RUTAS_LIBRES:
            await self.app(scope, receive, send)
            return
        cabeceras = dict(scope.get("headers") or [])
        if self.valida(cabeceras.get(b"authorization", b"")):
            await self.app(scope, receive, send)
            return
        if cabeceras.get(b"authorization"):
            await asyncio.sleep(ESPERA_FALLO_S)
            logging.warning("Acceso rechazado desde %s", (scope.get("client") or ("?",))[0])
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"www-authenticate", b'Basic realm="Aforo vehicular", charset="UTF-8"'),
                (b"content-type", b"text/plain; charset=utf-8"),
            ],
        })
        await send({"type": "http.response.body",
                    "body": "Hace falta usuario y contraseña.".encode("utf-8")})
