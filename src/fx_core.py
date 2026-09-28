"""Valor del dolar observado (CLP), consultado a mindicador.cl -- logica pura, sin ningun framework
de UI. src/fx.py (Streamlit) y src/ui_nicegui/fx.py envuelven `obtener_valor_dolar_sin_cache` cada
uno con su propio mecanismo de cache; este modulo no importa Streamlit para que el build empaquetado
de NiceGUI no arrastre Streamlit solo por transitividad de un import.

Esta es la unica funcion de la app que se conecta a internet (para todo lo demas la app es 100%
local). No envia ningun dato del usuario: es una consulta publica de solo lectura al valor del dolar
del dia. Cualquier falla (sin internet, API caida, respuesta rara) hace que la funcion devuelva None
en vez de reventar la pagina -- en ese caso el usuario sigue pudiendo ingresar el valor a mano.
"""
import requests

_URL = "https://mindicador.cl/api/dolar"
_MIN_PLAUSIBLE = 100.0
_MAX_PLAUSIBLE = 2000.0


def obtener_valor_dolar_sin_cache() -> float | None:
    try:
        resp = requests.get(_URL, timeout=5)
        resp.raise_for_status()
        valor = float(resp.json()["serie"][0]["valor"])
    except Exception:
        return None
    if not (_MIN_PLAUSIBLE <= valor <= _MAX_PLAUSIBLE):
        return None
    return valor
