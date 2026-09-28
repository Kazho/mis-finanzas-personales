"""Indicadores economicos (dolar observado, UF) consultados a mindicador.cl -- logica pura, sin ningun
framework de UI. src/fx.py (Streamlit) y src/ui_nicegui/fx.py envuelven las funciones `*_sin_cache`
cada uno con su propio mecanismo de cache; este modulo no importa Streamlit para que el build
empaquetado de NiceGUI no arrastre Streamlit solo por transitividad de un import.

Son las unicas funciones de la app que se conectan a internet (para todo lo demas la app es 100%
local). No envian ningun dato del usuario: son consultas publicas de solo lectura a indicadores del
dia. Cualquier falla (sin internet, API caida, respuesta rara) hace que la funcion devuelva None en
vez de reventar la pagina -- en ese caso la vista muestra un aviso o usa un valor por defecto.
"""
import datetime

import requests

_BASE = "https://mindicador.cl/api"
_DOLAR_MIN, _DOLAR_MAX = 100.0, 2000.0
_UF_MIN, _UF_MAX = 20_000.0, 100_000.0
# Inflacion anual fuera de este rango casi seguro es un dato roto de la API, no una lectura real.
_INFLACION_MIN, _INFLACION_MAX = -10.0, 50.0


def _valor_mindicador(ruta: str) -> float | None:
    try:
        resp = requests.get(f"{_BASE}/{ruta}", timeout=5)
        resp.raise_for_status()
        return float(resp.json()["serie"][0]["valor"])
    except Exception:
        return None


def obtener_valor_dolar_sin_cache() -> float | None:
    valor = _valor_mindicador("dolar")
    if valor is None or not (_DOLAR_MIN <= valor <= _DOLAR_MAX):
        return None
    return valor


def obtener_valor_uf_sin_cache() -> float | None:
    valor = _valor_mindicador("uf")
    if valor is None or not (_UF_MIN <= valor <= _UF_MAX):
        return None
    return valor


def obtener_inflacion_12m_sin_cache(uf_hoy: float | None = None) -> float | None:
    """Inflacion de los ultimos 12 meses (% anual), medida como la variacion de la UF entre hoy y
    hace un año. Se usa la UF y no la serie de IPC de mindicador porque esa serie se actualiza con
    meses de atraso, mientras que la UF se reajusta a diario siguiendo al IPC. `uf_hoy` permite
    reutilizar un valor ya consultado (y cacheado) en vez de pedirlo de nuevo."""
    uf_hoy = uf_hoy or obtener_valor_uf_sin_cache()
    hace_un_anio = datetime.date.today() - datetime.timedelta(days=365)
    uf_antes = _valor_mindicador(f"uf/{hace_un_anio.strftime('%d-%m-%Y')}")
    if not uf_hoy or not uf_antes:
        return None
    inflacion = (uf_hoy / uf_antes - 1) * 100
    if not (_INFLACION_MIN <= inflacion <= _INFLACION_MAX):
        return None
    return inflacion
