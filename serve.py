#!/usr/bin/env python3
"""
Punto de entrada de la plataforma (backend + dashboard).

Para procesar un video puntual y generar reportes (JSON/CSV/gráficas),
sigue usando main.py — este script es para el modo "servicio en vivo".
"""

import os

import uvicorn
import yaml

if __name__ == "__main__":
    config_path = os.environ.get("PLATFORM_CONFIG", "configs/platform.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        server_config = (yaml.safe_load(f) or {}).get("server", {})

    uvicorn.run(
        "src.api.app:app",
        host=server_config.get("host", "0.0.0.0"),
        port=server_config.get("port", 8080),
        reload=False,
    )
