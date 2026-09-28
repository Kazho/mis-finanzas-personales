"""Sesion del navegador que desbloqueo la app.

Sin esto, una vez desbloqueada la boveda cualquier programa del PC (o una pagina web maliciosa via
DNS rebinding) podia leer los datos con un simple GET a localhost:8765 -- desbloquear abria la app para
todos. Ahora el desbloqueo queda atado al navegador que ingreso la contraseña mediante una cookie
secreta HttpOnly; cualquier otro cliente debe ingresar la contraseña de nuevo.

Como el desbloqueo ocurre por websocket (no hay respuesta HTTP donde poner la cookie), se usa un codigo
de un solo uso y 30 segundos de vida: la pagina de desbloqueo navega a /_activar?c=<codigo>, que canjea
el codigo por la cookie y redirige al inicio.
"""
import hmac
import os
import secrets
import threading
import time

NOMBRE_COOKIE = "mfp_sesion"
VIDA_CODIGO_S = 30
# Bloqueo automatico por inactividad: sin mouse/teclado/scroll en ninguna pestaña durante este tiempo,
# la app se bloquea sola (ver el vigilante en launcher.py). Se avisa AVISO_ANTES_S segundos antes.
INACTIVIDAD_MAX_S = int(os.environ.get("MFP_INACTIVIDAD_S", 5 * 60))  # la variable es solo para pruebas
AVISO_ANTES_S = min(60, INACTIVIDAD_MAX_S // 3)

_lock = threading.Lock()
_tokens: set[str] = set()
_codigos: dict[str, float] = {}
_ultima_actividad = time.monotonic()


def registrar_actividad() -> None:
    global _ultima_actividad
    _ultima_actividad = time.monotonic()


def segundos_inactivo() -> float:
    return time.monotonic() - _ultima_actividad


def emitir_codigo() -> str:
    codigo = secrets.token_urlsafe(32)
    with _lock:
        _codigos[codigo] = time.monotonic() + VIDA_CODIGO_S
    return codigo


def canjear_codigo(codigo: str) -> str | None:
    """Devuelve un token de sesion nuevo si el codigo es valido (y lo invalida), o None."""
    with _lock:
        vence = _codigos.pop(codigo or "", None)
        if vence is None or time.monotonic() > vence:
            return None
        token = secrets.token_urlsafe(32)
        _tokens.add(token)
    registrar_actividad()  # recien desbloqueada: el conteo de inactividad parte de cero
    return token


def token_valido(token: str | None) -> bool:
    if not token:
        return False
    with _lock:
        # compare_digest para no filtrar por tiempo de respuesta cuantos caracteres coinciden.
        return any(hmac.compare_digest(token, t) for t in _tokens)


def revocar_todo() -> None:
    """Al bloquear: todas las sesiones y codigos pendientes dejan de valer."""
    with _lock:
        _tokens.clear()
        _codigos.clear()
