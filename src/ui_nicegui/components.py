"""Componentes chicos reutilizados en varias vistas -- equivalentes NiceGUI de helpers que en la
version Streamlit vivian en src/theme.py (kpi_cards) o eran un st.dataframe/st.container(border=True)
repetido a mano en cada vista."""
import pandas as pd
from nicegui import ui

from src.ui_nicegui.theme import colores


def kpi_cards(items: list[tuple]) -> None:
    """Tarjetas de resumen con borde de color -- mismo diseño que la version Streamlit.

    Cada item es (label, valor, color, icono) o (label, valor, color, icono, delta, delta_ok), donde
    delta_ok=True/False/None pinta el delta verde/rojo/gris."""
    c = colores()
    with ui.row().classes("w-full gap-3 mb-2"):
        for it in items:
            label, valor, color, icono = it[0], it[1], it[2], it[3]
            delta = it[4] if len(it) > 4 else None
            delta_ok = it[5] if len(it) > 5 else None
            with ui.card().classes("flex-1").style(
                f"background-color:{c['surface']};border:1px solid {c['border']};"
                f"border-left:3px solid {color};min-width:190px"
            ):
                ui.label(f"{icono} {label}").style(f"color:{color};font-size:14px")
                ui.label(str(valor)).style(f"color:{c['text']};font-size:26px;font-weight:700;line-height:1.2")
                if delta:
                    delta_color = c["success"] if delta_ok else (c["danger"] if delta_ok is False else c["text_muted"])
                    ui.label(delta).style(f"color:{delta_color};font-size:12px;margin-top:4px")


def tarjeta(titulo: str | None = None):
    """Contenedor con borde -- equivalente a st.container(border=True). Uso: `with tarjeta("X"): ...`"""
    c = colores()
    card = ui.card().classes("w-full")
    card.style(f"background-color:{c['surface']};border:1px solid {c['border']}")
    if titulo:
        with card:
            ui.label(titulo).classes("text-lg font-bold")
    return card


def tabla(df: pd.DataFrame, alias: dict[str, str] | None = None) -> ui.table:
    """Tabla de solo lectura -- equivalente a st.dataframe(df, hide_index=True). `alias` mapea nombre
    de columna -> encabezado visible, igual que column_config en la version Streamlit."""
    alias = alias or {}
    columnas = [
        {"name": col, "label": alias.get(col, col), "field": col, "align": "left", "sortable": True}
        for col in df.columns
    ]
    filas = df.reset_index(drop=True).reset_index().rename(columns={"index": "_fila"}).to_dict("records")
    return ui.table(columns=columnas, rows=filas, row_key="_fila").classes("w-full")


def campo_fecha(valor_inicial: str, etiqueta: str | None = None) -> ui.input:
    """Selector de fecha compacto -- equivalente a st.date_input. `ui.date` por si solo se pinta como
    un calendario grande siempre visible (sirve para un rango en una pagina ancha, no para un campo
    mas de un formulario), asi que se envuelve en un input con el calendario en un menu popup, patron
    estandar de NiceGUI. `.value` del input devuelto es el mismo string ISO (YYYY-MM-DD) que ui.date
    usa directamente, asi que se lee igual en el resto del codigo (datetime.date.fromisoformat(...))."""
    campo = ui.input(etiqueta, value=valor_inicial)
    with campo.add_slot("append"):
        icono = ui.icon("edit_calendar").classes("cursor-pointer")
    with ui.menu() as menu:
        ui.date(value=valor_inicial).bind_value(campo)
    icono.on("click", menu.open)
    return campo


def texto_muted(texto: str) -> ui.label:
    """Equivalente a st.caption -- texto secundario, mismo color en ambos temas."""
    c = colores()
    return ui.label(texto).style(f"color:{c['text_muted']};font-size:13px;line-height:1.5")


_ICONOS_BANNER = {"success": "check_circle", "warning": "warning", "error": "error", "info": "info"}


def banner(tipo: str, texto: str) -> None:
    """Equivalente a st.success/warning/error/info -- banner de ancho completo con icono y borde de
    color segun el tipo. `texto` admite **negrita** estilo markdown (se convierte a <b>)."""
    c = colores()
    color = {"success": c["success"], "warning": c["accent_orange"], "error": c["danger"], "info": c["accent_blue"]}[tipo]
    partes = texto.split("**")
    html = "".join(f"<b>{p}</b>" if i % 2 else p for i, p in enumerate(partes))
    with ui.row().classes("w-full items-start gap-2 rounded p-3").style(
        f"background-color:{color}1a;border-left:3px solid {color}"
    ):
        ui.icon(_ICONOS_BANNER[tipo], color=color)
        ui.html(html).style(f"color:{c['text']};font-size:14px;line-height:1.5")
