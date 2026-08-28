"""
Búsqueda de ubicaciones vía Nominatim (OpenStreetMap).

La política de uso de Nominatim exige un User-Agent propio que identifique
la aplicación (los que ponen las librerías HTTP por defecto no sirven),
máximo 1 petición por segundo, y cachear los resultados. Por eso esto va
por el backend y no directo desde el navegador: es el único lugar donde
podemos garantizar las tres cosas.

Ver: https://operations.osmfoundation.org/policies/nominatim/
"""

import json
import threading
import time
import urllib.parse
import urllib.request
from typing import Optional

from fastapi import APIRouter, HTTPException

from src.storage import traffic_db

router = APIRouter(prefix="/api/geo")

NOMINATIM_BASE = "https://nominatim.openstreetmap.org"
USER_AGENT = "AforoVehicular/1.0 (plataforma de conteo vehicular; contacto vía el operador del sistema)"
MIN_INTERVAL_S = 1.1  # la política dice 1 req/s; un margen para no rozar el límite

_rate_lock = threading.Lock()
_last_request_at = 0.0


def _rate_limited_fetch(url: str) -> list:
    """Serializa las peticiones a Nominatim y respeta el 1 req/s."""
    global _last_request_at
    with _rate_lock:
        elapsed = time.time() - _last_request_at
        if elapsed < MIN_INTERVAL_S:
            time.sleep(MIN_INTERVAL_S - elapsed)

        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode())
        except Exception as e:
            raise HTTPException(502, f"No se pudo consultar el servicio de mapas: {e}")
        finally:
            _last_request_at = time.time()

    return data if isinstance(data, list) else [data]


def _cached_fetch(cache_key: str, url: str) -> list:
    conn = traffic_db.get_connection()
    row = conn.execute(
        "SELECT response_json FROM geocode_cache WHERE query = ?", (cache_key,)
    ).fetchone()
    if row:
        return json.loads(row["response_json"])

    data = _rate_limited_fetch(url)
    conn.execute(
        "INSERT OR REPLACE INTO geocode_cache (query, response_json) VALUES (?, ?)",
        (cache_key, json.dumps(data))
    )
    conn.commit()
    return data


def _simplify(entry: dict) -> dict:
    return {
        "display_name": entry.get("display_name"),
        "latitude": float(entry["lat"]) if entry.get("lat") else None,
        "longitude": float(entry["lon"]) if entry.get("lon") else None,
    }


@router.get("/search")
def search(q: str):
    """Buscar una dirección o cruce de calles y obtener sus coordenadas."""
    query = q.strip()
    if len(query) < 3:
        raise HTTPException(400, "Escribe al menos 3 caracteres para buscar")

    params = urllib.parse.urlencode({"q": query, "format": "json", "limit": 5})
    results = _cached_fetch(f"search:{query.lower()}", f"{NOMINATIM_BASE}/search?{params}")
    return [_simplify(entry) for entry in results]


@router.get("/reverse")
def reverse(lat: float, lon: float):
    """Coordenadas -> dirección (cuando el usuario mueve el pin en el mapa)."""
    # Se redondea a 5 decimales (~1m) para que mover el pin unos píxeles no
    # genere una petición nueva por cada movimiento mínimo.
    key = f"reverse:{lat:.5f},{lon:.5f}"
    params = urllib.parse.urlencode({"lat": lat, "lon": lon, "format": "json"})
    results = _cached_fetch(key, f"{NOMINATIM_BASE}/reverse?{params}")
    if not results:
        raise HTTPException(404, "No se encontró una dirección para esas coordenadas")
    return _simplify(results[0])
