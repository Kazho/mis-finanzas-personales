"""Punto de entrada del .exe empaquetado (PyInstaller) y de "py launcher.py" en modo dev.
Reemplaza a run.bat/app_nicegui.py como entry point unico del build: levanta el servidor NiceGUI
embebido, sin consola visible, y abre el navegador solo -- mismo patron que tenia con Streamlit
(ver historial), solo que ahora NiceGUI se encarga el mismo de esperar a que el servidor este listo
antes de abrir el navegador (`ui.run(show=True)`), asi que ya no hace falta el hilo de sondeo manual
que existia antes para el health-check de Streamlit.

Con --windowed (sin consola), sys.stdout/stderr son None: cualquier print() de una libreria revienta
la app con AttributeError, asi que lo primero que se hace es redirigir ambos a un archivo de log real
(no os.devnull) para poder diagnosticar fallos de un usuario sin terminal.
"""
import os
import socket
import sys
import webbrowser
from pathlib import Path

PUERTO = 8765


def _app_dir() -> Path:
    """Carpeta que contiene los modulos de la app: sys._MEIPASS en el build empaquetado
    (PyInstaller la fija ahi tanto en onedir como en onefile), o la carpeta del repo en modo
    desarrollo."""
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


def main():
    _redirigir_salida_a_log()

    if _ya_esta_corriendo():
        webbrowser.open(f"http://localhost:{PUERTO}")
        return

    os.chdir(_app_dir())

    from src.categorias import asegurar_buckets_default, asegurar_reglas_default
    from src.db import init_db

    init_db()
    asegurar_reglas_default()
    asegurar_buckets_default()

    # Registra las 6 paginas (decoradas con @ui.page adentro de cada modulo) antes de arrancar
    # el servidor.
    from paginas_nicegui import (  # noqa: F401
        cargar_cartola,
        cargar_deuda_cmf,
        categorias,
        dashboard,
        inicio,
        registrar_ahorro,
    )

    from nicegui import ui

    ui.run(
        title="Mis Finanzas Personales",
        port=PUERTO,
        host="localhost",
        reload=False,
        show=True,
        favicon="\U0001F4B0",
    )


if __name__ in {"__main__", "__mp_main__"}:
    main()
