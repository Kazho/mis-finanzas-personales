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

    # La base de datos esta cifrada (src/boveda.py): el esquema y los datos por defecto se preparan
    # recien al desbloquearla, en paginas_nicegui/desbloquear.py.
    from src.db import boveda

    # Registra las paginas (decoradas con @ui.page adentro de cada modulo) antes de arrancar
    # el servidor.
    from paginas_nicegui import (  # noqa: F401
        cargar_cartola,
        cargar_deuda_cmf,
        categorias,
        cuentas,
        dashboard,
        desbloquear,
        inicio,
        panorama,
        registrar_ahorro,
    )

    import asyncio

    from nicegui import Client, app, core, run, ui
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.middleware.trustedhost import TrustedHostMiddleware
    from starlette.responses import RedirectResponse

    from src import sesion_local

    # Rutas que se sirven sin sesion: la pantalla de desbloqueo, el canje de su codigo, y los recursos
    # internos de NiceGUI (JS/CSS de la libreria y el canal websocket, que no contienen datos; las
    # paginas con datos solo se crean via una ruta protegida).
    rutas_publicas = ("/desbloquear", "/_activar")
    prefijos_publicos = ("/_nicegui/", "/_nicegui_ws/")
    cabeceras_seguridad = {
        "X-Frame-Options": "DENY",  # nadie puede incrustar la app en otra pagina (clickjacking)
        "Content-Security-Policy": "frame-ancestors 'none'",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store",
    }

    class _RequiereSesion(BaseHTTPMiddleware):
        """Toda pagina exige boveda desbloqueada Y la cookie de sesion del navegador que la desbloqueo
        (src/sesion_local.py). Sin cookie valida -- otro programa, otro navegador, una web maliciosa --
        se redirige a /desbloquear, que vuelve a pedir la contraseña."""

        async def dispatch(self, request, call_next):
            ruta = request.url.path
            publica = ruta in rutas_publicas or ruta.startswith(prefijos_publicos)
            autorizado = boveda.desbloqueada() and sesion_local.token_valido(request.cookies.get(sesion_local.NOMBRE_COOKIE))
            if autorizado and not publica:
                sesion_local.registrar_actividad()  # abrir una pagina tambien cuenta como actividad
            respuesta = await call_next(request) if (publica or autorizado) else RedirectResponse("/desbloquear")
            for nombre, valor in cabeceras_seguridad.items():
                if nombre == "Cache-Control" and ruta.startswith("/_nicegui/"):
                    continue  # los recursos estaticos de la libreria si se pueden cachear
                respuesta.headers.setdefault(nombre, valor)
            return respuesta

    @app.get("/_activar")
    def _activar(c: str = ""):
        token = sesion_local.canjear_codigo(c)
        if token is None or not boveda.desbloqueada():
            return RedirectResponse("/desbloquear")
        respuesta = RedirectResponse("/")
        # HttpOnly: el JavaScript de la pagina no puede leerla; SameSite=Strict: ninguna otra web
        # puede hacer que el navegador la envie.
        respuesta.set_cookie(sesion_local.NOMBRE_COOKIE, token, httponly=True, samesite="strict", path="/")
        return respuesta

    app.add_middleware(_RequiereSesion)
    # Rechaza peticiones cuyo Host no sea este PC: bloquea el "DNS rebinding", donde una web maliciosa
    # hace que su dominio apunte a 127.0.0.1 para leer la app como si fuera propia.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]"])
    # El canal websocket de NiceGUI acepta cualquier origen por defecto; se limita a la propia app.
    core.sio.eio.cors_allowed_origins = [f"http://localhost:{PUERTO}", f"http://127.0.0.1:{PUERTO}"]

    def _cerrar():
        sesion_local.revocar_todo()
        boveda.bloquear()

    # Al cerrar la app se guarda y se descarta la copia descifrada que estaba en memoria.
    app.on_shutdown(_cerrar)

    def _pestanas_con_datos():
        """Pestañas abiertas en paginas protegidas (no la de desbloqueo) y todavia conectadas."""
        return [c for c in list(Client.instances.values())
                if c.page.path != "/desbloquear" and c.has_socket_connection]

    async def _vigilar_inactividad():
        """Bloquea la app sola tras INACTIVIDAD_MAX_S sin actividad en ninguna pestaña, avisando
        AVISO_ANTES_S antes. Corre durante toda la vida del servidor."""
        avisado = False
        while True:
            await asyncio.sleep(5)
            try:
                if not boveda.desbloqueada():
                    avisado = False
                    continue
                inactivo = sesion_local.segundos_inactivo()
                if inactivo >= sesion_local.INACTIVIDAD_MAX_S:
                    sesion_local.revocar_todo()
                    await run.io_bound(boveda.bloquear)
                    for cliente in _pestanas_con_datos():
                        cliente.run_javascript("window.location.href = '/desbloquear'")
                    avisado = False
                elif inactivo >= sesion_local.INACTIVIDAD_MAX_S - sesion_local.AVISO_ANTES_S:
                    if not avisado:
                        for cliente in _pestanas_con_datos():
                            with cliente:
                                ui.notify(
                                    f"Por seguridad, la app se bloqueara en {sesion_local.AVISO_ANTES_S} segundos por inactividad. "
                                    "Mueve el mouse o presiona una tecla para seguir.",
                                    type="warning", timeout=sesion_local.AVISO_ANTES_S * 1000, close_button=True,
                                )
                        avisado = True
                else:
                    avisado = False
            except Exception as e:  # el vigilante nunca debe morir por un error puntual
                print(f"[vigilante de inactividad] {e!r}")

    app.on_startup(lambda: asyncio.create_task(_vigilar_inactividad()))

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
