"""Sistema de tema claro/oscuro compartido por toda la app.

El modo claro ("Lumina Finance", diseñado en Stitch) es el tema NATIVO de
Streamlit (ver .streamlit/config.toml) — asi los widgets nativos (botones,
inputs, tablas, selects, calendarios) salen bien gratis, sin tener que forzar
cada uno por CSS. El modo oscuro es una capa de CSS que se activa con el boton
de la barra lateral y se guarda en session_state (compartido entre todas las
paginas); como Streamlit no soporta cambiar de tema nativo en caliente, el
oscuro se logra sobreescribiendo por CSS los mismos contenedores que ya se
vienen personalizando en la app (fondo, sidebar, tabs, tarjetas).
"""
import streamlit as st

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


def es_oscuro() -> bool:
    return st.session_state.get("modo_oscuro", False)


def colores() -> dict:
    return DARK if es_oscuro() else LIGHT


def boton_modo():
    """Boton en la barra lateral para cambiar entre modo claro y oscuro."""
    with st.sidebar:
        st.divider()
        texto = "☀️ Cambiar a modo claro" if es_oscuro() else "\U0001F319 Cambiar a modo oscuro"
        if st.button(texto, use_container_width=True, key="boton_modo_oscuro"):
            st.session_state.modo_oscuro = not es_oscuro()
            st.rerun()


def inject_css():
    """CSS base compartido: sidebar mas angosto y con seccion activa marcada, y en modo
    oscuro ademas se fuerza fondo/texto/tarjetas. Llamar una vez al principio de cada pagina
    (despues de boton_modo())."""
    c = colores()

    st.markdown(
        f"""
        <style>
        [data-testid="stSidebar"] {{ min-width: 230px !important; max-width: 230px !important; }}
        [data-testid="stSidebarNavLink"] {{ border-radius: 8px; margin: 2px 10px; padding: 6px 10px !important; }}
        [data-testid="stSidebarNavLink"]:hover {{ background-color: {c["primary"]}1a; }}
        [data-testid="stSidebarNavLink"][aria-current="page"] {{
            background-color: {c["primary"]}22;
            border-left: 3px solid {c["primary"]};
        }}
        [data-testid="stSidebarNavLink"][aria-current="page"] span {{
            font-weight: 700 !important;
            color: {c["primary"]} !important;
        }}
        [data-testid="stExpander"] {{
            border: 1px solid {c["primary"]};
            border-radius: 10px;
            background-color: {c["primary"]}0d;
        }}
        [data-testid="stExpander"] summary {{ font-size: 18px; font-weight: 700; color: {c["primary"]}; }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    # El ancho del sidebar lo controla Streamlit con estilos en linea que ganan sobre el CSS
    # de arriba, asi que se fuerza por JS (via onerror, el truco de siempre para correr script
    # desde st.markdown ya que las etiquetas <script> insertadas asi no se ejecutan solas).
    st.markdown(
        '<img src="x" alt="" style="display:none" onerror="'
        "var s=document.querySelector('[data-testid=\\'stSidebar\\']');"
        "if(s){s.style.setProperty('width','230px','important');"
        "s.style.setProperty('min-width','230px','important');"
        "s.style.setProperty('max-width','230px','important');}"
        'this.remove();">',
        unsafe_allow_html=True,
    )

    if not es_oscuro():
        return

    st.markdown(
        f"""
        <style>
        [data-testid="stAppViewContainer"], [data-testid="stMain"], .stApp, [data-testid="stBottomBlockContainer"] {{
            background-color: {c["bg"]} !important;
        }}
        [data-testid="stHeader"] {{ background-color: {c["bg"]} !important; }}
        [data-testid="stSidebar"] {{ background-color: {c["surface"]} !important; }}
        [data-testid="stSidebarNavLink"] span {{ color: {c["text"]} !important; }}
        [data-testid="stSidebarNavLink"][aria-current="page"] span {{ color: {c["primary"]} !important; }}
        h1, h2, h3, h4, h5, p, span, label, li, a, .stMarkdown,
        [data-testid="stMetricLabel"], [data-testid="stMetricValue"], [data-testid="stMetricDelta"],
        [data-testid="stCaptionContainer"], [data-testid="stWidgetLabel"] {{
            color: {c["text"]} !important;
        }}
        [data-testid="stExpander"] {{ background-color: {c["surface"]} !important; }}
        [data-testid="stDataFrame"] {{ background-color: {c["surface"]} !important; }}
        .stButton button, .stDownloadButton button {{
            background-color: {c["surface"]} !important;
            color: {c["text"]} !important;
            border-color: {c["border"]} !important;
        }}
        [data-baseweb="input"], [data-baseweb="select"], [data-baseweb="textarea"],
        [data-baseweb="datepicker"], input, textarea {{
            background-color: {c["surface"]} !important;
            color: {c["text"]} !important;
            border-color: {c["border"]} !important;
        }}
        [data-testid="stMetricDelta"] svg {{ display: inline; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def tema_plotly(fig, color=None):
    """Aplica el tema (claro u oscuro) a un grafico Plotly."""
    c = colores()
    fig.update_layout(
        template="plotly_dark" if es_oscuro() else "plotly_white",
        paper_bgcolor=c["surface"],
        plot_bgcolor=c["surface"],
        font_color=c["text"],
        margin=dict(t=40, l=10, r=10, b=10),
    )
    if color:
        fig.update_traces(marker_color=color)
    return fig


def kpi_cards(items):
    """Tarjetas de resumen con borde de color, en vez de numeros sueltos flotando.
    Cada item es (label, valor, color, icono) o (label, valor, color, icono, delta, delta_ok),
    donde delta_ok=True/False/None pinta el delta verde/rojo/gris (igual que st.metric)."""
    c = colores()
    tarjetas = []
    for it in items:
        label, valor, color, icono = it[0], it[1], it[2], it[3]
        delta = it[4] if len(it) > 4 else None
        delta_ok = it[5] if len(it) > 5 else None
        delta_html = ""
        if delta:
            delta_color = c["success"] if delta_ok else (c["danger"] if delta_ok is False else c["text_muted"])
            delta_html = f'<div style="font-size:clamp(12px,1vw,14px);color:{delta_color};margin-top:4px">{delta}</div>'
        tarjetas.append(
            f'<div style="background:{c["surface"]};border:1px solid {c["border"]};border-left:3px solid {color};'
            f'border-radius:10px;padding:clamp(14px,1.6vw,20px) clamp(16px,1.8vw,22px);flex:1;min-width:190px">'
            f'<div style="font-size:clamp(13px,1.1vw,15px);color:{color};margin-bottom:6px">{icono} {label}</div>'
            f'<div style="font-size:clamp(22px,2.6vw,32px);font-weight:700;color:{c["text"]};line-height:1.2">{valor}</div>'
            f"{delta_html}</div>"
        )
    st.markdown(
        '<div style="display:flex;gap:14px;flex-wrap:wrap;margin-bottom:12px">' + "".join(tarjetas) + "</div>",
        unsafe_allow_html=True,
    )
