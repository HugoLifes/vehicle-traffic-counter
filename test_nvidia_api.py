#!/usr/bin/env python3
"""
Verifica que NVIDIA_API_KEY funciona contra las 3 capacidades que usa
el proyecto: chat, visión y embeddings. Corre esto después de poner tu
key en .env, antes de usar las IAs visual/validadora/RAG.

    python test_nvidia_api.py
"""

import sys

import numpy as np
from dotenv import load_dotenv

load_dotenv()

from src.ai import nvidia_client  # noqa: E402


def main():
    print("=" * 60)
    print("VERIFICACIÓN DE CONECTIVIDAD - NVIDIA API")
    print("=" * 60)

    if not nvidia_client.is_configured():
        print("\n✗ NVIDIA_API_KEY no está configurada.")
        print("  Copia .env.example a .env y pon tu key ahí.")
        print("  Se genera gratis en https://build.nvidia.com")
        return 1

    results = {}

    print("\n[1/3] Chat (IA validadora / generación RAG)...")
    try:
        reply = nvidia_client.chat(
            [{"role": "user", "content": "Responde solo con la palabra: OK"}],
            max_tokens=10,
        )
        print(f"  ✓ Respuesta: {reply!r}")
        results["chat"] = True
    except Exception as e:
        print(f"  ✗ Error: {e}")
        results["chat"] = False

    print("\n[2/3] Visión (IA visual)...")
    try:
        fake_frame = np.full((360, 640, 3), 120, dtype=np.uint8)
        reply = nvidia_client.vision("Describe brevemente qué ves.", fake_frame, max_tokens=60)
        print(f"  ✓ Respuesta: {reply[:120]!r}")
        results["vision"] = True
    except Exception as e:
        print(f"  ✗ Error: {e}")
        results["vision"] = False

    print("\n[3/3] Embeddings (RAG)...")
    try:
        vectors = nvidia_client.embed(["prueba de conectividad"], input_type="query")
        print(f"  ✓ Vector recibido, dimensiones: {len(vectors[0])}")
        results["embedding"] = True
    except Exception as e:
        print(f"  ✗ Error: {e}")
        results["embedding"] = False

    print("\n" + "=" * 60)
    passed = sum(results.values())
    print(f"RESULTADO: {passed}/{len(results)} capacidades funcionando")
    print("=" * 60)

    if not results.get("chat") or not results.get("embedding"):
        print("\nNota: revisa configs/nvidia_api.yaml — el catálogo de NVIDIA")
        print("cambia con el tiempo y esta cuenta puede tener habilitado un")
        print("subconjunto distinto. Prueba otros IDs de build.nvidia.com si")
        print("alguno falla con 404.")

    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
