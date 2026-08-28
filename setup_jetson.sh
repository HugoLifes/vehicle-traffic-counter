#!/bin/bash
#
# Setup de la plataforma completa en el Jetson Orin Nano (JetPack 6.x).
#
# Wrapper delgado sobre docker-compose.jetson.yml — ver
# docs/JETSON_DEPLOY.md para la guía completa (límites de memoria,
# cámara IP vs USB, comandos útiles, troubleshooting).
#
# Uso: bash setup_jetson.sh

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_status()  { echo -e "${GREEN}[✓]${NC} $1"; }
print_error()   { echo -e "${RED}[✗]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[!]${NC} $1"; }

echo "============================================================"
echo "  SETUP - Plataforma de Aforo Vehicular (Jetson Orin Nano)"
echo "============================================================"
echo ""

if [ ! -f /etc/nv_tegra_release ]; then
    print_error "Este script está diseñado para correr DENTRO de un Jetson"
    print_warning "Si estás en tu PC, usa: pip install -r requirements.txt && python serve.py"
    exit 1
fi
print_status "Jetson detectado"
cat /etc/nv_tegra_release
print_warning "Este proyecto asume JetPack 6.x — si lo de arriba dice otra cosa,"
print_warning "revisa docs/JETSON_DEPLOY.md antes de seguir (hay que ajustar el"
print_warning "tag de la imagen base en Dockerfile.jetson)."
echo ""

if ! command -v docker &> /dev/null; then
    print_error "Docker no está instalado."
    echo "    sudo apt-get update && sudo apt-get install -y docker.io nvidia-container-runtime"
    echo "    sudo usermod -aG docker \$USER   # y vuelve a iniciar sesión"
    exit 1
fi
print_status "Docker encontrado: $(docker --version)"

if ! docker info 2>/dev/null | grep -qi nvidia; then
    print_warning "No se detectó 'nvidia' como runtime de Docker."
    print_warning "sudo apt-get install -y nvidia-container-runtime && sudo systemctl restart docker"
fi

if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        print_warning ".env creado desde .env.example — edítalo y pon tu NVIDIA_API_KEY real"
        print_warning "(gratis en https://build.nvidia.com) antes de continuar."
        exit 1
    fi
fi

print_status "Paso 1/2: Ajustando rendimiento del sistema..."
if [ -f configure_jetson_performance.sh ]; then
    sudo bash configure_jetson_performance.sh
fi

print_status "Paso 2/2: Construyendo y levantando la plataforma..."
docker compose -f docker-compose.jetson.yml up -d --build

echo ""
echo "============================================================"
print_status "Plataforma corriendo"
echo "============================================================"
echo ""
echo "  Panel:    http://$(hostname -I | awk '{print $1}'):8080"
echo "  Logs:     docker compose -f docker-compose.jetson.yml logs -f"
echo "  Detener:  docker compose -f docker-compose.jetson.yml down"
echo ""
echo "  Guía completa (cámara IP vs USB, límites de memoria, troubleshooting):"
echo "  docs/JETSON_DEPLOY.md"
