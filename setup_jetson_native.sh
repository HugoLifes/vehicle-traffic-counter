#!/bin/bash
#
# ⚠️ OBSOLETO para el hardware actual del proyecto (Jetson Orin Nano).
#
# Este script es del Jetson Nano ORIGINAL (JetPack 4.6, Python 3.6).
# El Orin Nano corre JetPack 6.x con Python 3.10 de fábrica, así que
# el problema que resuelve este script (ultralytics no soporta Python
# 3.6) simplemente no aplica — usa setup_jetson.sh, es más simple y
# está probado. Se deja este archivo por si en algún momento se usa
# también un Jetson Nano original en paralelo.
#
# ------------------------------------------------------------------
# Setup NATIVO (sin Docker) para Jetson Nano ORIGINAL —
# EXPERIMENTAL / NO VERIFICADO.
#
# Usa esto solo si por alguna razón no puedes usar Docker (ver
# setup_jetson.sh, que es la ruta recomendada y soportada oficialmente
# por Ultralytics).
#
# Problema de fondo: JetPack 4.6 trae Python 3.6 de sistema, y el
# paquete `ultralytics` requiere Python >=3.8. Este script instala
# Miniforge (conda para aarch64) para tener un Python 3.8 aislado del
# sistema, y dentro de ese entorno instala PyTorch precompilado para
# Jetson + ultralytics. Es el mismo truco que usa la comunidad
# (JetsonHacks, Qengineering) para correr paquetes modernos en el Nano.
#
# Uso: bash setup_jetson_native.sh

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_status()  { echo -e "${GREEN}[✓]${NC} $1"; }
print_error()   { echo -e "${RED}[✗]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[!]${NC} $1"; }

print_warning "Esta ruta es EXPERIMENTAL. Si algo falla, usa setup_jetson.sh (Docker)."
echo ""

if [ ! -f /etc/nv_tegra_release ]; then
    print_error "Este script está diseñado para NVIDIA Jetson Nano"
    exit 1
fi
print_status "Jetson Nano detectado"
cat /etc/nv_tegra_release
echo ""

# 1. Dependencias de sistema
print_status "Paso 1/6: Actualizando sistema e instalando dependencias..."
sudo apt-get update
sudo apt-get install -y \
    python3-pip python3-dev python3-setuptools \
    libhdf5-serial-dev hdf5-tools libhdf5-dev zlib1g-dev zip \
    libjpeg8-dev liblapack-dev libblas-dev gfortran libopenblas-dev \
    libavcodec-dev libavformat-dev libswscale-dev libv4l-dev \
    libxvidcore-dev libx264-dev libgtk-3-dev libatlas-base-dev \
    curl

# 2. Instalar Miniforge (conda aarch64) para tener Python 3.8 aislado
print_status "Paso 2/6: Instalando Miniforge (Python 3.8 aislado del sistema)..."
if [ ! -d "$HOME/miniforge3" ]; then
    curl -L -o /tmp/miniforge.sh \
        "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-aarch64.sh"
    bash /tmp/miniforge.sh -b -p "$HOME/miniforge3"
else
    print_warning "Miniforge ya está instalado en $HOME/miniforge3"
fi
source "$HOME/miniforge3/etc/profile.d/conda.sh"

# 3. Crear entorno con Python 3.8
print_status "Paso 3/6: Creando entorno 'vtc' con Python 3.8..."
conda create -y -n vtc python=3.8
conda activate vtc

# 4. Instalar PyTorch para Jetson (JetPack 4.6 -> PyTorch 1.10 / Python 3.8)
print_status "Paso 4/6: Instalando PyTorch para Jetson (revisa la URL vigente en"
print_warning "  https://forums.developer.nvidia.com/t/pytorch-for-jetson/72048"
print_warning "  antes de continuar; los links de NVIDIA cambian con el tiempo)."
read -p "Pega la URL del wheel de torch para tu JetPack/Python (o Enter para omitir): " TORCH_URL
if [ -n "$TORCH_URL" ]; then
    pip install --upgrade pip setuptools wheel
    pip install "$TORCH_URL"
    # torchvision debe compilarse a mano contra ese torch (ver guía de NVIDIA)
    print_warning "Instala torchvision compatible siguiendo la misma guía de NVIDIA."
else
    print_warning "Omitido. Sin PyTorch instalado, ultralytics no podrá usar GPU."
fi

# 5. Instalar ultralytics y dependencias del proyecto
print_status "Paso 5/6: Instalando ultralytics y dependencias del proyecto..."
pip install ultralytics
pip install -r requirements-jetson-docker.txt

# 6. Ajustes de rendimiento del sistema
print_status "Paso 6/6: Configurando rendimiento del sistema..."
if [ -f configure_jetson_performance.sh ]; then
    sudo bash configure_jetson_performance.sh
fi

echo ""
print_status "Setup nativo completado (recuerda: 'conda activate vtc' en cada sesión nueva)"
echo "  python3 main.py --source input/video.mp4 --config configs/jetson_optimized.yaml"
