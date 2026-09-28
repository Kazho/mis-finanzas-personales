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
import base64
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

GITHUB_OWNER = "Kazho"
GITHUB_REPO = "mis-finanzas-personales"

# Firma de releases: cada instalador se publica con un archivo .sig firmado (Ed25519) con una clave
# privada que el autor guarda FUERA de GitHub (ver installer/firmar_release.py). La app solo instala
# una actualizacion si la firma es valida para esta clave publica -- asi, aunque alguien tomara control
# de la cuenta de GitHub, no podria distribuir un instalador malicioso. Mientras sea None (clave aun no
# generada), la app avisa de la version nueva pero no la instala sola: pide descargarla a mano.
# La escribe `py installer/firmar_release.py generar-clave`; no editar a mano.
CLAVE_PUBLICA_RELEASES: str | None = None
CONTEXTO_FIRMA = b"MisFinanzasPersonales-release-v1"
URL_RELEASES_WEB = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"


def mensaje_a_firmar(version: str, sha256_hex: str) -> bytes:
    """Lo que se firma: contexto + version + hash del instalador. Incluir la version impide reutilizar
    la firma de un instalador viejo (con fallas conocidas) haciendolo pasar por uno nuevo."""
    return b"\n".join([CONTEXTO_FIRMA, version.lstrip("v").encode(), sha256_hex.lower().encode()])


def _sha256_archivo(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def firma_valida(instalador: Path, firma_b64: str, version: str, clave_publica_b64: str | None = None) -> bool:
    clave_b64 = clave_publica_b64 or CLAVE_PUBLICA_RELEASES
    if not clave_b64:
        return False
    try:
        clave = Ed25519PublicKey.from_public_bytes(base64.b64decode(clave_b64))
        clave.verify(base64.b64decode(firma_b64.strip()), mensaje_a_firmar(version, _sha256_archivo(instalador)))
        return True
    except (InvalidSignature, ValueError):
        return False

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
    """Devuelve {"version", "url_instalador", "url_firma"} si hay una version mas nueva publicada en
    GitHub Releases (url_firma puede ser None si el release no trae .sig), o None si no hay, si algo
    fallo, o si no aplica."""
    if not getattr(sys, "frozen", False):
        return None
    try:
        resp = requests.get(_URL_RELEASES, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        version_remota = data.get("tag_name", "")
        assets = data.get("assets", [])
        instalador = next(
            (a for a in assets if a["name"].lower().endswith(".exe")), None
        )
        firma = next(
            (a for a in assets if instalador and a["name"] == instalador["name"] + ".sig"), None
        )
    except Exception:
        return None
    if not version_remota or not instalador:
        return None
    if _a_tupla(version_remota) <= _a_tupla(version_actual()):
        return None
    return {
        "version": version_remota.lstrip("v"),
        "url_instalador": instalador["browser_download_url"],
        "url_firma": firma["browser_download_url"] if firma else None,
    }


def descargar_instalador(url_instalador: str, url_firma: str | None, version: str) -> Path | None:
    """Descarga el instalador y lo devuelve SOLO si su firma es valida; si no hay firma, no hay clave
    configurada o la firma no calza, lo borra y devuelve None.

    Se descarga a una carpeta temporal nueva y privada (no a un nombre fijo en %TEMP%), para que otro
    programa no pueda cambiar el archivo entre la verificacion y la ejecucion."""
    if not url_firma or not CLAVE_PUBLICA_RELEASES:
        return None
    destino = Path(tempfile.mkdtemp(prefix="mfp-update-")) / "MisFinanzasPersonales-Update.exe"
    try:
        firma_b64 = requests.get(url_firma, timeout=15).text
        with requests.get(url_instalador, timeout=30, stream=True) as resp:
            resp.raise_for_status()
            with open(destino, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
    except Exception:
        destino.unlink(missing_ok=True)
        return None
    if not firma_valida(destino, firma_b64, version):
        destino.unlink(missing_ok=True)
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
