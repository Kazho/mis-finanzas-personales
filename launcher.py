"""Punto de entrada del .exe empaquetado (PyInstaller). Reemplaza a run.bat: levanta el
servidor de Streamlit embebido, sin consola visible, y abre el navegador solo.

Con --windowed (sin consola), sys.stdout/stderr son None: cualquier print() de una libreria
revienta la app con AttributeError, asi que lo primero que se hace es redirigir ambos a un
archivo de log real (no os.devnull) para poder diagnosticar fallos de un usuario sin terminal.
"""
import os
import sys
import socket
import threading
import time
import webbrowser
from pathlib import Path

PUERTO = 8765


def _app_dir() -> Path:
    """Carpeta que contiene app.py: sys._MEIPASS en el build empaquetado (PyInstaller la fija
    ahi tanto en onedir como en onefile -- en onedir moderno es una subcarpeta '_internal',
    NO la carpeta del .exe, por eso no se puede asumir Path(sys.executable).parent), o la
    carpeta del repo en modo desarrollo."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


def _redirigir_salida_a_log():
    if not getattr(sys, "frozen", False):
        return
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MisFinanzasPersonales" / "logs"
    base.mkdir(parents=True, exist_ok=True)
    log = open(base / "app.log", "a", buffering=1, encoding="utf-8")
    sys.stdout = log
    sys.stderr = log


def _ya_esta_corriendo() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", PUERTO)) == 0


def _abrir_navegador_cuando_este_listo():
    import urllib.request

    url_salud = f"http://localhost:{PUERTO}/_stcore/health"
    inicio = time.time()
    while time.time() - inicio < 20:
        try:
            if urllib.request.urlopen(url_salud, timeout=1).status == 200:
                webbrowser.open(f"http://localhost:{PUERTO}")
                return
        except Exception:
            pass
        time.sleep(0.2)


def main():
    _redirigir_salida_a_log()

    if _ya_esta_corriendo():
        webbrowser.open(f"http://localhost:{PUERTO}")
        return

    os.chdir(_app_dir())
    os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"

    threading.Thread(target=_abrir_navegador_cuando_este_listo, daemon=True).start()

    from streamlit.web import cli as stcli

    sys.argv = [
        "streamlit",
        "run",
        "app.py",
        "--server.port",
        str(PUERTO),
        "--server.address",
        "localhost",
        "--server.headless",
        "true",
        "--global.developmentMode",
        "false",
        "--server.fileWatcherType",
        "none",
    ]
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()
