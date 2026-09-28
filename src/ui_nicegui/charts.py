"""Wrapper de Plotly para NiceGUI -- reemplazo directo de src.theme.tema_plotly + st.plotly_chart.

El codigo que arma las figuras (px.bar/px.pie/px.line en las vistas) no cambia nada al portar: solo
cambia como se pintan (ui.plotly en vez de st.plotly_chart) y como se tematizan (esta funcion en vez
de src.theme.tema_plotly, que depende de st.session_state y no sirve fuera de una sesion Streamlit).
"""
from nicegui import ui

from src.ui_nicegui.theme import colores, es_oscuro, PALETTE


def tema_plotly(fig, color: str | None = None, colorear: bool = True):
    """Aplica el tema claro/oscuro y el color(es) del grafico.

    - Si se pasa `color`, se fuerza ese color unico en todo el grafico (para series de una sola
      linea/tendencia donde el color tiene un significado propio, ej. la deuda en rojo).
    - Si `colorear=False`, no se toca ningun color -- para graficos que ya vienen con su propio
      `color_discrete_map` semantico (ej. Necesidad/Gusto/Ahorro de la regla 50/30/20), donde
      recolorear por orden de traza pisaria ese significado.
    - En cualquier otro caso, se pinta con PALETTE: cada barra/porcion/linea (una por categoria o
      cuenta) recibe un color distinto en vez de que todo el grafico salga de un solo color plano --
      reemplaza tambien la paleta por defecto de Plotly por la de la app.
    """
    c = colores()
    fig.update_layout(
        template="plotly_dark" if es_oscuro() else "plotly_white",
        paper_bgcolor=c["surface"],
        plot_bgcolor=c["surface"],
        font_color=c["text"],
        margin=dict(t=40, l=10, r=10, b=10),
    )
    if color:
        fig.update_traces(marker_color=color, line_color=color)
    elif not colorear:
        pass
    elif len(fig.data) == 1 and fig.data[0].type == "pie":
        n = len(fig.data[0].labels) if fig.data[0].labels is not None else 0
        fig.data[0].marker.colors = [PALETTE[i % len(PALETTE)] for i in range(n)]
    elif len(fig.data) == 1 and fig.data[0].type == "bar":
        n = len(fig.data[0].x) if fig.data[0].x is not None else 0
        fig.data[0].marker.color = [PALETTE[i % len(PALETTE)] for i in range(n)]
    elif len(fig.data) == 1:
        # Una sola serie (ej. una linea de una sola cuenta): un color de la paleta en vez del
        # color plano (casi negro) que Plotly asigna por defecto cuando solo hay una categoria.
        # Solo las trazas de tipo scatter tienen atributo `line` (Bar no lo tiene y tirarlo da
        # AttributeError, no None).
        fig.data[0].marker.color = PALETTE[0]
        if fig.data[0].type == "scatter":
            fig.data[0].line.color = PALETTE[0]
    else:
        for i, trace in enumerate(fig.data):
            trace.marker.color = PALETTE[i % len(PALETTE)]
            if trace.type == "scatter":
                trace.line.color = PALETTE[i % len(PALETTE)]
    return fig


def plotly_chart(fig, color: str | None = None, colorear: bool = True) -> ui.plotly:
    """Aplica el tema y pinta la figura. Uso: plotly_chart(px.bar(df, ...))"""
    tema_plotly(fig, color, colorear)
    return ui.plotly(fig).classes("w-full")
