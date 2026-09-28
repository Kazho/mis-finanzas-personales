"""Pantalla de acceso: crear la boveda cifrada (primera vez o migracion desde la base sin cifrar),
desbloquearla con la contraseña, o recuperarla con el codigo de recuperacion.

Mientras la boveda esta bloqueada, el middleware de launcher.py redirige cualquier otra pagina aca.
Las operaciones de scrypt/cifrado se corren con run.io_bound para no congelar la interfaz."""
from nicegui import run, ui

from src.boveda import LARGO_MIN_CONTRASENA, ArchivoDanado, ContrasenaIncorrecta
from src import sesion_local
from src.db import boveda, init_db
from src.categorias import asegurar_buckets_default, asegurar_reglas_default
from src.ui_nicegui.theme import colores


def _entrar() -> None:
    """Pasa por /_activar para que este navegador reciba su cookie de sesion (ver src/sesion_local.py).
    El codigo se emite recien aca porque vive solo 30 segundos."""
    ui.navigate.to(f"/_activar?c={sesion_local.emitir_codigo()}")


def preparar_base() -> None:
    """Lo que antes corria al arrancar la app: esquema, migraciones y datos por defecto. Ahora corre
    recien al desbloquear, porque antes de eso la base no se puede leer."""
    init_db()
    asegurar_reglas_default()
    asegurar_buckets_default()


def _campo_contrasena(etiqueta: str) -> ui.input:
    return ui.input(etiqueta, password=True, password_toggle_button=True).classes("w-full")


def _tarjeta_centrada():
    c = colores()
    ui.query("body").style(f"background-color:{c['bg']}")
    with ui.column().classes("w-full items-center p-6"):
        card = ui.card().classes("w-full max-w-md gap-3 p-6").style(
            f"background-color:{c['surface']};border:1px solid {c['border']}"
        )
    with card:
        with ui.row().classes("items-center gap-2"):
            ui.icon("lock", color=c["primary"], size="28px")
            ui.label("Mis Finanzas Personales").classes("text-xl font-bold")
    return card


def _mostrar_codigo(contenedor, codigo: str):
    c = colores()
    contenedor.clear()
    with contenedor:
        ui.label("Guarda tu codigo de recuperacion").classes("text-lg font-bold")
        ui.label(
            "Es la UNICA forma de entrar si olvidas tu contraseña. No se guarda en ningun lado y no se "
            "vuelve a mostrar: anotalo en papel o en tu gestor de contraseñas."
        ).style(f"color:{c['text_muted']};font-size:13px")
        ui.label(codigo).classes("text-xl font-mono font-bold text-center w-full p-3 rounded").style(
            f"background-color:{c['bg']};letter-spacing:1px"
        )
        ui.button("Copiar codigo", icon="content_copy", on_click=lambda: (ui.clipboard.write(codigo), ui.notify("Codigo copiado."))).props("outline")
        confirmado = ui.checkbox("Guarde mi codigo de recuperacion en un lugar seguro")
        continuar = ui.button("Entrar a la app", on_click=_entrar).props("color=primary").classes("w-full")
        continuar.bind_enabled_from(confirmado, "value")


def _form_crear(card):
    c = colores()
    with card:
        contenedor = ui.column().classes("w-full gap-3")
    with contenedor:
        ui.label("Protege tus datos").classes("text-lg font-bold")
        if boveda.hay_base_sin_cifrar():
            texto = ("Tus datos se van a cifrar con una contraseña que solo tu conoces. Sin ella (o sin el "
                     "codigo de recuperacion que te daremos) nadie puede leerlos, ni siquiera nosotros.")
        else:
            texto = ("Crea una contraseña para cifrar tus datos. Sin ella (o sin el codigo de recuperacion "
                     "que te daremos) nadie puede leerlos, ni siquiera nosotros.")
        ui.label(texto).style(f"color:{c['text_muted']};font-size:13px")
        pw1 = _campo_contrasena(f"Contraseña (minimo {LARGO_MIN_CONTRASENA} caracteres)")
        pw2 = _campo_contrasena("Repite la contraseña")
        boton = ui.button("Cifrar y continuar", icon="lock").props("color=primary").classes("w-full")

    async def _crear():
        if pw1.value != pw2.value:
            ui.notify("Las contraseñas no coinciden.", type="warning")
            return
        boton.disable()
        try:
            codigo = await run.io_bound(boveda.crear, pw1.value or "")
            await run.io_bound(preparar_base)
        except ValueError as e:
            ui.notify(str(e), type="warning")
            boton.enable()
            return
        _mostrar_codigo(contenedor, codigo)

    boton.on_click(_crear)
    pw2.on("keydown.enter", _crear)


def _form_desbloquear(card):
    c = colores()
    with card:
        ui.label("Ingresa tu contraseña para desbloquear tus datos.").style(f"color:{c['text_muted']};font-size:13px")
        pw = _campo_contrasena("Contraseña")
        boton = ui.button("Desbloquear", icon="lock_open").props("color=primary").classes("w-full")
        olvide = ui.button("Olvide mi contraseña").props("flat dense no-caps")
        recuperar = ui.column().classes("w-full gap-3")
        recuperar.visible = False
        with recuperar:
            ui.label("Recuperar con tu codigo").classes("font-bold")
            codigo_input = ui.input("Codigo de recuperacion (XXXX-XXXX-...)").classes("w-full")
            nueva1 = _campo_contrasena(f"Contraseña nueva (minimo {LARGO_MIN_CONTRASENA} caracteres)")
            nueva2 = _campo_contrasena("Repite la contraseña nueva")
            boton_rec = ui.button("Recuperar y fijar contraseña nueva").props("color=primary outline").classes("w-full")

    async def _desbloquear():
        boton.disable()
        try:
            await run.io_bound(boveda.desbloquear, pw.value or "")
            await run.io_bound(preparar_base)
        except ContrasenaIncorrecta:
            ui.notify("Contraseña incorrecta.", type="negative")
            boton.enable()
            return
        except ArchivoDanado as e:
            ui.notify(f"{e} Puedes restaurar un respaldo de la carpeta 'respaldos'.", type="negative", multi_line=True)
            boton.enable()
            return
        _entrar()

    async def _recuperar():
        if nueva1.value != nueva2.value:
            ui.notify("Las contraseñas nuevas no coinciden.", type="warning")
            return
        boton_rec.disable()
        try:
            await run.io_bound(boveda.recuperar, codigo_input.value or "", nueva1.value or "")
            await run.io_bound(preparar_base)
        except ContrasenaIncorrecta:
            ui.notify("El codigo de recuperacion no es correcto.", type="negative")
            boton_rec.enable()
            return
        except ValueError as e:
            ui.notify(str(e), type="warning")
            boton_rec.enable()
            return
        ui.notify("Listo: tu contraseña nueva quedo activa.", type="positive")
        _entrar()

    boton.on_click(_desbloquear)
    pw.on("keydown.enter", _desbloquear)
    olvide.on_click(lambda: setattr(recuperar, "visible", not recuperar.visible))
    boton_rec.on_click(_recuperar)


@ui.page("/desbloquear")
def pagina_desbloquear():
    # Aunque la boveda ya este desbloqueada (por otro navegador) se pide la contraseña: cada navegador
    # necesita su propia sesion, si no cualquier programa del PC podria entrar sin ella.
    card = _tarjeta_centrada()
    if boveda.existe():
        _form_desbloquear(card)
    else:
        _form_crear(card)
