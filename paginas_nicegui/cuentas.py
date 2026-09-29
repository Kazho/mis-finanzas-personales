"""Cuentas -- ordena todas tus cuentas: ponles nombre propio, corrige el tipo y la moneda, o archiva las que
ya no usas.

Las cuentas se crean solas al cargar la primera cartola de cada una, con el tipo que detecta el parser. Aca
se corrigen si el tipo detectado no era el correcto. Archivar una cuenta la saca del Panorama y de los
saldos, pero conserva sus movimientos para el historial de gastos."""
from nicegui import ui

from src.cuentas import MONEDAS, TIPOS, actualizar_cuenta, listar_cuentas, nombre_visible
from src.formato import monto
from src.ui_nicegui.components import banner, tarjeta, texto_muted
from src.ui_nicegui.layout import layout
from src.ui_nicegui.theme import colores


def _dialogo_editar(cuenta: dict, al_guardar):
    with ui.dialog() as dialogo, ui.card().classes("w-[28rem] gap-3"):
        ui.label(f"Editar cuenta: {cuenta['nombre']}").classes("text-lg font-bold")
        alias = ui.input("Nombre propio (opcional)", value=cuenta.get("alias") or "").classes("w-full")
        banco = ui.input("Banco", value=cuenta.get("banco") or "").classes("w-full")
        tipo = ui.select({k: v for k, v in TIPOS.items()}, value=cuenta["tipo"], label="Tipo de cuenta").classes("w-full")
        moneda = ui.select(list(MONEDAS), value=cuenta.get("moneda") or "CLP", label="Moneda").classes("w-full")
        archivada = ui.checkbox("Archivada (no aparece en el Panorama ni en los saldos)", value=bool(cuenta.get("archivada")))
        texto_muted(
            "Cambiar la moneda no convierte los montos ya cargados: solo cambia como se interpretan. Corrigela si el "
            "parser la detecto mal, no para pasar una cuenta de una moneda a otra."
        )

        def _guardar():
            actualizar_cuenta(
                cuenta["id"], alias=alias.value, banco=banco.value, tipo=tipo.value, moneda=moneda.value,
                archivada=archivada.value,
            )
            dialogo.close()
            ui.notify("Cuenta actualizada.", type="positive")
            al_guardar()

        with ui.row().classes("w-full justify-end"):
            ui.button("Cancelar", on_click=dialogo.close).props("flat")
            ui.button("Guardar", on_click=_guardar).props("color=primary")
    dialogo.open()


@ui.refreshable
def _lista_cuentas():
    c = colores()
    cuentas = listar_cuentas()
    if not cuentas:
        ui.label("Aun no hay cuentas. Se crean solas al cargar la primera cartola en 'Cargar Cartola'.")
        return

    activas = [x for x in cuentas if not x["archivada"]]
    archivadas = [x for x in cuentas if x["archivada"]]

    def _fila(x: dict):
        moneda = x.get("moneda") or "CLP"
        with ui.row().classes("items-center gap-3 w-full py-1").style(f"border-bottom:1px solid {c['border']}"):
            with ui.column().classes("gap-0 flex-1 min-w-[220px]"):
                ui.label(nombre_visible(x)).classes("font-bold")
                if x.get("alias"):
                    ui.label(x["nombre"]).style(f"color:{c['text_muted']};font-size:12px")
            ui.label(x.get("banco") or "Sin banco").classes("min-w-[110px]")
            ui.label(TIPOS.get(x["tipo"], x["tipo"])).classes("min-w-[140px]")
            ui.label(moneda).classes("min-w-[50px]")
            ui.label(f"{x['n_movimientos']} mov.").classes("min-w-[80px]").style(f"color:{c['text_muted']}")
            if x["tipo"] != "tarjeta":
                ui.label(monto(x["saldo"], moneda) if x["saldo"] is not None else "sin saldo").classes("min-w-[130px]")
            ui.button(icon="edit", on_click=lambda x=x: _dialogo_editar(x, _lista_cuentas.refresh)).props("flat round dense").tooltip("Editar")

    with tarjeta(f"Cuentas activas ({len(activas)})"):
        if not activas:
            texto_muted("No tienes cuentas activas.")
        for x in activas:
            _fila(x)

    if archivadas:
        with ui.expansion(f"Archivadas ({len(archivadas)})").classes("w-full"):
            for x in archivadas:
                _fila(x)


@ui.page("/cuentas")
def pagina_cuentas():
    with layout("/cuentas"):
        ui.label("Cuentas").classes("text-2xl font-bold")
        texto_muted(
            "Todas tus cuentas y tarjetas, de todos los bancos. Se crean solas al cargar cartolas; aca les pones un "
            "nombre propio, corriges el tipo (corriente, vista, ahorro, inversion, tarjeta) y la moneda, o archivas las "
            "que ya no usas."
        )
        banner(
            "info",
            "El **tipo** decide como se cuenta cada cuenta en el Panorama: corriente, vista y ahorro son plata "
            "disponible; inversion es patrimonio; tarjeta de credito es deuda, no plata tuya.",
        )
        _lista_cuentas()
