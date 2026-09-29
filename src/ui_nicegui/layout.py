"""Layout compartido (header + menu lateral) para todas las paginas NiceGUI.

A diferencia de la version Streamlit, las 3 paginas de carga de datos (Cargar Cartola, Cargar Deuda
CMF, Registrar Ahorro) van VISIBLES en el menu -- antes estaban escondidas (`visibility="hidden"`) y
solo se llegaba a traves de un boton dentro de un expander en el Dashboard, que fue uno de los puntos
concretos de la evaluacion de diseño ("las acciones de cargar datos estan escondidas").
"""
from contextlib import contextmanager

from nicegui import run, ui

from src import sesion_local
from src.boveda import LARGO_MIN_CONTRASENA, ContrasenaIncorrecta
from src.db import boveda
from src.ui_nicegui.actualizador import aviso_actualizacion
from src.ui_nicegui.theme import alternar_modo, colores, registrar_dark_mode

PAGINAS = [
    ("/", "Inicio", "home"),
    ("/panorama", "Panorama", "pie_chart"),
    ("/dashboard", "Dashboard", "insights"),
    ("/categorias", "Categorias", "sell"),
    ("/cuentas", "Cuentas", "credit_card"),
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
        with ui.row().classes("items-center gap-1"):
            ui.button(icon="key", on_click=_dialogo_cambiar_contrasena).props("flat round").tooltip("Cambiar contraseña")
            ui.button(icon="lock", on_click=_bloquear).props("flat round").tooltip("Bloquear (cifra y oculta tus datos)")
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

    _reportar_actividad()

    with ui.column().classes("w-full max-w-screen-2xl mx-auto p-6 gap-4"):
        aviso_actualizacion()
        _aviso_respaldo_sin_cifrar()
        yield


# Cada interaccion del usuario (mouse, teclado, scroll, toque) avisa al servidor que sigue ahi, como
# maximo una vez cada 20 s para no inundar el websocket. El vigilante de launcher.py bloquea la app si
# pasan 5 minutos sin ningun aviso de ninguna pestaña.
_JS_ACTIVIDAD = """
<script>
(() => {
  let ultimo = 0;
  const avisar = () => {
    const ahora = Date.now();
    if (ahora - ultimo < 20000) return;
    ultimo = ahora;
    try { emitEvent('mfp_actividad'); } catch (e) {}
  };
  ['mousemove', 'mousedown', 'keydown', 'wheel', 'scroll', 'touchstart']
    .forEach(ev => window.addEventListener(ev, avisar, {passive: true, capture: true}));
})();
</script>
"""


def _reportar_actividad():
    ui.add_body_html(_JS_ACTIVIDAD)
    ui.on("mfp_actividad", lambda _: sesion_local.registrar_actividad())


def _bloquear():
    sesion_local.revocar_todo()
    boveda.bloquear()
    ui.navigate.to("/desbloquear")


def _dialogo_cambiar_contrasena():
    with ui.dialog() as dialogo, ui.card().classes("w-96 gap-3"):
        ui.label("Cambiar contraseña").classes("text-lg font-bold")
        actual = ui.input("Contraseña actual", password=True, password_toggle_button=True).classes("w-full")
        nueva1 = ui.input(f"Contraseña nueva (minimo {LARGO_MIN_CONTRASENA} caracteres)", password=True, password_toggle_button=True).classes("w-full")
        nueva2 = ui.input("Repite la contraseña nueva", password=True, password_toggle_button=True).classes("w-full")
        ui.label("Tu codigo de recuperacion sigue siendo el mismo.").style("font-size:12px;opacity:.7")

        async def _cambiar():
            if nueva1.value != nueva2.value:
                ui.notify("Las contraseñas nuevas no coinciden.", type="warning")
                return
            try:
                await run.io_bound(boveda.cambiar_contrasena, actual.value or "", nueva1.value or "")
            except ContrasenaIncorrecta:
                ui.notify("La contraseña actual no es correcta.", type="negative")
                return
            except ValueError as e:
                ui.notify(str(e), type="warning")
                return
            ui.notify("Contraseña cambiada.", type="positive")
            dialogo.close()

        with ui.row().classes("w-full justify-end"):
            ui.button("Cancelar", on_click=dialogo.close).props("flat")
            ui.button("Cambiar", on_click=_cambiar).props("color=primary")
    dialogo.open()


def _aviso_respaldo_sin_cifrar():
    """Despues de migrar, la base original SIN cifrar queda como respaldo por si algo salio mal. Hasta
    que el usuario la elimine, cualquiera con acceso al PC puede leerla, asi que se avisa en cada pagina."""
    if not boveda.hay_respaldo_sin_cifrar():
        return
    c = colores()
    with ui.card().classes("w-full").style(f"border:1px solid {c['danger']};background-color:{c['surface']}") as aviso:
        with ui.row().classes("items-center gap-3 w-full"):
            ui.icon("warning", color=c["danger"])
            ui.label(
                "Quedo una copia SIN cifrar de tus datos de antes de activar el cifrado "
                f"({', '.join(p.name for p in boveda.copias_sin_cifrar())}). Revisa que todo se vea bien y eliminala: "
                "mientras exista, cualquiera con acceso a tu PC puede leerla."
            ).classes("flex-1")

            def _confirmar():
                with ui.dialog() as dlg, ui.card():
                    ui.label("¿Eliminar la copia sin cifrar? Tus datos siguen a salvo en la version cifrada.")
                    with ui.row().classes("w-full justify-end"):
                        ui.button("Cancelar", on_click=dlg.close).props("flat")

                        def _eliminar():
                            boveda.eliminar_respaldo_sin_cifrar()
                            dlg.close()
                            aviso.delete()
                            ui.notify("Copia sin cifrar eliminada.", type="positive")

                        ui.button("Eliminar", on_click=_eliminar).props("color=negative")
                dlg.open()

            ui.button("Eliminar copia sin cifrar", on_click=_confirmar).props("color=negative outline")


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
