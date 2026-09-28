"""Chequeo de actualizaciones via GitHub Releases para la version empaquetada (.exe) de la app --
logica pura, sin ningun framework de UI. src/actualizador.py (Streamlit) y src/ui_nicegui/actualizador.py
envuelven estas funciones cada uno con su propio mecanismo de cache y su propio banner; este modulo
no importa Streamlit para que el build empaquetado de NiceGUI no arrastre Streamlit solo por
transitividad de un import.

Sigue el mismo patron defensivo que src/fx_core.py: si algo falla (sin internet, API caida, repo
todavia no configurado) las funciones devuelven None en vez de reventar la app -- el chequeo de
actualizaciones nunca debe afectar el uso normal, 100% offline, de la app. Tampoco hace nada si se
corre desde el codigo fuente (solo aplica a la version instalada como .exe).
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

GITHUB_OWNER = "Kazho"
GITHUB_REPO = "mis-finanzas-personales"

_URL_RELEASES = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"


def version_actual() -> str:
    """Version empaquetada en el .exe (archivo VERSION dentro del bundle de PyInstaller, en
    sys._MEIPASS -- que en el onedir moderno es la carpeta '_internal', NO la carpeta del .exe;
    usar Path(sys.executable).parent aca siempre fallaba en silencio y hacia caer a "0.0.0", asi
    que el aviso de actualizacion creia estar siempre desactualizado. En modo desarrollo, la raiz
    del repo)."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
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


def buscar_actualizacion_sin_cache() -> dict | None:
    """Devuelve {"version": str, "url_instalador": str} si hay una version mas nueva publicada
    en GitHub Releases, o None si no hay, si algo fallo, o si no aplica."""
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
    if _a_tupla(version_remota) <= _a_tupla(version_actual()):
        return None
    return {"version": version_remota.lstrip("v"), "url_instalador": instalador}


def descargar_instalador(url_instalador: str) -> Path | None:
    """Descarga el instalador a un temporal. Devuelve la ruta, o None si fallo."""
    destino = Path(tempfile.gettempdir()) / "MisFinanzasPersonales-Update.exe"
    try:
        with requests.get(url_instalador, timeout=30, stream=True) as resp:
            resp.raise_for_status()
            with open(destino, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
    except Exception:
        return None
    return destino


def instalar_y_salir(destino: Path):
    """Lanza el instalador silencioso como proceso aparte y cierra la app actual -- el instalador
    reemplaza los archivos con la app ya cerrada."""
    subprocess.Popen(
        [str(destino), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
    )
    os._exit(0)
