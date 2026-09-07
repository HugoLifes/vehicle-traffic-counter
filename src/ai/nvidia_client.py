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
            if attempt < max_retries:
                wait = 1.5 * (attempt + 1)
                logging.warning(f"{label} falló (intento {attempt + 1}/{max_retries + 1}): {e} — reintentando en {wait}s")
                time.sleep(wait)

    raise NvidiaClientError(f"Error llamando a {label} tras {max_retries + 1} intentos: {last_error}") from last_error


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

    def _call():
        response = client.chat.completions.create(
            model=config["models"]["chat"],
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout_s or config.get("request_timeout_s", 30),
        )
        return response.choices[0].message.content or ""

    return _with_retries("el modelo de chat", _call)


def vision(prompt: str, frame: np.ndarray, max_tokens: int = 400) -> str:
    """
    Analiza un frame (array BGR de OpenCV) con el modelo de visión.
    Se redimensiona/comprime antes de mandarlo — el free tier tiene
    límite de tamaño de payload en base64, y no hace falta más
    resolución para describir la escena en general.
    """
    client = _get_client()
    config = _load_config()

    h, w = frame.shape[:2]
    if w > 768:
        scale = 768 / w
        frame = cv2.resize(frame, (768, int(h * scale)))
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
    if not ok:
        raise NvidiaClientError("No se pudo codificar el frame para enviarlo")
    b64 = base64.b64encode(buf.tobytes()).decode()

    def _call():
        response = client.chat.completions.create(
            model=config["models"]["vision"],
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }],
            max_tokens=max_tokens,
            timeout=config.get("request_timeout_s", 30),
        )
        return response.choices[0].message.content or ""

    return _with_retries("el modelo de visión", _call)


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
