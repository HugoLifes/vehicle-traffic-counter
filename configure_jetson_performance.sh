#!/bin/bash
#
# Ajustes de rendimiento a nivel de sistema para el Jetson Nano.
# Independiente de si vas a correr el sistema nativo o con Docker:
# esto configura el host, no el contenedor.
#
# Uso: sudo bash configure_jetson_performance.sh

set -e

if [ ! -f /etc/nv_tegra_release ]; then
    echo "[✗] Este script está diseñado para NVIDIA Jetson Nano"
    exit 1
fi

echo "[✓] Jetson Nano detectado"
cat /etc/nv_tegra_release
echo ""

# Modo de máximo rendimiento (MAXN, sin límite de potencia)
echo "[*] Configurando modo MAXN..."
sudo nvpmodel -m 0

# Maximizar clocks de CPU/GPU/EMC
echo "[*] Maximizando clocks (jetson_clocks)..."
sudo jetson_clocks

echo ""
echo "[✓] Configuración actual:"
sudo nvpmodel -q

# Swap adicional si la memoria es baja (Nano 2GB)
TOTAL_MEM=$(free -m | awk '/^Mem:/{print $2}')
if [ "$TOTAL_MEM" -lt 3500 ]; then
    echo ""
    echo "[!] Memoria baja detectada (${TOTAL_MEM}MB)"
    if [ ! -f /swapfile ]; then
        echo "[*] Configurando swap adicional (4GB)..."
        sudo fallocate -l 4G /swapfile
        sudo chmod 600 /swapfile
        sudo mkswap /swapfile
        sudo swapon /swapfile
        echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
        echo "[✓] Swap configurado"
    else
        echo "[!] Swap ya existe, no se modifica"
    fi
fi

echo ""
echo "[✓] Sistema ajustado para máximo rendimiento."
echo "    Recuerda: esto se resetea al reiniciar el equipo, vuelve a"
echo "    correr este script (o agrégalo a un cron @reboot) tras cada boot."
echo "    Monitorea temperatura con: cat /sys/devices/virtual/thermal/thermal_zone*/temp"
