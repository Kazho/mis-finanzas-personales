"""Chequeo de actualizaciones via GitHub Releases para la version empaquetada (.exe) de la
app. Sigue el mismo patron defensivo que src/fx.py: si algo falla (sin internet, API caida,
repo todavia no configurado) la funcion devuelve None en vez de romper la app -- el chequeo
de actualizaciones nunca debe afectar el uso normal, 100% offline, de la app. Tampoco hace
nada si se corre desde el codigo fuente (solo aplica a la version instalada como .exe).
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import requests
import streamlit as st

GITHUB_OWNER = "Kazho"
GITHUB_REPO = "mis-finanzas-personales"

_URL_RELEASES = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"


def _version_actual() -> str:
    """Version empaquetada en el .exe (archivo VERSION en la raiz del bundle de PyInstaller,
    o en la raiz del repo en modo desarrollo)."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent.parent
    try:
        return (base / "VERSION").read_text(encoding="utf-8").strip()
    except Exception:
        return "0.0.0"


def _a_tupla(version: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in version.strip().lstrip("v").split("."))
    except Exception:
        return (0, 0, 0)


@st.cache_data(ttl=21600, show_spinner=False)
def buscar_actualizacion() -> dict | None:
    """Devuelve {"version": str, "url_instalador": str} si hay una version mas nueva
    publicada en GitHub Releases, o None si no hay, si algo fallo, o si no aplica."""
    if not getattr(sys, "frozen", False):
        return None
    try:
        resp = requests.get(_URL_RELEASES, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        version_remota = data.get("tag_name", "")
        assets = data.get("assets", [])
        instalador = next(
            (a["browser_download_url"] for a in assets if a["name"].lower().endswith(".exe")), None
        )
    except Exception:
        return None
    if not version_remota or not instalador:
        return None
    if _a_tupla(version_remota) <= _a_tupla(_version_actual()):
        return None
    return {"version": version_remota.lstrip("v"), "url_instalador": instalador}


def mostrar_aviso_actualizacion():
    """Banner discreto si hay una version nueva disponible, con boton para descargarla e
    instalarla sin que el usuario tenga que ir a buscarla a mano."""
    disponible = buscar_actualizacion()
    if not disponible:
        return
    if st.session_state.get("actualizacion_descartada") == disponible["version"]:
        return

    col1, col2, col3 = st.columns([5, 1, 1])
    with col1:
        st.info(f"\U0001F195 Hay una version nueva disponible: **{disponible['version']}**")
    with col2:
        if st.button("Actualizar ahora", key="btn_actualizar_ahora"):
            _descargar_e_instalar(disponible["url_instalador"])
    with col3:
        if st.button("Ahora no", key="btn_descartar_actualizacion"):
            st.session_state["actualizacion_descartada"] = disponible["version"]
            st.rerun()


def _descargar_e_instalar(url_instalador: str):
    destino = Path(tempfile.gettempdir()) / "MisFinanzasPersonales-Update.exe"
    with st.spinner("Descargando actualizacion..."):
        try:
            with requests.get(url_instalador, timeout=30, stream=True) as resp:
                resp.raise_for_status()
                with open(destino, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
        except Exception:
            st.error("No se pudo descargar la actualizacion. Intenta mas tarde desde 'Actualizar ahora'.")
            return

    st.success("Actualizacion descargada. La app se va a cerrar para instalarla...")
    subprocess.Popen(
        [str(destino), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
    )
    os._exit(0)
