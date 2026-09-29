#!/bin/sh
# Recorridos de una muestra de minutos por hora, para tools/estudio_velocidad.py.
#
#   sh tools/muestra_velocidad.sh CARPETA SALIDA [BANDA_Y0 BANDA_Y1] [MINUTOS...]
#
# CARPETA tiene los videos de un minuto como HH/MM.mp4 (la grabadora del aforo
# frontal los deja asi). Por omision toma nueve minutos por hora, que en Cd.
# Juarez dieron 50 o mas vehiculos medidos por hora y sentido; un estudio de
# velocidad de punto suele pedir al menos 50.
#
# Uno a la vez: dos trabajos de GPU juntos en el Orin dan
# NvMapMemAllocInternalTagged error 12 y cuadros sin deteccion. No correrlo
# mientras la cola cuenta. Retoma donde se quedo: salta lo ya extraido.
set -u
carpeta="$1"; salida="$2"; shift 2
y0=565; y1=1440
if [ $# -ge 2 ]; then y0="$1"; y1="$2"; shift 2; fi
minutos="${*:-05 10 15 25 30 35 45 50 55}"
mkdir -p "$salida"
for dir in "$carpeta"/[0-2][0-9]; do
  h=$(basename "$dir")
  for m in $minutos; do
    v="$dir/$m.mp4"
    s="$salida/$h-$m.json"
    [ -f "$s" ] && continue
    [ -f "$v" ] || continue
    python3 tools/extraer_trayectorias.py --video "$v" --rastreador propio \
      --banda "$y0" "$y1" --salida "$s" > /dev/null 2>&1 \
      && echo "$h:$m ok" || echo "$h:$m FALLO"
  done
done
echo TERMINADO
