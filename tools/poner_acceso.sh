#!/bin/bash
# Pone (o cambia) el usuario y la contraseña de la plataforma en el .env del
# Jetson y la reinicia para que los tome (ver src/api/acceso.py).
#
#   bash tools/poner_acceso.sh
#
# La contraseña se escribe sin verse en pantalla y no queda en el historial de
# la terminal. El .env nunca se sube al repositorio (tiene también la clave de
# NVIDIA). Para quitar el candado, borrar las dos líneas AFORO_ del .env y
# volver a levantar con `docker compose -f docker-compose.jetson.yml up -d
# --force-recreate`.
set -euo pipefail
cd "$(dirname "$0")/.."

read -rp "Usuario: " usuario
read -rsp "Contraseña (no se ve al escribir): " c1; echo
read -rsp "Repítela: " c2; echo
if [ "$c1" != "$c2" ]; then echo "No coinciden; no se cambió nada."; exit 1; fi
if [ ${#c1} -lt 10 ]; then echo "Usa al menos 10 caracteres; no se cambió nada."; exit 1; fi
# Entre comillas simples el .env toma el valor tal cual; lo único que no cabe
# es otra comilla simple.
case "$usuario$c1" in *"'"*) echo "Sin comillas simples, por favor; no se cambió nada."; exit 1;; esac
if [ -z "$usuario" ]; then echo "Falta el usuario; no se cambió nada."; exit 1; fi

touch .env
grep -v -E '^(AFORO_USUARIO|AFORO_CONTRASENA)=' .env > .env.nuevo || true
printf "AFORO_USUARIO='%s'\nAFORO_CONTRASENA='%s'\n" "$usuario" "$c1" >> .env.nuevo
chmod 600 .env.nuevo
mv .env.nuevo .env
unset c1 c2

# restart NO vuelve a leer el .env; hay que recrear el contenedor. Si estaba
# contando, la cola retoma sola el video que iba.
docker compose -f docker-compose.jetson.yml up -d --force-recreate aforo-vehicular
echo "Listo: la plataforma ahora pide usuario y contraseña."
