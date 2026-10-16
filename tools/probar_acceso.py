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



async def en_paralelo(n_malos):
    """n intentos malos A LA VEZ y uno bueno: los malos esperan en fila (no
    todos juntos), los que pasan de FILA_MAXIMA reciben 429 al momento y el
    bueno no espera a nadie."""
    import time
    acceso.ESPERA_FALLO_S = 0.05
    mw = acceso.AccesoBasico(app_de_prueba, "tio", "contraseña larga ñ")

    async def uno(usuario, contrasena):
        token = base64.b64encode(f"{usuario}:{contrasena}".encode()).decode()
        enviado = []

        async def send(msg):
            enviado.append(msg)

        async def receive():
            return {"type": "http.request", "body": b""}
        t0 = time.perf_counter()
        await mw({"type": "http", "path": "/api/projects", "client": ("127.0.0.1", 1),
                  "headers": [(b"authorization", f"Basic {token}".encode())]}, receive, send)
        return enviado[0]["status"], time.perf_counter() - t0

    malos = [uno("tio", f"mala{i}") for i in range(n_malos)]
    t0 = time.perf_counter()
    *r_malos, r_bueno = await asyncio.gather(*malos, uno("tio", "contraseña larga ñ"))
    acceso.ESPERA_FALLO_S = 0
    return r_malos, r_bueno, time.perf_counter() - t0


r_malos, r_bueno, total = asyncio.run(en_paralelo(acceso.FILA_MAXIMA + 5))
estados = [e for e, _ in r_malos]
comprobar(estados.count(401) == acceso.FILA_MAXIMA and estados.count(429) == 5,
          f"en paralelo: {estados.count(401)} esperan en fila (401) y 5 reciben 429")
comprobar(total >= acceso.FILA_MAXIMA * 0.05 * 0.9,
          f"los malos van en fila, no todos juntos ({total:.2f} s para {acceso.FILA_MAXIMA})")
comprobar(r_bueno[0] == 200 and r_bueno[1] < 0.05,
          f"la contraseña buena no espera la fila ({r_bueno[1] * 1000:.0f} ms)")

print(f"\n{fallos} fallos")
sys.exit(1 if fallos else 0)
