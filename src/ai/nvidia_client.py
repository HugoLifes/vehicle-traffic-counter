"""
Cliente único para las capacidades de NVIDIA API que usa el proyecto:
chat (IA validadora + generación del RAG), visión (IA visual) y
embeddings (RAG). Todo vía el endpoint OpenAI-compatible de
build.nvidia.com/NIM — un solo cliente `openai` apuntando a otro
base_url, sin SDK propietario que mantener.

Reranking dedicado no está disponible en la cuenta configurada por
ahora (ver configs/nvidia_api.yaml) — el RAG usa fusión híbrida
(denso + léxico + RRF) sin ese paso.
"""

import base64
import logging
import os
import time
from functools import lru_cache
from typing import Callable, List, Optional, TypeVar

import cv2
import numpy as np
import yaml
from openai import APIError, APIStatusError, APITimeoutError, OpenAI

CONFIG_PATH = os.environ.get("NVIDIA_API_CONFIG", "configs/nvidia_api.yaml")


class NvidiaClientError(RuntimeError):
    """La API de NVIDIA no respondió como se esperaba (sin key, modelo no disponible, etc.)."""


@lru_cache
def _load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache
def _get_client() -> OpenAI:
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        raise NvidiaClientError(
            "Falta NVIDIA_API_KEY. Genera una gratis en https://build.nvidia.com "
            "y ponla en tu .env (ver .env.example)."
        )
    config = _load_config()
    return OpenAI(api_key=api_key, base_url=config["base_url"])


def is_configured() -> bool:
    return bool(os.environ.get("NVIDIA_API_KEY"))


T = TypeVar("T")


def _with_retries(label: str, call: Callable[[], T]) -> T:
    """
    El free tier de NVIDIA responde 502 de vez en cuando bajo carga
    (confirmado probando en vivo: 1 de 3 llamadas idénticas falló así
    y las otras dos funcionaron perfecto) — no es un bug nuestro, hay
    que reintentar con backoff antes de darlo por error real.
    """
    config = _load_config()
    max_retries = config.get("max_retries", 2)
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            return call()
        except (APIStatusError, APITimeoutError, APIError) as e:
            last_error = e
            # 404 = el modelo ya no existe en la cuenta: reintentar solo
            # gasta segundos antes de pasar al de respaldo.
            if isinstance(e, APIStatusError) and e.status_code == 404:
                break
            if attempt < max_retries:
                wait = 1.5 * (attempt + 1)
                logging.warning(f"{label} falló (intento {attempt + 1}/{max_retries + 1}): {e} — reintentando en {wait}s")
                time.sleep(wait)

    raise NvidiaClientError(f"Error llamando a {label} tras {max_retries + 1} intentos: {last_error}") from last_error


def _modelos_de(rol: str) -> List[str]:
    """El modelo del rol y sus respaldos (`<rol>_respaldo` en la config)."""
    modelos = _load_config()["models"]
    return [modelos[rol]] + list(modelos.get(f"{rol}_respaldo") or [])


def _extra(modelo: str) -> Optional[dict]:
    """`chat_extra` (apagar el razonamiento) solo para los modelos que lo
    aceptan: los listados en `sin_razonamiento`."""
    config = _load_config()
    return config.get("chat_extra") if modelo in (config.get("sin_razonamiento") or []) else None


def _con_respaldo(rol: str, etiqueta: str, llamar: Callable[[str], T]) -> T:
    """Prueba el modelo del rol y, si la API dice que ya no existe (404),
    sus respaldos en orden. Un 404 es un modelo retirado del catálogo:
    reintentarlo no sirve. Cualquier otro error sí es de la llamada."""
    ultimo = None
    for modelo in _modelos_de(rol):
        try:
            return _with_retries(etiqueta, lambda: llamar(modelo))
        except NvidiaClientError as e:
            if getattr(e.__cause__, "status_code", None) != 404:
                raise
            logging.warning(f"{etiqueta}: {modelo} ya no existe en la API (404); "
                            f"se usa el de respaldo. Actualiza configs/nvidia_api.yaml.")
            ultimo = e
    raise ultimo


def chat(messages: List[dict], max_tokens: int = 512, temperature: float = 0.2,
         timeout_s: Optional[float] = None) -> str:
    """
    Llamada de texto simple — la usan la IA validadora y el RAG.

    timeout_s permite pedir más tiempo que el límite general. El RAG lo
    necesita: manda seis fragmentos de contexto a un modelo de 90B y pide
    varios cientos de tokens, y con los 30 s que bastan para un
    sanity-check de conteos se agota siempre.
    """
    client = _get_client()
    config = _load_config()

    def _call(modelo):
        response = client.chat.completions.create(
            model=modelo,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout_s or config.get("request_timeout_s", 30),
            extra_body=_extra(modelo),
        )
        return response.choices[0].message.content or ""

    return _con_respaldo("chat", "el modelo de chat", _call)


def vision(prompt: str, frame: np.ndarray, max_tokens: int = 400,
           rol: str = "vision", timeout_s: Optional[float] = None,
           calidad_jpeg: int = 70) -> str:
    """
    Analiza un frame (array BGR de OpenCV) con el modelo de visión.
    Se redimensiona/comprime antes de mandarlo — el free tier tiene
    límite de tamaño de payload en base64, y no hace falta más
    resolución para describir la escena en general.

    `rol` elige el modelo de configs/nvidia_api.yaml: "clasificacion" usa
    uno de razonamiento, que necesita más tokens y más tiempo.
    """
    client = _get_client()
    config = _load_config()

    h, w = frame.shape[:2]
    if w > 768:
        scale = 768 / w
        frame = cv2.resize(frame, (768, int(h * scale)))
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, calidad_jpeg])
    if not ok:
        raise NvidiaClientError("No se pudo codificar el frame para enviarlo")
    b64 = base64.b64encode(buf.tobytes()).decode()

    def _call(modelo):
        response = client.chat.completions.create(
            model=modelo,
            extra_body=_extra(modelo),
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }],
            max_tokens=max_tokens,
            timeout=timeout_s or config.get("request_timeout_s", 30),
        )
        return response.choices[0].message.content or ""

    return _con_respaldo(rol, "el modelo de visión", _call)


def embed(texts: List[str], input_type: str = "passage") -> List[List[float]]:
    """input_type: 'query' al buscar en el RAG, 'passage' al indexar documentos."""
    client = _get_client()
    config = _load_config()

    def _call():
        response = client.embeddings.create(
            model=config["models"]["embedding"],
            input=texts,
            extra_body={"input_type": input_type},
            timeout=config.get("request_timeout_s", 30),
        )
        return [item.embedding for item in response.data]

    return _with_retries("el modelo de embeddings", _call)
