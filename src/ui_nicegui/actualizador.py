"""Aviso de actualizacion disponible -- version NiceGUI de src.actualizador.mostrar_aviso_actualizacion.

Reutiliza toda la logica de red/descarga/instalacion de src/actualizador_core.py (GitHub Releases,
comparacion de version, descarga e instalacion silenciosa) -- eso no cambia nada, y ese modulo no
importa Streamlit (a diferencia de src/actualizador.py, el wrapper que SI lo usa) para que este build
no arrastre Streamlit solo por transitividad de un import. Lo que cambia aca es la UI (banner NiceGUI
en vez de st.info/st.button) y el cache (TTL manual, ver src.ui_nicegui.cache, en vez de
@st.cache_data que depende de una sesion Streamlit)."""
from nicegui import run, ui

from src.actualizador_core import buscar_actualizacion_sin_cache, descargar_instalador, instalar_y_salir
from src.ui_nicegui.cache import cache_ttl
from src.ui_nicegui.theme import colores

# Variable de proceso, no por pestaña -- misma logica que _preferencia_oscura en theme.py (app de
# escritorio de un usuario, una ventana).
_version_descartada: str | None = None


def _buscar_actualizacion() -> dict | None:
    return cache_ttl("actualizacion_disponible", 21600, buscar_actualizacion_sin_cache)


@ui.refreshable
def aviso_actualizacion():
    disponible = _buscar_actualizacion()
    if not disponible or disponible["version"] == _version_descartada:
        return
    c = colores()
    with ui.row().classes("w-full items-center justify-between rounded p-3 mb-3").style(
        f"background-color:{c['accent_blue']}1a;border-left:3px solid {c['accent_blue']}"
    ):
        ui.label(f"\U0001F195 Hay una version nueva disponible: {disponible['version']}").style(f"color:{c['text']}")
        with ui.row().classes("gap-2"):
            ui.button("Actualizar ahora", on_click=lambda: _actualizar(disponible["url_instalador"])).props("color=primary dense")
            ui.button("Ahora no", on_click=_descartar).props("flat dense")


def _descartar():
    global _version_descartada
    disponible = _buscar_actualizacion()
    if disponible:
        _version_descartada = disponible["version"]
    aviso_actualizacion.refresh()


async def _actualizar(url_instalador: str):
    ui.notify("Descargando actualizacion...", type="ongoing", timeout=0)
    destino = await run.io_bound(descargar_instalador, url_instalador)
    if destino is None:
        ui.notify("No se pudo descargar la actualizacion. Intenta mas tarde desde 'Actualizar ahora'.", type="negative")
        return
    ui.notify("Actualizacion descargada. La app se va a cerrar para instalarla...", type="positive")
    instalar_y_salir(destino)
