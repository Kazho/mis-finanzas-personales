"""Cache TTL manual -- reemplazo de @st.cache_data para el lado NiceGUI (no depende de una sesion
Streamlit). Deliberadamente chico: la app solo tiene 2 consultas cacheadas en total (valor del dolar,
version disponible para actualizar), no amerita una libreria."""
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

_cache: dict[str, tuple[float, object]] = {}


def cache_ttl(clave: str, ttl_segundos: float, obtener: Callable[[], T]) -> T:
    """Devuelve el valor cacheado bajo `clave` si tiene menos de `ttl_segundos`, si no llama a
    `obtener()` y guarda el resultado nuevo."""
    ahora = time.monotonic()
    if clave in _cache:
        guardado_en, valor = _cache[clave]
        if ahora - guardado_en < ttl_segundos:
            return valor
    valor = obtener()
    _cache[clave] = (ahora, valor)
    return valor


def invalidar(clave: str) -> None:
    _cache.pop(clave, None)
