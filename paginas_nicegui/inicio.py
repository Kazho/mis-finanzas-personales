"""Pagina de Inicio -- version NiceGUI de `mostrar_inicio()` en app.py (Streamlit).

Mismo contenido/tono que la version Streamlit; lo que cambia es como se arma: menos HTML a mano
(unsafe_allow_html), mas elementos nativos de NiceGUI con estilos via .style()/.classes(), y el
"dato freak" ahora usa @ui.refreshable en vez de session_state + st.rerun para el boton de rotar.
"""
import datetime

from nicegui import ui

from src.ui_nicegui.layout import layout
from src.ui_nicegui.theme import colores

DATOS_FREAK = [
    "La Regla del 72: para saber en cuantos años se duplica tu dinero a una tasa fija, divide 72 por la tasa "
    "anual. A un 6% anual, tu plata se duplica en unos 12 años; a un 12% anual, en 6.",
    "Al interes compuesto se le atribuye (probablemente de forma apocrifa) la frase de que seria 'la octava "
    "maravilla del mundo' — funciona igual de fuerte en tu contra: pagar solo el minimo de una tarjeta de "
    "credito puede significar años pagando una deuda chica por como se acumula el interes rotativo mes a mes.",
    "El interes rotativo de una tarjeta de credito en Chile suele rondar 30-50% anual — mucho mas caro que "
    "cualquier ganancia de una cuenta de ahorro remunerada (que suele rondar 4-10% anual). Pagar el total "
    "facturado, no el minimo, es la decision financiera con mejor 'retorno' garantizado que existe.",
    "Una cuenta corriente comun no genera interes: la plata que dejas ahi quieta 'pierde' contra la inflacion "
    "cada mes. Cualquier cuenta remunerada, aunque sea con una tasa modesta, es mejor que dejarla sin generar nada.",
    "La palabra 'salario' viene del latin 'salarium', ligado a la sal que a veces se usaba para pagar a los "
    "soldados romanos — un producto tan valioso que funcionaba como moneda.",
    "El metodo 50/30/20 sugiere destinar 50% del ingreso a necesidades, 30% a gustos y 20% a ahorro/deuda — "
    "una regla simple para ordenar el presupuesto sin llevar cuentas al detalle.",
]

RECURSOS = [
    ("menu_book", "CMF Educa", "Portal oficial de educacion financiera de la CMF.", "https://www.cmfchile.cl/educa/621/w3-propertyvalue-45232.html"),
    ("credit_card", "SERNAC: Endeudamiento", "Guias del Servicio Nacional del Consumidor.", "https://www.sernac.cl/portal/607/w3-propertyvalue-21055.html"),
    ("check_circle", "Nueve tips para un endeudamiento responsable", "Consejos concretos sobre tarjetas de credito y creditos de consumo.", "https://www.sernac.cl/portal/607/w3-article-3612.html"),
]

_idx_dato_freak = datetime.date.today().toordinal() % len(DATOS_FREAK)


@ui.refreshable
def _tarjeta_dato_freak():
    c = colores()
    with ui.card().classes("w-full").style(f"background-color:{c['surface']};border:1px solid {c['border']}"):
        with ui.row().classes("items-center justify-between w-full"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("lightbulb", color=c["success"])
                ui.label("DATO FREAK SOBRE PLATA").classes("font-bold")
            ui.button(icon="refresh", on_click=_rotar_dato_freak).props("flat round dense").tooltip("Ver otro dato")
        ui.label(DATOS_FREAK[_idx_dato_freak]).style(f"color:{c['text_muted']}")


def _rotar_dato_freak():
    global _idx_dato_freak
    _idx_dato_freak = (_idx_dato_freak + 1) % len(DATOS_FREAK)
    _tarjeta_dato_freak.refresh()


def _tarjeta_acceso_rapido(icono: str, titulo: str, subtitulo: str, destino: str):
    c = colores()
    with ui.card().classes("w-full"):
        with ui.row().classes("items-center gap-3 w-full"):
            with ui.element("div").classes("rounded-full flex items-center justify-center").style(
                f"width:44px;height:44px;background-color:{c['primary']}1a;font-size:20px"
            ):
                ui.label(icono)
            with ui.column().classes("gap-0"):
                ui.label(titulo).classes("font-bold")
                ui.label(subtitulo).style(f"color:{c['text_muted']};font-size:13px")
        ui.button("Ir →", on_click=lambda: ui.navigate.to(destino)).props("outline").classes("w-full mt-2")


@ui.page("/")
def pagina_inicio():
    with layout("/"):
        c = colores()
        ui.label("Mis Finanzas Personales").classes("text-3xl font-bold")

        with ui.card().classes("w-full").style(
            f"background-color:{c['hero_bg']};border-radius:12px;padding:32px 36px"
        ):
            ui.label("Tu plata, bajo control.").style(
                f"font-size:32px;font-weight:600;color:{c['hero_text']};letter-spacing:-0.02em"
            )
            with ui.row().classes("flex-wrap items-baseline gap-1").style(f"max-width:640px"):
                ui.label(
                    "Administra tus finanzas personales de forma simple y segura — tus datos se guardan en"
                ).style(f"color:{c['hero_subtext']};font-size:16px;line-height:1.6")
                ui.label("data/finanzas.db").classes("px-1 rounded font-mono").style(
                    f"background-color:{c['hero_text']}22;color:{c['hero_text']};font-size:14px"
                )
                ui.label(
                    "en tu computador, nunca se suben a ningun servidor. La unica excepcion es el valor del "
                    "dolar (Dashboard > Proyeccion), que se consulta a una API publica para no tener que "
                    "ingresarlo a mano — esa consulta no envia ningun dato tuyo, solo pide el valor del dia."
                ).style(f"color:{c['hero_subtext']};font-size:16px;line-height:1.6")

        with ui.row().classes("w-full gap-4"):
            with ui.column().classes("flex-1 min-w-[240px]"):
                _tarjeta_acceso_rapido("\U0001F4C8", "Ir al Dashboard", "Revisa tu resumen financiero mensual.", "/dashboard")
            with ui.column().classes("flex-1 min-w-[240px]"):
                _tarjeta_acceso_rapido("\U0001F3F7️", "Ver Categorias", "Gestiona y analiza tus gastos por tipo.", "/categorias")

        with ui.row().classes("w-full gap-4 items-start"):
            with ui.column().classes("flex-1 min-w-[280px]"):
                _tarjeta_dato_freak()
            with ui.column().classes("flex-[2] min-w-[280px]"):
                with ui.card().classes("w-full").style(f"background-color:{c['surface']};border:1px solid {c['border']}"):
                    ui.label("Recursos de aprendizaje").classes("font-bold")
                    for icono, titulo, subtitulo, url in RECURSOS:
                        with ui.row().classes("items-start gap-3 w-full"):
                            ui.icon(icono, color=c["text_muted"])
                            with ui.column().classes("gap-0"):
                                ui.link(titulo, url, new_tab=True).classes("font-bold")
                                ui.label(subtitulo).style(f"color:{c['text_muted']};font-size:13px")

        with ui.expansion("Como funciona la deteccion de duplicados").classes("w-full"):
            ui.label(
                "Cada transaccion se identifica por cuenta + fecha + descripcion + montos + saldo, no por el "
                "numero de cartola, asi que puedes cargar el PDF de 'Movimientos al dia' para ver tu saldo antes "
                "de que salga la cartola oficial del mes, y despues cargar la cartola oficial sin que se dupliquen "
                "los movimientos que ya cargaste. Los informes CMF se identifican por su fecha de actualizacion."
            ).style(f"color:{c['text_muted']}")

        ui.separator()
        ui.label(
            "Idea y desarrollo: Javier Ignacio Rivas Poblete. © 2026 Javier Ignacio Rivas Poblete. Todos los "
            "derechos reservados. Aplicacion de uso personal; su uso, adaptacion o distribucion queda bajo la "
            "responsabilidad exclusiva de quien la utilice. Esto no constituye asesoria financiera profesional: "
            "las proyecciones y calculos son estimaciones simples basadas en los datos y tasas que tu mismo "
            "ingresas, no garantias de resultado."
        ).style(f"color:{c['text_muted']};font-size:12px")
