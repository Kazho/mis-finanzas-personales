import calendar
import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from src.db import get_conn, init_db, obtener_tipos_cuenta, obtener_config_tarjeta, guardar_config_tarjeta
from src.fx import obtener_valor_dolar
from src.proyeccion import (
    listar_config,
    calcular_ganancia_anual,
    ganancia_periodo,
    tasa_efectiva,
    optimizar_asignacion,
    evaluar_plan_con_costo,
    proyectar_saldo,
    meses_entre,
    simular_dap,
)
from src.formato import clp, clp_md
from src.analisis_gastos import (
    comparacion_mes_actual,
    comparacion_por_categoria,
    alertas_categoria,
    logros_ahorro,
    es_categoria_ahorro,
    es_categoria_ingreso,
    ahorro_por_mes,
)
from src.metas import listar_metas, calcular_progresos, ritmo_mensual_cuenta
from src.theme import colores, tema_plotly as tema, kpi_cards

init_db()
# boton_modo() e inject_css() ya se llaman una vez en app.py antes de nav.run(), que
# ejecuta el codigo de esta pagina — llamarlos de nuevo aqui duplicaria la key del boton.

# Un color de acento distinto por seccion (Gastos/Ahorros/Proyeccion/Deuda), reutilizado en
# las pestañas, las tarjetas KPI y el tema de cada grafico, para que se note de un vistazo
# en que parte de la app estas (pedido del usuario: mas orden y colores que llamen la atencion).
_c = colores()
COLOR_GASTOS = _c["accent_orange"]
COLOR_AHORROS = _c["success"]
COLOR_PROYECCION = _c["accent_blue"]
COLOR_DEUDA = _c["danger"]
COLOR_PATRIMONIO = _c["accent_purple"]


def _proxima_fecha_dia(dia: int, desde: datetime.date) -> datetime.date:
    """Proxima fecha (a partir de 'desde' inclusive) que caiga en el dia del mes indicado."""
    ultimo_dia_mes = calendar.monthrange(desde.year, desde.month)[1]
    candidata = desde.replace(day=min(dia, ultimo_dia_mes))
    if candidata < desde:
        mes, anio = (desde.month % 12) + 1, desde.year + (1 if desde.month == 12 else 0)
        candidata = datetime.date(anio, mes, min(dia, calendar.monthrange(anio, mes)[1]))
    return candidata


def _colores_tarjeta(tipo: str) -> tuple[str, str, str]:
    """(bg, fg, chip) segun el nivel de la tarjeta: negro para Infinite/Signature/Black, plata
    para Platinum, dorada para Dorada."""
    tipo_u = tipo.upper()
    if "INFINITE" in tipo_u or "BLACK" in tipo_u:
        return "#0a0a0a", "#e5e5e5", "#c9a227"
    if "PLATINUM" in tipo_u:
        return "#54585f", "#f5f5f6", "#e5e7eb"
    if "DORADA" in tipo_u:
        return "#8a6d1f", "#fff8e1", "#f0d060"
    return "#1a1a1a", "#e5e5e5", "#9ca3af"


def _banner_tarjeta_credito(tipo: str, texto_color: str) -> str:
    """Banner chico con un icono de tarjeta — el color de fondo de toda la seccion ya se aplica
    aparte via CSS (.st-key-card_gastos_tarjeta), asi que este banner solo aporta el borde/icono."""
    bg, fg, chip = _colores_tarjeta(tipo)
    marca = "VISA" if "VISA" in tipo.upper() else ("MASTERCARD" if "MASTERCARD" in tipo.upper() else "")
    svg = (
        f'<svg width="40" height="26" viewBox="0 0 40 26" xmlns="http://www.w3.org/2000/svg" style="flex-shrink:0">'
        f'<rect width="40" height="26" rx="5" fill="{bg}"></rect>'
        f'<rect x="5" y="6" width="9" height="6" rx="1.3" fill="{chip}"></rect>'
        f'<rect x="5" y="17" width="30" height="3.5" rx="1.75" fill="{fg}" opacity="0.6"></rect>'
        "</svg>"
    )
    return (
        f'<div style="background:{bg}26;border:1px solid {bg}55;border-radius:10px;padding:10px 14px;'
        f'display:flex;align-items:center;gap:10px;margin-bottom:10px">'
        + svg
        + f'<div><div style="color:{texto_color};font-weight:700;font-size:15px">Configuracion de tu tarjeta</div>'
        f'<div style="color:{texto_color};opacity:0.7;font-size:12px">{tipo}{" · " + marca if marca else ""}</div></div>'
        "</div>"
    )


# Tasas de acumulacion de Dolares Premio de Banco de Chile (compras nacionales), segun tipo de tarjeta.
TASAS_DOLARES_PREMIO = {
    "Visa Infinite": 0.8,
    "Visa Signature / Mastercard Black": 0.7,
    "Visa Platinum / Platinum Pyme / Mastercard Platinum": 0.6,
    "Visa Dorada, Internacional o FAN / Visa ChilePyme / Mastercard Dorada": 0.5,
}

st.title("Dashboard Financiero")

# Las pestañas quedan mas grandes, "pegadas" arriba al hacer scroll, y cada una toma el
# color de su seccion cuando esta activa.
st.markdown(
    f"""
    <style>
    [data-testid="stTabs"] [role="tablist"] {{
        position: sticky;
        top: 0;
        z-index: 999;
        background-color: {_c["bg"]};
        gap: 12px;
        padding-top: 10px;
        padding-bottom: 6px;
        border-bottom: 1px solid {_c["border"]};
    }}
    [data-testid="stTabs"] [data-testid="stTab"] {{
        height: 56px;
        padding: 0 24px;
        display: flex;
        align-items: center;
    }}
    [data-testid="stTabs"] [data-testid="stTab"] {{
        border-radius: 8px 8px 0 0;
    }}
    [data-testid="stTabs"] [data-testid="stTab"] p {{
        font-size: 20px;
        font-weight: 700;
        color: {_c["text_muted"]};
    }}
    [data-testid="stTabs"] [data-testid="stTab"][aria-selected="true"] p {{
        color: {_c["text"]};
    }}
    [data-testid="stTabs"] [data-testid="stTab"]:nth-child(1)[aria-selected="true"] {{ background-color: {COLOR_GASTOS}26; border-bottom: 3px solid {COLOR_GASTOS}; }}
    [data-testid="stTabs"] [data-testid="stTab"]:nth-child(1)[aria-selected="true"] p {{ color: {COLOR_GASTOS}; }}
    [data-testid="stTabs"] [data-testid="stTab"]:nth-child(2)[aria-selected="true"] {{ background-color: {COLOR_AHORROS}26; border-bottom: 3px solid {COLOR_AHORROS}; }}
    [data-testid="stTabs"] [data-testid="stTab"]:nth-child(2)[aria-selected="true"] p {{ color: {COLOR_AHORROS}; }}
    [data-testid="stTabs"] [data-testid="stTab"]:nth-child(3)[aria-selected="true"] {{ background-color: {COLOR_PROYECCION}26; border-bottom: 3px solid {COLOR_PROYECCION}; }}
    [data-testid="stTabs"] [data-testid="stTab"]:nth-child(3)[aria-selected="true"] p {{ color: {COLOR_PROYECCION}; }}
    [data-testid="stTabs"] [data-testid="stTab"]:nth-child(4)[aria-selected="true"] {{ background-color: {COLOR_DEUDA}26; border-bottom: 3px solid {COLOR_DEUDA}; }}
    [data-testid="stTabs"] [data-testid="stTab"]:nth-child(4)[aria-selected="true"] p {{ color: {COLOR_DEUDA}; }}
    .st-key-kpi_saldo, .st-key-kpi_ahorros, .st-key-kpi_proyeccion, .st-key-kpi_deuda {{
        border-radius: 10px !important;
    }}
    .st-key-card_gastos {{ border-color: {COLOR_GASTOS}55 !important; }}
    .st-key-card_ahorros {{ border-color: {COLOR_AHORROS}55 !important; }}
    .st-key-card_proyeccion {{ border-color: {COLOR_PROYECCION}55 !important; }}
    .st-key-card_deuda {{ border-color: {COLOR_DEUDA}55 !important; }}
    </style>
    """,
    unsafe_allow_html=True,
)

with st.expander("\U0001F504 Actualizar datos — carga tu ultima cartola, deuda CMF o ahorro", expanded=False):
    au1, au2, au3 = st.columns(3)
    if au1.button("\U0001F4C4 Cargar Cartola", use_container_width=True):
        st.switch_page("vistas/1_Cargar_Cartola.py")
    if au2.button("\U0001F4CA Cargar Deuda CMF", use_container_width=True):
        st.switch_page("vistas/2_Cargar_Deuda_CMF.py")
    if au3.button("\U0001F4B5 Registrar Ahorro", use_container_width=True):
        st.switch_page("vistas/3_Registrar_Ahorro.py")

with get_conn() as conn:
    df_trans = pd.read_sql_query(
        """
        SELECT t.id, t.fecha, t.descripcion, t.sucursal, t.monto_cargo, t.monto_abono, t.saldo, t.categoria, c.nombre AS cuenta
        FROM transacciones t JOIN cuentas c ON c.id = t.cuenta_id
        ORDER BY t.fecha, t.id
        """,
        conn,
    )
    df_deuda = pd.read_sql_query(
        "SELECT fecha_informe, fecha_actualizacion, deuda_total FROM deuda_cmf_informes ORDER BY fecha_actualizacion",
        conn,
    )
    df_ahorros = pd.read_sql_query(
        "SELECT fecha, cuenta, saldo, rentabilidad_generada FROM ahorros_snapshot ORDER BY fecha",
        conn,
    )
    df_saldo_snapshot = pd.read_sql_query(
        """
        SELECT c.nombre AS cuenta, s.fecha, s.saldo
        FROM saldo_snapshot s JOIN cuentas c ON c.id = s.cuenta_id
        ORDER BY s.fecha
        """,
        conn,
    )

if df_trans.empty and df_deuda.empty and df_ahorros.empty:
    st.info("Aun no hay datos cargados. Ve a 'Cargar Cartola', 'Cargar Deuda CMF' o 'Registrar Ahorro' para empezar.")
    st.stop()

for df, col in ((df_trans, "fecha"), (df_deuda, "fecha_actualizacion"), (df_ahorros, "fecha"), (df_saldo_snapshot, "fecha")):
    if not df.empty:
        df[col] = pd.to_datetime(df[col])

# --- Resumen general (siempre visible arriba, sin necesidad de cambiar de pestaña) ---
# El saldo actual se toma del dato mas reciente entre la ultima transaccion y el ultimo
# "saldo disponible" guardado (de un PDF de movimientos): a veces el disponible cambia por
# retenciones que no aparecen como una transaccion propiamente tal, y viceversa una cartola
# nueva puede traer transacciones mas recientes que el ultimo saldo disponible guardado.
_ultimo_trans = (
    df_trans.sort_values("fecha").groupby("cuenta").tail(1)[["cuenta", "fecha", "saldo"]]
    if not df_trans.empty
    else pd.DataFrame(columns=["cuenta", "fecha", "saldo"])
)
_ultimo_snapshot = (
    df_saldo_snapshot.sort_values("fecha").groupby("cuenta").tail(1)[["cuenta", "fecha", "saldo"]]
    if not df_saldo_snapshot.empty
    else pd.DataFrame(columns=["cuenta", "fecha", "saldo"])
)
_saldo_actual_por_cuenta = pd.concat([_ultimo_trans, _ultimo_snapshot])
if not _saldo_actual_por_cuenta.empty:
    _saldo_actual_por_cuenta = _saldo_actual_por_cuenta.sort_values("fecha").groupby("cuenta").tail(1)
saldo_cc_actual = _saldo_actual_por_cuenta["saldo"].sum() if not _saldo_actual_por_cuenta.empty else 0
ahorros_actual = (
    df_ahorros.sort_values("fecha").groupby("cuenta").tail(1)["saldo"].sum() if not df_ahorros.empty else 0
)
deuda_actual = df_deuda.sort_values("fecha_actualizacion").tail(1)["deuda_total"].iloc[0] if not df_deuda.empty else 0

kpi_cards(
    [
        ("Saldo cuenta corriente", clp(saldo_cc_actual), COLOR_PROYECCION, "\U0001F4B3"),
        ("Ahorros / inversiones", clp(ahorros_actual), COLOR_AHORROS, "\U0001F4B0"),
        ("Deuda CMF vigente", clp(deuda_actual), COLOR_DEUDA, "\U0001F4C4"),
        ("Patrimonio neto estimado", clp(saldo_cc_actual + ahorros_actual - deuda_actual), COLOR_PATRIMONIO, "\U00002696"),
    ]
)

# Recordatorio de pago de tarjeta visible en cualquier pestaña, para que no se pase la fecha
# (pedido del usuario: "un msj para que no se me olvide pagar la TC y no me cobre intereses").
_cfg_tc_top = obtener_config_tarjeta()
if _cfg_tc_top and _cfg_tc_top.get("dia_pago"):
    _hoy_top = datetime.date.today()
    _fecha_pago_top = _proxima_fecha_dia(int(_cfg_tc_top["dia_pago"]), _hoy_top)
    _dias_top = (_fecha_pago_top - _hoy_top).days
    if _dias_top <= 5:
        st.error(
            f"\U000023F0 Tu tarjeta de credito vence el **{_fecha_pago_top.strftime('%d-%m-%Y')}** "
            f"({'hoy' if _dias_top == 0 else ('vencida' if _dias_top < 0 else f'en {_dias_top} dias')}) — "
            "paga el total facturado para no generar intereses. Detalle en la pestaña Gastos."
        )

st.divider()

tab_gastos, tab_ahorros, tab_proyeccion, tab_deuda = st.tabs(
    ["\U0001F4B8 Gastos", "\U0001F4B0 Ahorros", "\U0001F4C8 Proyeccion", "\U0001F4C4 Deuda CMF"]
)

# --- Gastos por categoria ---
with tab_gastos:
    if df_trans.empty:
        st.info("Aun no has cargado ninguna cartola. Ve a 'Cargar Cartola' para empezar.")
    else:
        comp = comparacion_mes_actual(df_trans)
        if comp is None:
            st.info("Necesitas transacciones de al menos 2 meses distintos para ver la comparacion mensual y las alertas.")
        else:
            with st.container(border=True, key="card_gastos"):
                st.subheader(f"Este mes ({comp['mes_actual']}) vs el anterior ({comp['mes_anterior']})")
                delta_txt = f"{comp['porcentaje']:+.1f}% vs mes anterior" if comp["porcentaje"] is not None else None
                delta_ok = (comp["porcentaje"] < 0) if comp["porcentaje"] is not None else None
                kpi_cards(
                    [
                        (f"Gasto en {comp['mes_anterior']}", clp(comp["gasto_anterior"]), COLOR_GASTOS, "\U0001F4C5"),
                        (f"Gasto en {comp['mes_actual']}", clp(comp["gasto_actual"]), COLOR_GASTOS, "\U0001F4C5", delta_txt, delta_ok),
                    ]
                )

                comp_cat = comparacion_por_categoria(df_trans)
                if not comp_cat.empty:
                    fig = px.bar(
                        comp_cat,
                        x="categoria",
                        y="monto_cargo",
                        color="mes",
                        barmode="group",
                        category_orders={"mes": [comp["mes_anterior"], comp["mes_actual"]]},
                        title="Gasto por categoria: este mes vs el anterior",
                    )
                    st.plotly_chart(tema(fig), use_container_width=True)

                logros = logros_ahorro(df_trans)
                if logros:
                    st.markdown(f"**Buen dato en {comp['mes_actual']}**")
                    for l in logros:
                        st.success(
                            f"**{l['categoria']}**: destinaste **{clp_md(l['actual'])}** este mes, un **{l['exceso_pct']:.0f}%** mas "
                            f"que tu promedio historico (**{clp_md(l['promedio'])}** en los ultimos {l['n_meses']} meses)."
                        )

                alertas = alertas_categoria(df_trans)
                if alertas:
                    st.markdown(f"**Alertas de gasto en {comp['mes_actual']}**")
                    for a in alertas:
                        st.warning(
                            f"**{a['categoria']}**: gastaste **{clp_md(a['actual'])}** este mes, un **{a['exceso_pct']:.0f}%** mas "
                            f"que tu promedio historico (**{clp_md(a['promedio'])}** en los ultimos {a['n_meses']} meses)."
                        )

        with st.container(border=True, key="card_gastos_detalle"):
            st.subheader("En que gasto mi dinero")

            fmin, fmax = df_trans["fecha"].min().date(), df_trans["fecha"].max().date()
            # Por defecto muestra solo el ultimo mes (no todo el historico), pero se puede
            # expandir libremente porque min_value/max_value siguen cubriendo todos los datos.
            inicio_default = max(fmin, fmax.replace(day=1))
            rango = st.date_input("Periodo a analizar", value=(inicio_default, fmax), min_value=fmin, max_value=fmax)
            if isinstance(rango, tuple) and len(rango) == 2:
                desde, hasta = rango
            else:
                desde, hasta = inicio_default, fmax

            mask = (df_trans["fecha"].dt.date >= desde) & (df_trans["fecha"].dt.date <= hasta)
            df_periodo = df_trans[mask]

            es_ahorro_mask = df_periodo["categoria"].apply(es_categoria_ahorro)
            es_ingreso_mask = df_periodo["categoria"].apply(es_categoria_ingreso)
            es_gasto_mask = ~es_ahorro_mask & ~es_ingreso_mask
            # Neto (cargo - abono) por categoria: si categorizas un reembolso (ej. te devuelven
            # tu parte de una salida grupal) en la MISMA categoria del gasto original, se
            # descuenta aqui en vez de aparecer como un ingreso suelto que no compensa nada.
            total_gastos = (
                df_periodo.loc[es_gasto_mask, "monto_cargo"].sum() - df_periodo.loc[es_gasto_mask, "monto_abono"].sum()
            )
            total_ahorro_periodo = df_periodo.loc[es_ahorro_mask, "monto_cargo"].sum()
            total_ingresos = df_periodo["monto_abono"].sum()

            kpi_cards(
                [
                    ("Total gastos en el periodo", clp(total_gastos), COLOR_GASTOS, "\U0001F4B8"),
                    ("Destinado a ahorro en el periodo", clp(total_ahorro_periodo), COLOR_AHORROS, "\U0001F4B0"),
                    ("Total abonos (entradas) en el periodo", clp(total_ingresos), COLOR_PROYECCION, "\U0001F4E5"),
                ]
            )
            st.caption(
                "El gasto no incluye lo que transferiste a categorias de ahorro/inversion ni tus ingresos — y si "
                "categorizas un reembolso (ej. te devuelven tu parte de una salida grupal) en la misma categoria "
                "del gasto original, se descuenta del gasto de esa categoria en vez de sumarse aparte."
            )

            gasto_categoria = (
                df_periodo[es_gasto_mask]
                .groupby("categoria", as_index=False)
                .agg(_cargo=("monto_cargo", "sum"), _abono=("monto_abono", "sum"))
            )
            gasto_categoria["monto_cargo"] = gasto_categoria["_cargo"] - gasto_categoria["_abono"]
            gasto_categoria = gasto_categoria[["categoria", "monto_cargo"]].sort_values("monto_cargo", ascending=False)
            gasto_categoria["porcentaje"] = gasto_categoria["monto_cargo"] / gasto_categoria["monto_cargo"].sum() * 100

            col_pie, col_lista = st.columns([3, 2])
            with col_pie:
                st.markdown("**Distribucion de gastos por categoria**")
                # Una categoria en negativo (te reembolsaron mas de lo que gastaste ahi este
                # periodo) no se puede mostrar como porcion de una torta, asi que se excluye
                # del grafico pero se mantiene visible en el listado de al lado.
                gasto_categoria_pie = gasto_categoria[gasto_categoria["monto_cargo"] > 0]
                fig = px.pie(
                    gasto_categoria_pie,
                    names="categoria",
                    values="monto_cargo",
                    hole=0.35,
                )
                fig.update_traces(textinfo="percent+label")
                fig.update_layout(height=560, showlegend=False)
                st.plotly_chart(tema(fig), use_container_width=True)
            with col_lista:
                st.markdown("**Listado por categoria**")
                df_lista = gasto_categoria.rename(
                    columns={"categoria": "Categoria", "monto_cargo": "Monto", "porcentaje": "%"}
                ).copy()
                df_lista["Monto"] = df_lista["Monto"].apply(clp)
                st.dataframe(
                    df_lista,
                    hide_index=True,
                    use_container_width=True,
                    height=560,
                    column_config={"%": st.column_config.NumberColumn("%", format="%.1f%%")},
                )

        with st.container(border=True, key="card_gastos_saldo"):
            st.subheader("Evolucion del saldo en cuenta corriente")
            fig = px.line(df_trans, x="fecha", y="saldo", color="cuenta", markers=True)
            st.plotly_chart(tema(fig), use_container_width=True)

            with st.expander("Ver transacciones del periodo"):
                df_ver = df_periodo.sort_values("fecha", ascending=False).copy()
                for col in ("monto_cargo", "monto_abono", "saldo"):
                    df_ver[col] = df_ver[col].apply(clp)
                st.dataframe(
                    df_ver,
                    hide_index=True,
                    use_container_width=True,
                    column_config={"monto_cargo": "cargo", "monto_abono": "abono", "saldo": "saldo"},
                )

# --- Ahorros ---
ultimo_por_cuenta = pd.DataFrame()
with tab_ahorros:
    if df_ahorros.empty:
        st.info("Aun no registras ningun ahorro. Ve a 'Registrar Ahorro' para empezar.")
    else:
        ultimo_por_cuenta = df_ahorros.sort_values("fecha").groupby("cuenta").tail(1)

        metas = listar_metas()
        if metas:
            with st.container(border=True, key="card_ahorros_metas"):
                st.subheader("Metas de ahorro")
                progresos = calcular_progresos(metas, df_ahorros, df_trans, ultimo_por_cuenta)
                for m in metas:
                    p = progresos[m["id"]]
                    alcance = m["cuenta"] or "total de tus ahorros"
                    titulo = f"**{m['nombre']}** ({alcance}) — {clp_md(p['monto_actual'])} de {clp_md(m['monto_objetivo'])}"
                    if p["cumplida"]:
                        st.success(f"{titulo} — meta cumplida! 🎉")
                    else:
                        st.markdown(titulo)
                        st.progress(min(p["porcentaje"], 100) / 100)
                        detalle = f"{p['porcentaje']:.0f}% completado, faltan {clp_md(p['falta'])}."
                        if p["fecha_estimada"]:
                            detalle += f" A tu ritmo actual ({clp_md(p['ritmo_mensual'])}/mes), la alcanzarias en **{p['fecha_estimada'].strftime('%B %Y')}**."
                        elif p["ritmo_mensual"] is not None and p["ritmo_mensual"] <= 0:
                            detalle += " Con tu ritmo actual (no estas ahorrando o el saldo esta bajando) no vas a llegar; aumenta lo que destinas cada mes."
                        else:
                            detalle += " Aun no hay suficiente historial para estimar una fecha."
                        if m["fecha_objetivo"]:
                            detalle += f" Fecha limite que pusiste: {m['fecha_objetivo']}."
                        st.caption(detalle)
                st.caption(
                    "Si mas de una meta comparte el mismo alcance (ej. ambas al total de tus ahorros), la plata se "
                    "reparte entre ellas en orden — primero las con fecha limite mas proxima — para no contar el "
                    "mismo peso dos veces."
                )

        with st.container(border=True, key="card_ahorros_evolucion"):
            fig = px.line(
                df_ahorros, x="fecha", y="saldo", color="cuenta", markers=True, title="Evolucion del saldo de ahorros"
            )
            st.plotly_chart(tema(fig), use_container_width=True)

        serie_ahorro = ahorro_por_mes(df_trans) if not df_trans.empty else pd.Series(dtype=float)
        if len(serie_ahorro) >= 1:
            with st.container(border=True, key="card_ahorros_mensual"):
                st.subheader("Cuanto ahorre este mes")
                st.caption("Segun las transferencias categorizadas como ahorro/inversion en tu cartola.")

                if len(serie_ahorro) >= 2:
                    mes_actual_a, mes_anterior_a = serie_ahorro.index[-1], serie_ahorro.index[-2]
                    actual_a, anterior_a = float(serie_ahorro.iloc[-1]), float(serie_ahorro.iloc[-2])
                    diferencia_a = actual_a - anterior_a
                    pct_a = (diferencia_a / anterior_a * 100) if anterior_a else None
                    delta_txt_a = f"{pct_a:+.1f}% vs mes anterior" if pct_a is not None else None
                    delta_ok_a = (pct_a > 0) if pct_a is not None else None
                    kpi_cards(
                        [
                            (f"Ahorrado en {mes_anterior_a}", clp(anterior_a), COLOR_AHORROS, "\U0001F4B0"),
                            (f"Ahorrado en {mes_actual_a}", clp(actual_a), COLOR_AHORROS, "\U0001F4B0", delta_txt_a, delta_ok_a),
                        ]
                    )
                else:
                    kpi_cards([(f"Ahorrado en {serie_ahorro.index[-1]}", clp(serie_ahorro.iloc[-1]), COLOR_AHORROS, "\U0001F4B0")])

                df_serie_ahorro = serie_ahorro.reset_index()
                df_serie_ahorro.columns = ["mes", "monto"]
                df_serie_ahorro["mes"] = df_serie_ahorro["mes"].astype(str)
                fig = px.bar(df_serie_ahorro, x="mes", y="monto", title="Ahorro destinado por mes")
                st.plotly_chart(tema(fig, COLOR_AHORROS), use_container_width=True)

        if df_ahorros["rentabilidad_generada"].notna().any():
            with st.container(border=True, key="card_ahorros_rentabilidad"):
                st.subheader("Cuanto he generado con mis ahorros")
                rent = df_ahorros.sort_values("fecha").groupby("cuenta").tail(1)[["cuenta", "rentabilidad_generada"]].dropna()
                fig = px.bar(rent, x="cuenta", y="rentabilidad_generada", title="Rentabilidad generada a la fecha, por cuenta")
                st.plotly_chart(tema(fig, COLOR_AHORROS), use_container_width=True)
                kpi_cards([("Rentabilidad total generada", clp(rent["rentabilidad_generada"].sum()), COLOR_AHORROS, "\U0001F4C8")])

# --- Proyeccion de ahorros ---
with tab_proyeccion:
    if ultimo_por_cuenta.empty:
        st.info("Aun no registras ningun ahorro. Ve a 'Registrar Ahorro' para empezar.")
    else:
        with st.container(border=True, key="card_proy_distribucion"):
            st.subheader("Donde tengo mis ahorros")
            fig = px.pie(ultimo_por_cuenta, names="cuenta", values="saldo", title="Distribucion actual de ahorros por cuenta")
            st.plotly_chart(tema(fig), use_container_width=True)

            config_tasas_marginal = listar_config()
            cuentas_con_tasa_marginal = {c: cfg for c, cfg in config_tasas_marginal.items() if cfg and cfg.get("tasa_base")}
            if cuentas_con_tasa_marginal:
                st.markdown("**¿A que cuenta conviene ingresar tu proximo ahorro?**")
                monto_prox_ahorro = st.number_input(
                    "Monto que vas a ahorrar",
                    min_value=0.0,
                    step=10000.0,
                    format="%.0f",
                    value=100000.0,
                    key="monto_prox_ahorro",
                )
                if monto_prox_ahorro > 0:
                    filas_marginal = []
                    for cuenta, cfg in cuentas_con_tasa_marginal.items():
                        saldo_actual_cta = 0.0
                        if not ultimo_por_cuenta.empty and cuenta in ultimo_por_cuenta["cuenta"].values:
                            saldo_actual_cta = float(
                                ultimo_por_cuenta.loc[ultimo_por_cuenta["cuenta"] == cuenta, "saldo"].iloc[0]
                            )
                        # Ganancia MARGINAL de este monto especifico (no la tasa base de la cuenta):
                        # si la cuenta ya tiene saldo cerca o sobre su tramo de mejor tasa, lo nuevo
                        # puede caer en una tasa mas baja aunque la tasa base configurada sea alta.
                        ganancia_extra = calcular_ganancia_anual(saldo_actual_cta + monto_prox_ahorro, cfg) - calcular_ganancia_anual(
                            saldo_actual_cta, cfg
                        )
                        filas_marginal.append(
                            {
                                "cuenta": cuenta,
                                "saldo_actual": saldo_actual_cta,
                                "ganancia_extra_1a": ganancia_extra,
                                "tasa_marginal_%": ganancia_extra / monto_prox_ahorro * 100,
                            }
                        )
                    df_marginal = pd.DataFrame(filas_marginal).sort_values("ganancia_extra_1a", ascending=False)
                    mejor_marginal = df_marginal.iloc[0]
                    st.success(
                        f"Deposita tu proximo ahorro (**{clp_md(monto_prox_ahorro)}**) en **{mejor_marginal['cuenta']}** — "
                        f"hoy es la que te da la mejor tasa marginal (**{mejor_marginal['tasa_marginal_%']:.2f}% anual "
                        f"efectiva**), generarias aprox. **{clp_md(mejor_marginal['ganancia_extra_1a'])}** extra en un año."
                    )
                    df_marginal_fmt = df_marginal.copy()
                    df_marginal_fmt["saldo_actual"] = df_marginal_fmt["saldo_actual"].apply(clp)
                    df_marginal_fmt["ganancia_extra_1a"] = df_marginal_fmt["ganancia_extra_1a"].apply(clp)
                    st.dataframe(
                        df_marginal_fmt,
                        hide_index=True,
                        use_container_width=True,
                        column_config={
                            "cuenta": "Cuenta",
                            "saldo_actual": "Saldo actual",
                            "ganancia_extra_1a": "Ganancia extra estimada en 1 año",
                            "tasa_marginal_%": st.column_config.NumberColumn("Tasa marginal efectiva", format="%.2f%%"),
                        },
                    )
                    st.caption(
                        "La 'tasa marginal' es lo que ganaria especificamente este monto nuevo segun el saldo que ya "
                        "tiene cada cuenta — no es necesariamente la tasa base de la cuenta, porque si ya esta sobre "
                        "su tramo de mejor tasa, lo nuevo cae en la tasa mas baja."
                    )

        config_tasas = listar_config()
        if not any(c.get("tasa_base") for c in config_tasas.values()):
            st.info("Configura una tasa de interes anual para tus cuentas en 'Registrar Ahorro' para ver la proyeccion aqui.")
        else:
            with st.container(border=True, key="card_proy_ganancia"):
                st.subheader("Cuanto generaria si dejo la plata donde esta")
                st.caption(
                    "Proyeccion a 1 año, segun la tasa que configuraste en 'Registrar Ahorro' y el saldo actual de cada cuenta."
                )
                proy = ultimo_por_cuenta.copy()
                proy["config"] = proy["cuenta"].apply(lambda c: config_tasas.get(c))
                proy["tasa_efectiva_%"] = proy.apply(lambda r: tasa_efectiva(r["saldo"], r["config"]), axis=1)
                proy["ganancia_estimada_1a"] = proy.apply(lambda r: calcular_ganancia_anual(r["saldo"], r["config"]), axis=1)
                proy = proy[proy["ganancia_estimada_1a"] > 0][["cuenta", "saldo", "tasa_efectiva_%", "ganancia_estimada_1a"]]

                if proy.empty:
                    st.info("Ninguna de tus cuentas con saldo tiene una tasa configurada mayor a 0.")
                else:
                    proy = proy.sort_values("ganancia_estimada_1a", ascending=False)
                    df_proy = proy.copy()
                    df_proy["saldo"] = df_proy["saldo"].apply(clp)
                    df_proy["ganancia_estimada_1a"] = df_proy["ganancia_estimada_1a"].apply(clp)
                    st.dataframe(
                        df_proy,
                        hide_index=True,
                        use_container_width=True,
                        column_config={
                            "cuenta": "Cuenta",
                            "saldo": "Saldo actual",
                            "tasa_efectiva_%": st.column_config.NumberColumn("Tasa anual efectiva", format="%.2f%%"),
                            "ganancia_estimada_1a": "Ganancia estimada en 1 año",
                        },
                    )
                    ganancia_actual_total = proy["ganancia_estimada_1a"].sum()
                    kpi_cards(
                        [
                            (
                                "Ganancia total estimada en 1 año (con la distribucion actual)",
                                clp(ganancia_actual_total),
                                COLOR_PROYECCION,
                                "\U0001F4C8",
                            )
                        ]
                    )
                    st.caption(
                        "Estimacion simple con interes sobre el saldo actual; no considera aportes, retiros ni cambios de tasa futuros."
                    )

            if not proy.empty:
                with st.container(border=True, key="card_proy_fecha"):
                    st.subheader("Proyeccion a una fecha")
                    st.caption(
                        "Elige una fecha y estima cuanto tendrias ahorrado y cuanto seria intereses, si las tasas se "
                        "mantienen y sigues aportando a tu ritmo reciente de cada cuenta (mes a mes, no lineal, para "
                        "reflejar bien los tramos con tope)."
                    )
                    fecha_proyeccion = st.date_input(
                        "Proyectar hasta",
                        value=datetime.date.today() + datetime.timedelta(days=365),
                        min_value=datetime.date.today() + datetime.timedelta(days=1),
                    )
                    meses_proy = meses_entre(datetime.date.today(), fecha_proyeccion)

                    filas_proy_fecha = []
                    for _, fila in ultimo_por_cuenta.iterrows():
                        cfg = config_tasas.get(fila["cuenta"])
                        if not cfg or not cfg.get("tasa_base"):
                            continue
                        ritmo_cta = ritmo_mensual_cuenta(df_ahorros, fila["cuenta"])
                        r = proyectar_saldo(fila["saldo"], cfg, ritmo_cta, meses_proy)
                        filas_proy_fecha.append(
                            {
                                "cuenta": fila["cuenta"],
                                "saldo_actual": fila["saldo"],
                                "aporte_mensual_estimado": ritmo_cta or 0.0,
                                "total_aportado": r["total_aportado"],
                                "intereses_estimados": r["total_intereses"],
                                "saldo_proyectado": r["saldo_proyectado"],
                            }
                        )

                    if not filas_proy_fecha:
                        st.info("Ninguna de tus cuentas con saldo tiene una tasa configurada mayor a 0.")
                    else:
                        df_proy_fecha = pd.DataFrame(filas_proy_fecha).sort_values("saldo_proyectado", ascending=False)

                        total_actual = df_proy_fecha["saldo_actual"].sum()
                        total_aportado = df_proy_fecha["total_aportado"].sum()
                        total_intereses = df_proy_fecha["intereses_estimados"].sum()
                        total_proyectado = df_proy_fecha["saldo_proyectado"].sum()

                        pm1, pm2, pm3, pm4 = st.columns(4)
                        pm1.metric("Saldo inicial (hoy)", clp(total_actual))
                        pm2.metric(f"A aportar ({meses_proy} meses)", clp(total_aportado))
                        pm3.metric("Ganancia (intereses)", clp(total_intereses))
                        pm4.metric(
                            f"Saldo final a {fecha_proyeccion}",
                            clp(total_proyectado),
                            delta=clp(total_proyectado - total_actual),
                        )

                        df_proy_fecha_fmt = df_proy_fecha.copy()
                        for col in ("saldo_actual", "aporte_mensual_estimado", "total_aportado", "intereses_estimados", "saldo_proyectado"):
                            df_proy_fecha_fmt[col] = df_proy_fecha_fmt[col].apply(clp)
                        st.dataframe(
                            df_proy_fecha_fmt,
                            hide_index=True,
                            use_container_width=True,
                            column_config={
                                "cuenta": "Cuenta",
                                "saldo_actual": "Saldo actual",
                                "aporte_mensual_estimado": "Aporte mensual estimado",
                                "total_aportado": f"Total a aportar ({meses_proy} meses)",
                                "intereses_estimados": "Intereses estimados",
                                "saldo_proyectado": f"Saldo proyectado a {fecha_proyeccion}",
                            },
                        )
                        st.caption(
                            "El aporte mensual estimado sale del crecimiento real de saldo de cada cuenta entre tu "
                            "primer y ultimo registro; si una cuenta tiene poco historial, se asume que no seguiras "
                            "aportando (solo se proyecta el interes)."
                        )

                planes_con_costo = []
                for _, fila in ultimo_por_cuenta.iterrows():
                    cfg = config_tasas.get(fila["cuenta"])
                    ev = evaluar_plan_con_costo(fila["saldo"], cfg)
                    if ev:
                        planes_con_costo.append({"cuenta": fila["cuenta"], "saldo": fila["saldo"], **ev})

                if planes_con_costo:
                    with st.expander("\U0001F4B3 ¿Me conviene pagar el plan premium?"):
                        for p in planes_con_costo:
                            if p["conviene_activar"]:
                                st.success(
                                    f"**{p['cuenta']}**: con tu saldo actual (**{clp_md(p['saldo'])}**) SI te conviene pagar el "
                                    f"plan — ganarias **{clp_md(p['diferencia'])}** mas al año que sin activarlo (equilibrio en "
                                    f"**{clp_md(p['punto_equilibrio'])}**)."
                                )
                            else:
                                st.warning(
                                    f"**{p['cuenta']}**: con tu saldo actual (**{clp_md(p['saldo'])}**) NO te conviene pagar el "
                                    f"plan — perderias **{clp_md(-p['diferencia'])}** al año frente a no activarlo. Te conviene "
                                    f"desde que tengas **{clp_md(p['punto_equilibrio'])}** en la cuenta."
                                )

                with st.container(border=True, key="card_proy_reparto"):
                    st.subheader("¿Como repartir tu plata entre tus cuentas para maximizar la ganancia?")
                    # Solo se reparten las cuentas marcadas como "movimiento" en 'Registrar Ahorro':
                    # las "ahorro estatica" son plata que no se quiere mover a otra fintech, asi que
                    # quedan fuera tanto como origen del monto a repartir como destino posible.
                    tipos_cuenta = obtener_tipos_cuenta()
                    cuentas_movimiento = {
                        c for c in ultimo_por_cuenta["cuenta"] if tipos_cuenta.get(c, "ahorro") == "movimiento"
                    }
                    total_ahorros = ultimo_por_cuenta[ultimo_por_cuenta["cuenta"].isin(cuentas_movimiento)]["saldo"].sum()
                    config_tasas_reparto = {c: cfg for c, cfg in config_tasas.items() if c in cuentas_movimiento}
                    reparto = optimizar_asignacion(total_ahorros, config_tasas_reparto)

                    if reparto:
                        ganancia_optima = sum(r["ganancia"] for r in reparto)
                        diferencia = ganancia_optima - ganancia_actual_total
                        if diferencia > 1:
                            detalle = ", ".join(f"**{clp_md(r['monto_asignado'])}** en **{r['cuenta']}**" for r in reparto)
                            st.success(
                                f"Repartiendo tu total (**{clp_md(total_ahorros)}**) asi: {detalle} — "
                                f"generarias aprox. **{clp_md(ganancia_optima)}** al año, **{clp_md(diferencia)}** mas que con la "
                                "distribucion actual."
                            )
                        else:
                            st.info(
                                "Con la distribucion actual ya estas obteniendo el mejor resultado posible entre tus "
                                "cuentas configuradas."
                            )

                        df_reparto = pd.DataFrame(reparto)
                        df_reparto["monto_asignado"] = df_reparto["monto_asignado"].apply(clp)
                        df_reparto["ganancia"] = df_reparto["ganancia"].apply(clp)
                        st.dataframe(
                            df_reparto,
                            hide_index=True,
                            use_container_width=True,
                            column_config={"cuenta": "Cuenta", "monto_asignado": "Monto sugerido", "ganancia": "Ganancia de ese tramo"},
                        )
                        st.caption(
                            "El reparto llena primero los tramos con mejor tasa (por ejemplo, el tope con tasa alta de una "
                            "cuenta con plan premium) y pone el resto en la siguiente mejor tasa disponible. No considera "
                            "topes que la app no te haya informado, asi que confirma las condiciones reales antes de mover dinero."
                        )

            _config_flotar = listar_config()
            if saldo_cc_actual > 0 and any(c.get("tasa_base") for c in _config_flotar.values()):
                with st.container(border=True, key="card_proy_flotar"):
                    st.subheader("\U0001F4B0 ¿Me conviene mover mi saldo a una fintech mientras uso la tarjeta de credito?")
                    st.caption(
                        "Tu cuenta corriente no genera interes. Si pagas el dia a dia con la tarjeta de credito y "
                        "dejas este saldo en una cuenta remunerada hasta la fecha de pago, genera algo en vez de "
                        "nada — siempre que la devuelvas a tiempo para pagar el total facturado (si no, el interes "
                        "rotativo de la tarjeta se come cualquier ganancia)."
                    )

                    _cfg_tc_flotar = obtener_config_tarjeta()
                    if _cfg_tc_flotar and _cfg_tc_flotar.get("dia_pago"):
                        _hoy = datetime.date.today()
                        _fecha_pago_tc = _proxima_fecha_dia(int(_cfg_tc_flotar["dia_pago"]), _hoy)
                        dias_flotar = max((_fecha_pago_tc - _hoy).days, 1)
                        kpi_cards(
                            [
                                ("Saldo cuenta corriente", clp(saldo_cc_actual), COLOR_PROYECCION, "\U0001F4B3"),
                                (
                                    "Dias hasta que necesites pagar la tarjeta",
                                    f"{dias_flotar} dias",
                                    COLOR_DEUDA if dias_flotar <= 5 else COLOR_AHORROS,
                                    "\U0001F4C6",
                                    _fecha_pago_tc.strftime("Vence %d-%m-%Y"),
                                    dias_flotar > 5,
                                ),
                            ]
                        )
                    else:
                        dias_flotar = 30
                        kpi_cards([("Saldo cuenta corriente", clp(saldo_cc_actual), COLOR_PROYECCION, "\U0001F4B3")])
                        st.caption(
                            "No configuraste la fecha de pago de tu tarjeta (mas abajo en esta pestaña), asi que "
                            "se usan 30 dias por defecto."
                        )

                    # La ganancia se calcula marginal (saldo existente + lo nuevo, menos lo que ya generaria el
                    # saldo existente solo): si la cuenta ya tiene plata cerca o sobre el tope del tramo (ej.
                    # Copec Pay), lo que agregas puede caer en la tasa mas baja, no en la tasa base completa.
                    _tipos_flotar = obtener_tipos_cuenta()
                    filas_flotar = [{"opcion": "Dejarlo en cuenta corriente (no genera interes)", "ganancia": 0.0}]
                    for cuenta, cfg in _config_flotar.items():
                        if not cfg or not cfg.get("tasa_base"):
                            continue
                        if _tipos_flotar.get(cuenta, "ahorro") != "movimiento":
                            continue
                        saldo_existente = 0.0
                        if not ultimo_por_cuenta.empty and cuenta in ultimo_por_cuenta["cuenta"].values:
                            saldo_existente = float(ultimo_por_cuenta.loc[ultimo_por_cuenta["cuenta"] == cuenta, "saldo"].iloc[0])
                        ganancia_marginal = ganancia_periodo(
                            saldo_existente + saldo_cc_actual, cfg, dias_flotar
                        ) - ganancia_periodo(saldo_existente, cfg, dias_flotar)
                        filas_flotar.append({"opcion": cuenta, "ganancia": ganancia_marginal})
                    df_flotar = pd.DataFrame(filas_flotar).sort_values("ganancia", ascending=False)
                    mejor_flotar = df_flotar.iloc[0]

                    if mejor_flotar["opcion"] != "Dejarlo en cuenta corriente (no genera interes)":
                        st.success(
                            f"Si mueves tu saldo actual (**{clp_md(saldo_cc_actual)}**) a **{mejor_flotar['opcion']}** "
                            f"por **{int(dias_flotar)} dias**, generarias aprox. **{clp_md(mejor_flotar['ganancia'])}** "
                            "extra (ya considerando el saldo que esa cuenta ya tiene) — algo en vez de nada, "
                            "mientras cubres tus gastos con la tarjeta."
                        )
                    else:
                        st.info(
                            "Con el saldo que ya tienen tus cuentas 'movimiento', agregar mas no generaria una "
                            "ganancia extra relevante (probablemente ya estan sobre el tramo de mejor tasa)."
                        )

                    df_flotar_fmt = df_flotar.copy()
                    df_flotar_fmt["ganancia"] = df_flotar_fmt["ganancia"].apply(clp)
                    st.dataframe(
                        df_flotar_fmt,
                        hide_index=True,
                        use_container_width=True,
                        column_config={"opcion": "Opcion", "ganancia": f"Ganancia en {int(dias_flotar)} dias"},
                    )

                    _cuentas_abono_mensual_flotar = [
                        c for c, cfg in _config_flotar.items()
                        if cfg and cfg.get("tasa_base") and cfg.get("abono_mensual")
                        and _tipos_flotar.get(c, "ahorro") == "movimiento"
                    ]
                    if _cuentas_abono_mensual_flotar:
                        st.caption(
                            f"⏳ {', '.join(_cuentas_abono_mensual_flotar)} abona el interes recien los primeros "
                            "dias del mes siguiente (no dia a dia), asi que esa ganancia puede que no se refleje "
                            "en tu saldo antes de la fecha de pago de tu tarjeta — igual la vas a recibir, solo "
                            "que despues."
                        )

                    # Ademas del interes por dejar la plata en la fintech, la otra mitad de la estrategia es
                    # que ese mismo saldo, gastado con la tarjeta, tambien genera Dolares Premio.
                    _tipo_tc_flotar = st.session_state.get("tipo_tarjeta_premio")
                    _valor_dolar_flotar = st.session_state.get("valor_dolar_premio")
                    if _tipo_tc_flotar and _valor_dolar_flotar:
                        _dp_flotar = (saldo_cc_actual / _valor_dolar_flotar) * (
                            TASAS_DOLARES_PREMIO[_tipo_tc_flotar] / 100
                        )
                        kpi_cards(
                            [
                                (
                                    f"Dolares Premio usando {clp(saldo_cc_actual)} en tu {_tipo_tc_flotar}",
                                    f"US$ {_dp_flotar:,.2f}".replace(",", "."),
                                    COLOR_PATRIMONIO,
                                    "\U00002708",
                                )
                            ]
                        )
                        st.caption(
                            "Ganas por los dos lados: el interes de la fintech (arriba) y los Dolares Premio de la "
                            "tarjeta (esta tarjeta) al usar la misma plata."
                        )
                    else:
                        st.caption(
                            "Configura el tipo de tarjeta y el valor del dolar aqui abajo para ver tambien cuantos "
                            "Dolares Premio generarias usando este mismo saldo en la tarjeta."
                        )

            gasto_tarjeta_mes = 0.0
            if not df_trans.empty:
                _comp_tc = comparacion_mes_actual(df_trans)
                if _comp_tc is not None:
                    _comp_cat_tc = comparacion_por_categoria(df_trans)
                    if not _comp_cat_tc.empty:
                        _fila_tarjeta = _comp_cat_tc[
                            (_comp_cat_tc["categoria"] == "Pago tarjeta de credito")
                            & (_comp_cat_tc["mes"] == _comp_tc["mes_actual"])
                        ]
                        if not _fila_tarjeta.empty:
                            gasto_tarjeta_mes = float(_fila_tarjeta["monto_cargo"].iloc[0])

            # Configuracion de la tarjeta (tipo, dia de corte, dia de pago): se guarda en la BD para no
            # tener que reingresarla cada vez que se abre la app (pedido del usuario: "se debe llenar sola").
            _cfg_tc = obtener_config_tarjeta()
            if "tipo_tarjeta_premio" not in st.session_state and _cfg_tc and _cfg_tc.get("tipo_tarjeta"):
                st.session_state["tipo_tarjeta_premio"] = _cfg_tc["tipo_tarjeta"]
            if "dia_corte_tarjeta" not in st.session_state and _cfg_tc and _cfg_tc.get("dia_corte"):
                st.session_state["dia_corte_tarjeta"] = _cfg_tc["dia_corte"]
            if "dia_pago_tarjeta" not in st.session_state and _cfg_tc and _cfg_tc.get("dia_pago"):
                st.session_state["dia_pago_tarjeta"] = _cfg_tc["dia_pago"]

            _tipo_para_svg = (
                (_cfg_tc.get("tipo_tarjeta") if _cfg_tc else None)
                or st.session_state.get("tipo_tarjeta_premio")
                or next(iter(TASAS_DOLARES_PREMIO))
            )
            _bg_tarjeta, _fg_tarjeta, _ = _colores_tarjeta(_tipo_para_svg)
            # Toda la seccion se tiñe (transparente) con el color/nivel de la tarjeta, no solo el icono.
            st.markdown(
                f'<style>.st-key-card_gastos_tarjeta {{ background-color: {_bg_tarjeta}14 !important; '
                f"border-color: {_bg_tarjeta}40 !important; }}</style>",
                unsafe_allow_html=True,
            )

            with st.container(border=True, key="card_gastos_tarjeta"):
                st.subheader("\U0001F4B3 Dolares Premio y disciplina de pago")
                st.caption(
                    "La app no lee la cartola de la tarjeta de credito, solo tu cuenta corriente — asi que el "
                    "gasto de la tarjeta se estima con lo que le transferiste este mes (categoria 'Pago tarjeta "
                    "de credito'), asumiendo que pagas el total facturado y no dejas saldo revolvente."
                )

                # Valor del dolar: se consulta automatico a mindicador.cl (unica conexion a
                # internet de la app, no envia ningun dato tuyo) y se cachea por 1 hora. Si falla
                # (sin internet, API caida) o el usuario prefiere otro valor, lo puede editar igual.
                if "valor_dolar_premio" not in st.session_state:
                    _valor_auto = obtener_valor_dolar()
                    if _valor_auto:
                        st.session_state["valor_dolar_premio"] = _valor_auto

                # Una vez guardada, la configuracion (tipo, corte, pago) queda bloqueada para que
                # no se cambie sin querer — hay que apretar "Actualizar" para poder editarla de nuevo.
                _tiene_config_guardada = bool(_cfg_tc and _cfg_tc.get("tipo_tarjeta"))
                if "tc_bloqueada" not in st.session_state:
                    st.session_state["tc_bloqueada"] = _tiene_config_guardada

                if st.session_state["tc_bloqueada"] and _tiene_config_guardada:
                    tipo_tarjeta, dia_corte, dia_pago = _cfg_tc["tipo_tarjeta"], _cfg_tc["dia_corte"], _cfg_tc["dia_pago"]
                    st.markdown(_banner_tarjeta_credito(tipo_tarjeta, _c["text"]), unsafe_allow_html=True)
                    dtc1, dtc2, dtc3 = st.columns(3)
                    dtc1.metric("Tipo de tarjeta", tipo_tarjeta)
                    dtc2.metric("Dia de corte", dia_corte)
                    dtc3.metric("Dia limite de pago", dia_pago)
                    if st.button("\U0000270F\U0000FE0F Actualizar configuracion de tarjeta", key="editar_tarjeta_btn"):
                        st.session_state["tc_bloqueada"] = False
                        st.rerun()
                else:
                    # Los valores por defecto se toman de lo ya guardado (no del minimo del campo),
                    # para que "Actualizar" abra con lo ingresado la vez anterior, no en blanco/1.
                    _opciones_tc = list(TASAS_DOLARES_PREMIO.keys())
                    _tipo_prev = _cfg_tc.get("tipo_tarjeta") if _cfg_tc else None
                    _idx_prev = _opciones_tc.index(_tipo_prev) if _tipo_prev in _opciones_tc else 0
                    dtc1, dtc2, dtc3 = st.columns(3)
                    tipo_tarjeta = dtc1.selectbox(
                        "Tipo de tarjeta (para calcular los beneficios)",
                        _opciones_tc,
                        index=_idx_prev,
                        key="tipo_tarjeta_premio",
                    )
                    dia_corte = dtc2.number_input(
                        "Dia de corte",
                        min_value=1,
                        max_value=31,
                        step=1,
                        value=(_cfg_tc.get("dia_corte") or 1) if _cfg_tc else 1,
                        key="dia_corte_tarjeta",
                    )
                    dia_pago = dtc3.number_input(
                        "Dia limite de pago",
                        min_value=1,
                        max_value=31,
                        step=1,
                        value=(_cfg_tc.get("dia_pago") or 1) if _cfg_tc else 1,
                        key="dia_pago_tarjeta",
                    )
                    if st.button("\U0001F4BE Guardar configuracion de tarjeta", key="guardar_tarjeta_btn"):
                        guardar_config_tarjeta(tipo_tarjeta, int(dia_corte), int(dia_pago))
                        st.session_state["tc_bloqueada"] = True
                        st.success("Configuracion guardada y bloqueada — usa 'Actualizar' si necesitas cambiarla.")
                        st.rerun()

                    # La miniatura se actualiza al toque con lo que se va eligiendo (antes de guardar).
                    st.markdown(_banner_tarjeta_credito(tipo_tarjeta, _c["text"]), unsafe_allow_html=True)

                # El valor del dolar no es editable a mano: siempre viene de mindicador.cl. Un boton
                # fuerza a refrescarlo (la consulta esta cacheada 1 hora) por si cambio en el dia.
                valor_dolar = st.session_state.get("valor_dolar_premio") or 0.0
                dvc1, dvc2 = st.columns([3, 1])
                if valor_dolar > 0:
                    dvc1.metric("Valor del dolar hoy (CLP)", clp(valor_dolar))
                    dvc1.caption("\U0001F310 Automatico, desde mindicador.cl.")
                else:
                    dvc1.warning("No se pudo obtener el valor del dolar (revisa tu conexion a internet).")
                if dvc2.button("\U0001F504 Actualizar", key="refrescar_dolar_btn"):
                    obtener_valor_dolar.clear()
                    _valor_nuevo = obtener_valor_dolar()
                    if _valor_nuevo:
                        st.session_state["valor_dolar_premio"] = _valor_nuevo
                    st.rerun()

                hoy = datetime.date.today()
                fecha_corte = _proxima_fecha_dia(int(dia_corte), hoy)
                fecha_pago = _proxima_fecha_dia(int(dia_pago), hoy)
                dias_para_pagar = (fecha_pago - hoy).days

                if dias_para_pagar <= 5:
                    st.error(
                        f"\U000023F0 **Recordatorio**: tu tarjeta vence el **{fecha_pago.strftime('%d-%m-%Y')}** "
                        f"({'hoy' if dias_para_pagar == 0 else ('vencida' if dias_para_pagar < 0 else f'en {dias_para_pagar} dias')}). "
                        "Paga el total facturado antes de esa fecha para no generar intereses."
                    )
                else:
                    st.info(
                        f"\U0001F4C6 Tu tarjeta vence el **{fecha_pago.strftime('%d-%m-%Y')}** (en {dias_para_pagar} dias). "
                        f"Proxima fecha de corte: **{fecha_corte.strftime('%d-%m-%Y')}**."
                    )

                st.markdown("**Simula cuantos Dolares Premio ganarias con un gasto**")
                monto_simulado = st.number_input(
                    "Monto de compra a simular (CLP)", min_value=0.0, step=10000.0, format="%.0f", key="monto_simulado_dp"
                )
                if monto_simulado > 0:
                    if valor_dolar > 0:
                        dp_simulado = (monto_simulado / valor_dolar) * (TASAS_DOLARES_PREMIO[tipo_tarjeta] / 100)
                        kpi_cards(
                            [
                                (
                                    f"Dolares Premio gastando {clp(monto_simulado)} con tu {tipo_tarjeta}",
                                    f"US$ {dp_simulado:,.2f}".replace(",", "."),
                                    COLOR_PATRIMONIO,
                                    "\U00002708",
                                )
                            ]
                        )
                    else:
                        st.caption("Ingresa el valor del dolar de hoy arriba para calcular los Dolares Premio de esta simulacion.")

                intereses_por_cuenta = []
                if not df_ahorros.empty:
                    _config_temp = listar_config()
                    _ultimo_ahorro = df_ahorros.sort_values("fecha").groupby("cuenta").tail(1)
                    for _, _fila in _ultimo_ahorro.iterrows():
                        _cfg = _config_temp.get(_fila["cuenta"])
                        if _cfg and _cfg.get("tasa_base"):
                            intereses_por_cuenta.append(
                                {"cuenta": _fila["cuenta"], "intereses_mes": ganancia_periodo(_fila["saldo"], _cfg, 365 / 12)}
                            )
                intereses_mes_total = sum(f["intereses_mes"] for f in intereses_por_cuenta)

                if gasto_tarjeta_mes > 0:
                    dolares_premio = 0.0
                    if valor_dolar > 0:
                        dolares_premio = (gasto_tarjeta_mes / valor_dolar) * (TASAS_DOLARES_PREMIO[tipo_tarjeta] / 100)

                    kpi_cards(
                        [
                            ("Gasto en tarjeta este mes", clp(gasto_tarjeta_mes), COLOR_GASTOS, "\U0001F4B3"),
                            ("Dolares Premio ganados este mes", f"US$ {dolares_premio:,.2f}".replace(",", "."), COLOR_PATRIMONIO, "\U00002708"),
                            ("Intereses de tu ahorro este mes", clp(intereses_mes_total), COLOR_AHORROS, "\U0001F4B0"),
                        ]
                    )

                    if intereses_por_cuenta:
                        st.markdown("**Cuanto rento tu plata este mes, cuenta por cuenta**")
                        df_intereses = pd.DataFrame(intereses_por_cuenta).sort_values("intereses_mes", ascending=False)
                        df_intereses["intereses_mes"] = df_intereses["intereses_mes"].apply(clp)
                        st.dataframe(
                            df_intereses,
                            hide_index=True,
                            use_container_width=True,
                            column_config={"cuenta": "Cuenta", "intereses_mes": "Intereses este mes"},
                        )

                    if saldo_cc_actual >= gasto_tarjeta_mes:
                        margen = saldo_cc_actual - gasto_tarjeta_mes
                        st.success(
                            f"Tu saldo en cuenta corriente (**{clp_md(saldo_cc_actual)}**) alcanza para pagar el total "
                            f"de la tarjeta (**{clp_md(gasto_tarjeta_mes)}**) antes del **{fecha_pago.strftime('%d-%m-%Y')}** "
                            f"({dias_para_pagar} dias) — te quedarian **{clp_md(margen)}** de margen. Pagando el total "
                            "facturado (no el minimo) evitas el interes rotativo, que en Chile suele rondar 30-50% anual "
                            "— mucho mas caro que cualquier Dolar Premio o interes de ahorro."
                        )
                    else:
                        falta = gasto_tarjeta_mes - saldo_cc_actual
                        st.warning(
                            f"Tu saldo en cuenta corriente (**{clp_md(saldo_cc_actual)}**) no alcanza para cubrir el total "
                            f"de la tarjeta (**{clp_md(gasto_tarjeta_mes)}**) — te faltarian **{clp_md(falta)}** antes del "
                            f"**{fecha_pago.strftime('%d-%m-%Y')}** ({dias_para_pagar} dias). Si pagas solo una parte, el "
                            "resto queda como saldo revolvente generando interes alto — revisa si puedes cubrirlo con "
                            "ahorro antes de esa fecha."
                        )
                else:
                    st.caption("Aun no registras un pago de tarjeta este mes, asi que no se muestra el gasto real todavia.")

            with st.expander("\U0001F3E6 ¿DAP o dejarlo en una cuenta fintech?"):
                st.caption(
                    "Ingresa el monto, tasa y plazo que te dio el simulador del banco para tu Deposito a Plazo (DAP), "
                    "y lo comparamos contra dejar el mismo monto ese mismo plazo en tus cuentas configuradas. Esto es "
                    "solo una calculadora — si terminas abriendo el DAP, puedes agregarlo como una cuenta mas en "
                    "'Registrar Ahorro' (igual que Mach o Tenpo) para seguirle la pista."
                )

                tipo_tasa_dap = st.radio(
                    "¿Que tasa te muestra el simulador del banco?",
                    ["Tasa del periodo (ej: '0,30% a 30 dias', la mas comun)", "Tasa anual"],
                    key="dap_tipo_tasa",
                    horizontal=True,
                )
                tasa_es_anual = tipo_tasa_dap == "Tasa anual"

                dc1, dc2, dc3 = st.columns(3)
                monto_dap = dc1.number_input("Monto a depositar", min_value=0.0, step=100000.0, format="%.0f", key="dap_monto")
                tasa_dap = dc2.number_input(
                    "Tasa anual (%)" if tasa_es_anual else "Tasa del periodo (%)",
                    min_value=0.0, step=0.05, format="%.2f", key="dap_tasa",
                )
                plazo_dap = dc3.number_input("Plazo (dias)", min_value=1, step=1, value=90, key="dap_plazo")

                if monto_dap > 0 and tasa_dap > 0:
                    etiqueta_tasa = f"{tasa_dap:.2f}% anual" if tasa_es_anual else f"{tasa_dap:.2f}% en {int(plazo_dap)} dias"
                    opciones_comparar = [
                        {
                            "opcion": f"DAP ({etiqueta_tasa})",
                            **simular_dap(monto_dap, tasa_dap, int(plazo_dap), tasa_es_anual=tasa_es_anual),
                        }
                    ]
                    for cuenta, cfg in config_tasas.items():
                        if not cfg or not cfg.get("tasa_base"):
                            continue
                        ganancia = ganancia_periodo(monto_dap, cfg, plazo_dap)
                        opciones_comparar.append(
                            {
                                "opcion": cuenta,
                                "monto_inicial": monto_dap,
                                "ganancia": ganancia,
                                "monto_final": monto_dap + ganancia,
                                "dias": plazo_dap,
                            }
                        )

                    df_comparar = pd.DataFrame(opciones_comparar).sort_values("ganancia", ascending=False)
                    mejor = df_comparar.iloc[0]
                    st.success(
                        f"Con **{clp_md(monto_dap)}** a **{int(plazo_dap)} dias**, lo que mas te conviene es "
                        f"**{mejor['opcion']}**: terminarias con **{clp_md(mejor['monto_final'])}** "
                        f"(**{clp_md(mejor['ganancia'])}** de ganancia)."
                    )
                    df_comparar_fmt = df_comparar[["opcion", "ganancia", "monto_final"]].copy()
                    df_comparar_fmt["ganancia"] = df_comparar_fmt["ganancia"].apply(clp)
                    df_comparar_fmt["monto_final"] = df_comparar_fmt["monto_final"].apply(clp)
                    st.dataframe(
                        df_comparar_fmt,
                        hide_index=True,
                        use_container_width=True,
                        column_config={"opcion": "Opcion", "ganancia": "Ganancia", "monto_final": "Monto final"},
                    )
                    st.caption(
                        "El DAP usa interes simple sobre el plazo (como los simuladores de los bancos). Las cuentas "
                        "fintech se calculan con su tasa configurada, prorrateada al mismo plazo — en la practica esas "
                        "cuentas suelen componer mes a mes, asi que podrian rendir un poco mas de lo que muestra esta tabla."
                    )

# --- Deuda CMF ---
with tab_deuda:
    if df_deuda.empty:
        st.info("Aun no has cargado ningun informe de deuda CMF. Ve a 'Cargar Deuda CMF' para empezar.")
    else:
        with st.container(border=True, key="card_deuda"):
            st.subheader("Evolucion de mi deuda (CMF)")
            fig = px.line(df_deuda, x="fecha_actualizacion", y="deuda_total", markers=True)
            st.plotly_chart(tema(fig, COLOR_DEUDA), use_container_width=True)
