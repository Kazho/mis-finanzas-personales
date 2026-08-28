"""Valor del dolar observado (CLP), consultado a mindicador.cl.

Esta es la unica funcion de la app que se conecta a internet (para todo lo demas la app es
100% local). No envia ningun dato del usuario: es una consulta publica de solo lectura al
valor del dolar del dia. Se cachea por una hora para no repetir la consulta en cada rerun de
Streamlit, y cualquier falla (sin internet, API caida, respuesta rara) hace que la funcion
devuelva None en vez de reventar la pagina — en ese caso el usuario sigue pudiendo ingresar el
valor a mano.
"""
import requests
import streamlit as st

_URL = "https://mindicador.cl/api/dolar"
_MIN_PLAUSIBLE = 100.0
_MAX_PLAUSIBLE = 2000.0


@st.cache_data(ttl=3600, show_spinner=False)
def obtener_valor_dolar() -> float | None:
    try:
        resp = requests.get(_URL, timeout=5)
        resp.raise_for_status()
        valor = float(resp.json()["serie"][0]["valor"])
    except Exception:
        return None
    if not (_MIN_PLAUSIBLE <= valor <= _MAX_PLAUSIBLE):
        return None
    return valor
