"""Tema claro/oscuro para la version NiceGUI.

Mismos tokens de color que la version Streamlit (src/theme.py), duplicados aqui a proposito en vez
de importados: mientras ambas versiones conviven (migracion en curso) esta capa no depende en nada
de Streamlit, y cuando Streamlit se retire (ver plan de migracion, Fase 5) src/theme.py desaparece
sin arrastrar a este modulo. Si cambias un color, cambialo en los dos lugares mientras dure la
migracion.
"""
from nicegui import ui

LIGHT = {
    "bg": "#f8f9fa",
    "surface": "#ffffff",
    "border": "#e5e7eb",
    "text": "#191c1d",
    "text_muted": "#45464c",
    "primary": "#111827",
    "on_primary": "#ffffff",
    "success": "#10b981",
    "danger": "#ef4444",
    "accent_blue": "#3b82f6",
    "accent_orange": "#f97316",
    "accent_purple": "#a78bfa",
    "hero_bg": "#141b2b",
    "hero_text": "#ffffff",
    "hero_subtext": "#c0c6db",
}

DARK = {
    "bg": "#0f1419",
    "surface": "#1a2129",
    "border": "rgba(255,255,255,0.14)",
    "text": "#e7ecef",
    "text_muted": "#9ca3af",
    "primary": "#22c55e",
    "on_primary": "#052e16",
    "success": "#22c55e",
    "danger": "#ef4444",
    "accent_blue": "#3b82f6",
    "accent_orange": "#f97316",
    "accent_purple": "#a78bfa",
    "hero_bg": "#1a2129",
    "hero_text": "#e7ecef",
    "hero_subtext": "#9ca3af",
}

# Paleta cualitativa para graficos con varias categorias (torta, barras por cuenta/mes, lineas por
# cuenta) -- se usa igual en claro y oscuro (son tonos suficientemente saturados para leerse sobre
# fondo blanco o casi negro). Arranca con los 3 acentos que ya existian (para que un grafico de una
# sola cuenta, por ejemplo, coincida con el color de esa seccion) y suma mas tonos distinguibles.
PALETTE = [
    "#3b82f6",  # azul
    "#f97316",  # naranjo
    "#a78bfa",  # purpura
    "#10b981",  # verde
    "#ec4899",  # rosado
    "#eab308",  # ambar
    "#06b6d4",  # celeste
    "#ef4444",  # rojo
    "#84cc16",  # lima
    "#6366f1",  # indigo
]

# Un solo modo oscuro compartido por toda la app (app de escritorio de un usuario, una ventana). La
# preferencia se guarda en `_preferencia_oscura`, una variable de proceso -- NO en el elemento
# ui.dark_mode(), porque ese elemento se recrea (con su valor por defecto) cada vez que se navega a
# una pagina nueva, y el cambio de tema hoy fuerza un reload completo (ver alternar_modo) para que los
# elementos con color "a mano" (que no son nativos de Quasar) se vuelvan a pintar con colores(). Si
# solo se guardara en el elemento, el toggle se habria revertido solo en cada reload.
# TODO Fase 2+: si la app pasa a soportar mas de una ventana/pestaña a la vez, cambiar esto por
# app.storage.tab (requiere esperar la conexion del cliente, ver docs de NiceGUI) en vez de una
# variable de proceso compartida por todas las conexiones.
_dark_mode: ui.dark_mode | None = None
_preferencia_oscura: bool = False


def registrar_dark_mode(dark: ui.dark_mode) -> None:
    global _dark_mode
    _dark_mode = dark
    dark.value = _preferencia_oscura


def es_oscuro() -> bool:
    return _preferencia_oscura


def colores() -> dict:
    return DARK if es_oscuro() else LIGHT


def alternar_modo() -> None:
    global _preferencia_oscura
    _preferencia_oscura = not _preferencia_oscura
    if _dark_mode is not None:
        _dark_mode.value = _preferencia_oscura
