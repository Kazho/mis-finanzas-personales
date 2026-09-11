"""Layout compartido (header + menu lateral) para todas las paginas NiceGUI.

A diferencia de la version Streamlit, las 3 paginas de carga de datos (Cargar Cartola, Cargar Deuda
CMF, Registrar Ahorro) van VISIBLES en el menu -- antes estaban escondidas (`visibility="hidden"`) y
solo se llegaba a traves de un boton dentro de un expander en el Dashboard, que fue uno de los puntos
concretos de la evaluacion de diseño ("las acciones de cargar datos estan escondidas").
"""
from contextlib import contextmanager

from nicegui import ui

from src.ui_nicegui.actualizador import aviso_actualizacion
from src.ui_nicegui.theme import alternar_modo, colores, registrar_dark_mode

PAGINAS = [
    ("/", "Inicio", "home"),
    ("/dashboard", "Dashboard", "insights"),
    ("/categorias", "Categorias", "sell"),
    ("/cargar-cartola", "Cargar Cartola", "description"),
    ("/cargar-deuda-cmf", "Cargar Deuda CMF", "account_balance"),
    ("/registrar-ahorro", "Registrar Ahorro", "savings"),
]


@contextmanager
def layout(ruta_activa: str):
    """Envuelve el contenido de una pagina con el header y el menu lateral compartidos.

    Uso: `with layout('/'): ...contenido de la pagina...`
    """
    dark = ui.dark_mode()
    registrar_dark_mode(dark)
    c = colores()

    ui.query("body").style(f"background-color:{c['bg']}")

    with ui.header().classes("items-center justify-between px-4").style(
        f"background-color:{c['surface']};color:{c['text']}"
    ):
        with ui.row().classes("items-center gap-2"):
            ui.icon("account_balance_wallet", color=c["primary"])
            ui.label("Mis Finanzas Personales").classes("text-lg font-bold")
        ui.button(
            icon="dark_mode" if not dark.value else "light_mode",
            on_click=lambda: (alternar_modo(), ui.navigate.reload()),
        ).props("flat round").tooltip("Cambiar modo claro/oscuro")

    with ui.left_drawer(value=True).classes("q-pa-md gap-1").style(
        f"background-color:{c['surface']}"
    ):
        for ruta, titulo, icono in PAGINAS:
            activa = ruta == ruta_activa
            with ui.row().classes(
                "items-center gap-3 w-full rounded-lg px-3 py-2 cursor-pointer"
                + (" font-bold" if activa else "")
            ).style(
                (f"background-color:{c['primary']}22;border-left:3px solid {c['primary']}" if activa else "")
            ).on("click", lambda r=ruta: ui.navigate.to(r)):
                ui.icon(icono, color=c["primary"] if activa else c["text_muted"])
                ui.label(titulo).style(f"color:{c['primary'] if activa else c['text']}")

    with ui.column().classes("w-full max-w-5xl mx-auto p-6 gap-4"):
        aviso_actualizacion()
        yield


def pagina_placeholder(ruta: str, titulo: str):
    """Pagina 'Proximamente' para las rutas todavia no portadas -- asi el menu nuevo no rompe nada
    mientras se migra el resto de las vistas (fases siguientes del plan)."""
    with layout(ruta):
        c = colores()
        ui.label(titulo).classes("text-2xl font-bold")
        with ui.card().classes("w-full items-center p-10").style(f"background-color:{c['surface']}"):
            ui.icon("construction", size="48px", color=c["text_muted"])
            ui.label("Proximamente en la version nueva -- por ahora, usa la app actual.").style(
                f"color:{c['text_muted']}"
            )
