"""
Regresión del usuario y contraseña de la plataforma (`src/api/acceso.py`).

Lo que no se puede romper:

1. Sin contraseña, ni la pantalla ni la API responden (401 con la petición
   de usuario del navegador).
2. Con la buena, todo pasa; con una mala, no.
3. `/api/status` queda libre: es la revisión de salud del contenedor.

    python tools/probar_acceso.py
"""
import asyncio
import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.api.acceso as acceso  # noqa: E402

acceso.ESPERA_FALLO_S = 0  # la prueba no tiene por qué esperar
fallos = 0


def comprobar(ok, que):
    global fallos
    print(("ok   " if ok else "MAL  ") + que)
    fallos += 0 if ok else 1


async def app_de_prueba(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def pedir(ruta, usuario=None, contrasena=None, crudo=None):
    cabeceras = []
    if crudo is not None:
        cabeceras.append((b"authorization", crudo))
    elif usuario is not None:
        token = base64.b64encode(f"{usuario}:{contrasena}".encode()).decode()
        cabeceras.append((b"authorization", f"Basic {token}".encode()))
    enviado = []

    async def send(msg):
        enviado.append(msg)

    async def receive():
        return {"type": "http.request", "body": b""}

    mw = acceso.AccesoBasico(app_de_prueba, "tio", "contraseña larga ñ")
    asyncio.run(mw({"type": "http", "path": ruta, "headers": cabeceras,
                    "client": ("1.2.3.4", 1)}, receive, send))
    inicio = enviado[0]
    return inicio["status"], dict(inicio["headers"])


estado, cab = pedir("/")
comprobar(estado == 401 and b"www-authenticate" in cab,
          "sin contraseña la pantalla pide usuario (401 con WWW-Authenticate)")
comprobar(pedir("/api/projects")[0] == 401, "sin contraseña la API no responde")
comprobar(pedir("/api/projects", "tio", "contraseña larga ñ")[0] == 200,
          "con la contraseña buena pasa (acentos y eñes incluidos)")
comprobar(pedir("/api/projects", "tio", "otra")[0] == 401, "con una mala, no")
comprobar(pedir("/api/projects", "otro", "contraseña larga ñ")[0] == 401,
          "con otro usuario, no")
comprobar(pedir("/api/projects", crudo=b"Basic esto-no-es-base64!!")[0] == 401,
          "una cabecera mal formada no tumba nada: 401")
comprobar(pedir("/api/status")[0] == 200, "/api/status queda libre para la revisión de salud")

print(f"\n{fallos} fallos")
sys.exit(1 if fallos else 0)
