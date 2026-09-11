"""Dashboard -- version NiceGUI de vistas/4_Dashboard.py (Streamlit).

Reutiliza integramente la logica de src/ (analisis_gastos, proyeccion, metas, categorias) -- nada de
eso cambia, es Python/pandas puro. Lo que cambia es la capa de presentacion: kpi_cards/tarjeta/tabla/
banner de src.ui_nicegui.components reemplazan a st.metric/st.container(border=True)/st.dataframe/
st.success-warning-info-error, y los graficos van con src.ui_nicegui.charts.plotly_chart en vez de
st.plotly_chart.

Nota de alcance (ver resumen al usuario): la seccion de "Dolares Premio de tarjeta de credito +
simulador DAP" de la pestaña Proyeccion (la mas grande y con mas estado propio: bloqueo/edicion de
configuracion de tarjeta, cache del valor del dolar, simulador aparte) queda pendiente para un
siguiente turno -- todo lo demas de las 4 pestañas esta portado completo.
"""
import calendar
import datetime

import pandas as pd
import plotly.express as px
from nicegui import ui

from src.db import get_conn, obtener_tipos_cuenta, obtener_config_tarjeta, guardar_config_tarjeta
from src.fx_core import obtener_valor_dolar_sin_cache
from src.proyeccion import (
    listar_config,
    calcular_ganancia_anual,
    ganancia_periodo,
    tasa_efectiva,
    optimizar_asignacion,
    proyectar_saldo,
    meses_entre,
    tasa_observada_reciente,
    simular_dap,
)
from src.formato import clp
from src.ui_nicegui.cache import cache_ttl, invalidar
from src.analisis_gastos import (
    comparacion_mes_actual,
    comparacion_por_categoria,
    alertas_categoria,
    logros_ahorro,
    es_categoria_ahorro,
    es_categoria_ingreso,
    ahorro_por_mes,
    resumen_50_30_20,
)
from src.categorias import obtener_categoria_buckets, BUCKETS, SIN_CLASIFICAR
from src.metas import listar_metas, calcular_progresos, ritmo_mensual_total
from src.ui_nicegui.layout import layout
from src.ui_nicegui.theme import colores
from src.ui_nicegui.charts import plotly_chart
from src.ui_nicegui.components import kpi_cards, tarjeta, tabla, texto_muted, banner, campo_fecha
from src.ui_nicegui.editable_table import editable_table


TASAS_DOLARES_PREMIO = {
    "Visa Infinite": 0.8,
    "Visa Signature / Mastercard Black": 0.7,
    "Visa Platinum / Platinum Pyme / Mastercard Platinum": 0.6,
    "Visa Dorada, Internacional o FAN / Visa ChilePyme / Mastercard Dorada": 0.5,
}


def _proxima_fecha_dia(dia: int, desde: datetime.date) -> datetime.date:
    """Proxima fecha (a partir de 'desde' inclusive) que caiga en el dia del mes indicado."""
    ultimo_dia_mes = calendar.monthrange(desde.year, desde.month)[1]
    candidata = desde.replace(day=min(dia, ultimo_dia_mes))
    if candidata < desde:
        mes, anio = (desde.month % 12) + 1, desde.year + (1 if desde.month == 12 else 0)
        candidata = datetime.date(anio, mes, min(dia, calendar.monthrange(anio, mes)[1]))
    return candidata


def _cargar_datos():
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
    for df, col in ((df_trans, "fecha"), (df_deuda, "fecha_actualizacion"), (df_ahorros, "fecha"), (df_saldo_snapshot, "fecha")):
        if not df.empty:
            df[col] = pd.to_datetime(df[col])
    return df_trans, df_deuda, df_ahorros, df_saldo_snapshot


def _tab_gastos(df_trans: pd.DataFrame, colores_seccion: dict):
    color_gastos = colores_seccion["gastos"]
    color_ahorros = colores_seccion["ahorros"]
    color_proyeccion = colores_seccion["proyeccion"]
    c = colores()

    if df_trans.empty:
        ui.label("Aun no has cargado ninguna cartola. Ve a 'Cargar Cartola' para empezar.")
        return

    comp = comparacion_mes_actual(df_trans)
    if comp is None:
        ui.label("Necesitas transacciones de al menos 2 meses distintos para ver la comparacion mensual y las alertas.")
    else:
        with tarjeta(f"Este mes ({comp['mes_actual']}) vs el anterior ({comp['mes_anterior']})"):
            delta_txt = f"{comp['porcentaje']:+.1f}% vs mes anterior" if comp["porcentaje"] is not None else None
            delta_ok = (comp["porcentaje"] < 0) if comp["porcentaje"] is not None else None
            kpi_cards(
                [
                    (f"Gasto en {comp['mes_anterior']}", clp(comp["gasto_anterior"]), color_gastos, "\U0001F4C5"),
                    (f"Gasto en {comp['mes_actual']}", clp(comp["gasto_actual"]), color_gastos, "\U0001F4C5", delta_txt, delta_ok),
                ]
            )
            comp_cat = comparacion_por_categoria(df_trans)
            if not comp_cat.empty:
                fig = px.bar(
                    comp_cat, x="categoria", y="monto_cargo", color="mes", barmode="group",
                    category_orders={"mes": [comp["mes_anterior"], comp["mes_actual"]]},
                    title="Gasto por categoria: este mes vs el anterior",
                )
                plotly_chart(fig)

            logros = logros_ahorro(df_trans)
            if logros:
                ui.label(f"Buen dato en {comp['mes_actual']}").classes("font-bold")
                for l in logros:
                    banner(
                        "success",
                        f"**{l['categoria']}**: destinaste **{clp(l['actual'])}** este mes, un "
                        f"**{l['exceso_pct']:.0f}%** mas que tu promedio historico "
                        f"(**{clp(l['promedio'])}** en los ultimos {l['n_meses']} meses).",
                    )

            alertas = alertas_categoria(df_trans)
            if alertas:
                ui.label(f"Alertas de gasto en {comp['mes_actual']}").classes("font-bold")
                for a in alertas:
                    banner(
                        "warning",
                        f"**{a['categoria']}**: gastaste **{clp(a['actual'])}** este mes, un "
                        f"**{a['exceso_pct']:.0f}%** mas que tu promedio historico "
                        f"(**{clp(a['promedio'])}** en los ultimos {a['n_meses']} meses).",
                    )

    with tarjeta("En que gasto mi dinero"):
        fmin, fmax = df_trans["fecha"].min().date(), df_trans["fecha"].max().date()
        inicio_default = max(fmin, fmax.replace(day=1))

        with ui.row().classes("gap-3"):
            desde_input = campo_fecha(inicio_default.isoformat(), "Desde")
            hasta_input = campo_fecha(fmax.isoformat(), "Hasta")

        cuerpo_periodo = ui.column().classes("w-full gap-2")

        def _redibujar_periodo():
            desde = datetime.date.fromisoformat(desde_input.value) if desde_input.value else inicio_default
            hasta = datetime.date.fromisoformat(hasta_input.value) if hasta_input.value else fmax
            mask = (df_trans["fecha"].dt.date >= desde) & (df_trans["fecha"].dt.date <= hasta)
            df_periodo = df_trans[mask]

            cuerpo_periodo.clear()
            with cuerpo_periodo:
                es_ahorro_mask = df_periodo["categoria"].apply(es_categoria_ahorro)
                es_ingreso_mask = df_periodo["categoria"].apply(es_categoria_ingreso)
                es_gasto_mask = ~es_ahorro_mask & ~es_ingreso_mask
                total_gastos = (
                    df_periodo.loc[es_gasto_mask, "monto_cargo"].sum() - df_periodo.loc[es_gasto_mask, "monto_abono"].sum()
                )
                total_ahorro_periodo = df_periodo.loc[es_ahorro_mask, "monto_cargo"].sum()
                total_ingresos = df_periodo["monto_abono"].sum()

                kpi_cards(
                    [
                        ("Total gastos en el periodo", clp(total_gastos), color_gastos, "\U0001F4B8"),
                        ("Destinado a ahorro en el periodo", clp(total_ahorro_periodo), color_ahorros, "\U0001F4B0"),
                        ("Total abonos (entradas) en el periodo", clp(total_ingresos), color_proyeccion, "\U0001F4E5"),
                    ]
                )
                texto_muted(
                    "El gasto no incluye lo que transferiste a categorias de ahorro/inversion ni tus ingresos — y si "
                    "categorizas un reembolso en la misma categoria del gasto original, se descuenta del gasto de esa "
                    "categoria en vez de sumarse aparte."
                )

                gasto_categoria = (
                    df_periodo[es_gasto_mask].groupby("categoria", as_index=False)
                    .agg(_cargo=("monto_cargo", "sum"), _abono=("monto_abono", "sum"))
                )
                gasto_categoria["monto_cargo"] = gasto_categoria["_cargo"] - gasto_categoria["_abono"]
                gasto_categoria = gasto_categoria[["categoria", "monto_cargo"]].sort_values("monto_cargo", ascending=False)
                total_cat = gasto_categoria["monto_cargo"].sum()
                gasto_categoria["porcentaje"] = gasto_categoria["monto_cargo"] / total_cat * 100 if total_cat else 0.0

                with ui.row().classes("w-full gap-4 items-start"):
                    with ui.column().classes("flex-[3] min-w-[320px]"):
                        ui.label("Distribucion de gastos por categoria").classes("font-bold")
                        gasto_categoria_pie = gasto_categoria[gasto_categoria["monto_cargo"] > 0]
                        fig = px.pie(gasto_categoria_pie, names="categoria", values="monto_cargo", hole=0.35)
                        fig.update_traces(textinfo="percent+label")
                        fig.update_layout(height=480, showlegend=False)
                        plotly_chart(fig)
                    with ui.column().classes("flex-[2] min-w-[280px]"):
                        ui.label("Listado por categoria").classes("font-bold")
                        df_lista = gasto_categoria.rename(
                            columns={"categoria": "Categoria", "monto_cargo": "Monto", "porcentaje": "%"}
                        ).copy()
                        df_lista["Monto"] = df_lista["Monto"].apply(clp)
                        df_lista["%"] = df_lista["%"].map(lambda v: f"{v:.1f}%")
                        tabla(df_lista)

        desde_input.on_value_change(lambda _: _redibujar_periodo())
        hasta_input.on_value_change(lambda _: _redibujar_periodo())
        _redibujar_periodo()

    resumen_5030 = resumen_50_30_20(df_trans, obtener_categoria_buckets())
    if resumen_5030 and resumen_5030["total"] > 0:
        with tarjeta("Regla 50/30/20"):
            texto_muted(
                f"Compara tu gasto real de {resumen_5030['mes']} contra la regla practica de destinar 50% a "
                "necesidades, 30% a gustos y 20% a ahorro."
            )
            objetivos = {"Necesidad": 50.0, "Gusto": 30.0, "Ahorro": 20.0}
            colores_balde = {"Necesidad": color_proyeccion, "Gusto": color_gastos, "Ahorro": color_ahorros, SIN_CLASIFICAR: c["text_muted"]}
            total = resumen_5030["total"]

            def _texto_segmento(balde, pct):
                return f"{balde} {pct:.0f}%" if pct >= 5 else ""

            filas_barra = [
                {"eje": "Objetivo", "balde": b, "porcentaje": objetivos[b], "texto": _texto_segmento(b, objetivos[b])}
                for b in BUCKETS
            ]
            for b in BUCKETS:
                pct_real = resumen_5030["montos"][b] / total * 100 if total else 0.0
                filas_barra.append({"eje": "Real", "balde": b, "porcentaje": pct_real, "texto": _texto_segmento(b, pct_real)})
            pct_sin = resumen_5030["sin_clasificar"] / total * 100 if total else 0.0
            if pct_sin > 0:
                filas_barra.append({"eje": "Real", "balde": SIN_CLASIFICAR, "porcentaje": pct_sin, "texto": _texto_segmento("Sin clasificar", pct_sin)})

            fig = px.bar(
                pd.DataFrame(filas_barra), x="porcentaje", y="eje", color="balde", orientation="h", text="texto",
                category_orders={"eje": ["Objetivo", "Real"], "balde": [*BUCKETS, SIN_CLASIFICAR]},
                color_discrete_map=colores_balde,
            )
            fig.update_traces(textposition="inside", textfont_size=13, insidetextanchor="middle")
            fig.update_layout(height=160, margin=dict(t=10, b=10, l=10, r=10), showlegend=False,
                               xaxis=dict(visible=False, range=[0, 100]), yaxis=dict(visible=True, title=None), bargap=0.35)
            plotly_chart(fig, colorear=False)

            if resumen_5030["sin_clasificar"] > 0:
                banner(
                    "warning",
                    f"**{clp(resumen_5030['sin_clasificar'])}** ({pct_sin:.0f}% del gasto de {resumen_5030['mes']}) "
                    f"esta en categorias sin clasificar: {', '.join(resumen_5030['categorias_sin_clasificar'])}. "
                    "Clasificalas en la pagina Categorias para que este grafico sea mas representativo.",
                )

    with tarjeta("Evolucion del saldo en cuenta corriente"):
        fig = px.line(df_trans, x="fecha", y="saldo", color="cuenta", markers=True)
        plotly_chart(fig)


def _tab_ahorros(df_trans: pd.DataFrame, df_ahorros: pd.DataFrame, color_ahorros: str) -> pd.DataFrame:
    if df_ahorros.empty:
        ui.label("Aun no registras ningun ahorro. Ve a 'Registrar Ahorro' para empezar.")
        return pd.DataFrame()

    ultimo_por_cuenta = df_ahorros.sort_values("fecha").groupby("cuenta").tail(1)

    metas = listar_metas()
    if metas:
        with tarjeta("Metas de ahorro"):
            progresos = calcular_progresos(metas, df_ahorros, df_trans, ultimo_por_cuenta)
            for m in metas:
                p = progresos[m["id"]]
                alcance = m["cuenta"] or "total de tus ahorros"
                titulo = f"{m['nombre']} ({alcance}) — {clp(p['monto_actual'])} de {clp(m['monto_objetivo'])}"
                if p["cumplida"]:
                    banner("success", f"{titulo} — meta cumplida! 🎉")
                else:
                    ui.label(titulo)
                    ui.linear_progress(min(p["porcentaje"], 100) / 100, show_value=False).props(f'color="{color_ahorros}"')
                    detalle = f"{p['porcentaje']:.0f}% completado, faltan {clp(p['falta'])}."
                    if p["fecha_estimada"]:
                        detalle += f" A tu ritmo actual ({clp(p['ritmo_mensual'])}/mes), la alcanzarias en {p['fecha_estimada'].strftime('%B %Y')}."
                    elif p["ritmo_mensual"] is not None and p["ritmo_mensual"] <= 0:
                        detalle += " Con tu ritmo actual no vas a llegar; aumenta lo que destinas cada mes."
                    else:
                        detalle += " Aun no hay suficiente historial para estimar una fecha."
                    if m["fecha_objetivo"]:
                        detalle += f" Fecha limite: {m['fecha_objetivo']}."
                    texto_muted(detalle)

    with tarjeta():
        fig = px.line(df_ahorros, x="fecha", y="saldo", color="cuenta", markers=True, title="Evolucion del saldo de ahorros")
        plotly_chart(fig)

    serie_ahorro = ahorro_por_mes(df_trans) if not df_trans.empty else pd.Series(dtype=float)
    if len(serie_ahorro) >= 1:
        with tarjeta("Cuanto ahorre este mes"):
            texto_muted("Segun las transferencias categorizadas como ahorro/inversion en tu cartola.")
            if len(serie_ahorro) >= 2:
                mes_actual_a, mes_anterior_a = serie_ahorro.index[-1], serie_ahorro.index[-2]
                actual_a, anterior_a = float(serie_ahorro.iloc[-1]), float(serie_ahorro.iloc[-2])
                pct_a = ((actual_a - anterior_a) / anterior_a * 100) if anterior_a else None
                delta_txt_a = f"{pct_a:+.1f}% vs mes anterior" if pct_a is not None else None
                delta_ok_a = (pct_a > 0) if pct_a is not None else None
                kpi_cards(
                    [
                        (f"Ahorrado en {mes_anterior_a}", clp(anterior_a), color_ahorros, "\U0001F4B0"),
                        (f"Ahorrado en {mes_actual_a}", clp(actual_a), color_ahorros, "\U0001F4B0", delta_txt_a, delta_ok_a),
                    ]
                )
            else:
                kpi_cards([(f"Ahorrado en {serie_ahorro.index[-1]}", clp(serie_ahorro.iloc[-1]), color_ahorros, "\U0001F4B0")])

            df_serie_ahorro = serie_ahorro.reset_index()
            df_serie_ahorro.columns = ["mes", "monto"]
            df_serie_ahorro["mes"] = df_serie_ahorro["mes"].astype(str)
            fig = px.bar(df_serie_ahorro, x="mes", y="monto", title="Ahorro destinado por mes")
            plotly_chart(fig)

    if df_ahorros["rentabilidad_generada"].notna().any():
        with tarjeta("Cuanto he generado con mis ahorros"):
            rent = df_ahorros.sort_values("fecha").groupby("cuenta").tail(1)[["cuenta", "rentabilidad_generada"]].dropna()
            fig = px.bar(rent, x="cuenta", y="rentabilidad_generada", title="Rentabilidad generada a la fecha, por cuenta")
            plotly_chart(fig)
            kpi_cards([("Rentabilidad total generada", clp(rent["rentabilidad_generada"].sum()), color_ahorros, "\U0001F4C8")])

            observada = tasa_observada_reciente(df_ahorros)
            if not observada.empty:
                config_tasas_obs = listar_config()
                ui.label("¿La tasa real coincide con la que configuraste?").classes("font-bold")
                for _, fila_obs in observada.iterrows():
                    cfg_obs = config_tasas_obs.get(fila_obs["cuenta"])
                    tasa_config = cfg_obs.get("tasa_base") if cfg_obs else None
                    periodo_txt = f"del {fila_obs['dias']:.0f} dias ({fila_obs['desde'].strftime('%d-%m')} a {fila_obs['hasta'].strftime('%d-%m')})"
                    if tasa_config:
                        diferencia_obs = fila_obs["tasa_observada_%"] - tasa_config
                        if abs(diferencia_obs) >= 1.0:
                            banner(
                                "warning",
                                f"**{fila_obs['cuenta']}**: configuraste **{tasa_config:.1f}%** anual, pero tu "
                                f"rendimiento real en el ultimo periodo {periodo_txt} equivale a "
                                f"**{fila_obs['tasa_observada_%']:.1f}%** anual — revisa si te bajaron la tasa, "
                                "superaste un tope, o cambiaron las condiciones.",
                            )
                        else:
                            texto_muted(f"✅ {fila_obs['cuenta']}: tasa real observada {periodo_txt} ({fila_obs['tasa_observada_%']:.1f}% anual) en linea con lo configurado.")
                    else:
                        texto_muted(f"{fila_obs['cuenta']}: tasa real observada {periodo_txt}: {fila_obs['tasa_observada_%']:.1f}% anual.")
            else:
                texto_muted(
                    "\U0001F4A1 Completa 'Rentabilidad generada a la fecha' cada vez que registres un ahorro y aqui "
                    "vas a poder comparar la tasa real que te estan pagando contra la que configuraste."
                )

    return ultimo_por_cuenta


def _estado_tarjeta_credito() -> dict:
    """Estado compartido por las dos secciones de tarjeta de credito de esta pestaña (flotar y la
    tarjeta 'Dolares Premio'): config guardada en BD + valor del dolar (cacheado 1h, igual que en la
    version Streamlit, pero con un cache TTL propio en vez de @st.cache_data)."""
    cfg_guardado = obtener_config_tarjeta()
    return {
        "tipo": (cfg_guardado or {}).get("tipo_tarjeta") or next(iter(TASAS_DOLARES_PREMIO)),
        "dia_corte": (cfg_guardado or {}).get("dia_corte") or 1,
        "dia_pago": (cfg_guardado or {}).get("dia_pago") or 1,
        "bloqueada": bool(cfg_guardado and cfg_guardado.get("tipo_tarjeta")),
        "valor_dolar": cache_ttl("valor_dolar", 3600, obtener_valor_dolar_sin_cache) or 0.0,
    }


def _gasto_tarjeta_mes(df_trans: pd.DataFrame) -> float:
    if df_trans.empty:
        return 0.0
    comp = comparacion_mes_actual(df_trans)
    if comp is None:
        return 0.0
    comp_cat = comparacion_por_categoria(df_trans)
    if comp_cat.empty:
        return 0.0
    fila = comp_cat[(comp_cat["categoria"] == "Pago tarjeta de credito") & (comp_cat["mes"] == comp["mes_actual"])]
    return float(fila["monto_cargo"].iloc[0]) if not fila.empty else 0.0


def _seccion_flotar(df_trans, ultimo_por_cuenta, config_tasas, estado_tc, colores_seccion):
    saldo_cc_actual = 0.0
    if not df_trans.empty:
        saldo_cc_actual = float(df_trans.sort_values("fecha").groupby("cuenta").tail(1)["saldo"].sum())
    if not (saldo_cc_actual > 0 and any(cfg.get("tasa_base") for cfg in config_tasas.values())):
        return

    with tarjeta("\U0001F4B0 ¿Me conviene mover mi saldo a una fintech mientras uso la tarjeta de credito?"):
        texto_muted(
            "Tu cuenta corriente no genera interes. Si pagas el dia a dia con la tarjeta de credito y dejas este "
            "saldo en una cuenta remunerada hasta la fecha de pago, genera algo en vez de nada — siempre que la "
            "devuelvas a tiempo para pagar el total facturado."
        )
        cfg_tc = obtener_config_tarjeta()
        if cfg_tc and cfg_tc.get("dia_pago"):
            hoy = datetime.date.today()
            fecha_pago_tc = _proxima_fecha_dia(int(cfg_tc["dia_pago"]), hoy)
            dias_flotar = max((fecha_pago_tc - hoy).days, 1)
            kpi_cards([
                ("Saldo cuenta corriente", clp(saldo_cc_actual), colores_seccion["proyeccion"], "\U0001F4B3"),
                ("Dias hasta que necesites pagar la tarjeta", f"{dias_flotar} dias",
                 colores_seccion["deuda"] if dias_flotar <= 5 else colores_seccion["ahorros"], "\U0001F4C6",
                 fecha_pago_tc.strftime("Vence %d-%m-%Y"), dias_flotar > 5),
            ])
        else:
            dias_flotar = 30
            kpi_cards([("Saldo cuenta corriente", clp(saldo_cc_actual), colores_seccion["proyeccion"], "\U0001F4B3")])
            texto_muted("No configuraste la fecha de pago de tu tarjeta (mas abajo), asi que se usan 30 dias por defecto.")

        tipos_flotar = obtener_tipos_cuenta()
        filas_flotar = [{"opcion": "Dejarlo en cuenta corriente (no genera interes)", "ganancia": 0.0}]
        for cuenta, cfg in config_tasas.items():
            if not cfg or not cfg.get("tasa_base") or tipos_flotar.get(cuenta, "ahorro") != "movimiento":
                continue
            saldo_existente = 0.0
            if not ultimo_por_cuenta.empty and cuenta in ultimo_por_cuenta["cuenta"].values:
                saldo_existente = float(ultimo_por_cuenta.loc[ultimo_por_cuenta["cuenta"] == cuenta, "saldo"].iloc[0])
            ganancia_marginal = ganancia_periodo(saldo_existente + saldo_cc_actual, cfg, dias_flotar) - ganancia_periodo(saldo_existente, cfg, dias_flotar)
            filas_flotar.append({"opcion": cuenta, "ganancia": ganancia_marginal})
        df_flotar = pd.DataFrame(filas_flotar).sort_values("ganancia", ascending=False)
        mejor_flotar = df_flotar.iloc[0]

        if mejor_flotar["opcion"] != "Dejarlo en cuenta corriente (no genera interes)":
            banner(
                "success",
                f"Si mueves tu saldo actual (**{clp(saldo_cc_actual)}**) a **{mejor_flotar['opcion']}** por "
                f"**{int(dias_flotar)} dias**, generarias aprox. **{clp(mejor_flotar['ganancia'])}** extra — algo en "
                "vez de nada, mientras cubres tus gastos con la tarjeta.",
            )
        else:
            ui.label("Con el saldo que ya tienen tus cuentas 'movimiento', agregar mas no generaria una ganancia extra relevante.")

        df_flotar_fmt = df_flotar.copy()
        df_flotar_fmt["ganancia"] = df_flotar_fmt["ganancia"].apply(clp)
        tabla(df_flotar_fmt, {"opcion": "Opcion", "ganancia": f"Ganancia en {int(dias_flotar)} dias"})

        cuentas_abono_mensual = [
            c for c, cfg in config_tasas.items()
            if cfg and cfg.get("tasa_base") and cfg.get("abono_mensual") and tipos_flotar.get(c, "ahorro") == "movimiento"
        ]
        if cuentas_abono_mensual:
            texto_muted(
                f"⏳ {', '.join(cuentas_abono_mensual)} abona el interes recien los primeros dias del mes "
                "siguiente (no dia a dia), asi que esa ganancia puede que no se refleje antes de la fecha de pago."
            )

        if estado_tc["tipo"] and estado_tc["valor_dolar"]:
            dp_flotar = (saldo_cc_actual / estado_tc["valor_dolar"]) * (TASAS_DOLARES_PREMIO[estado_tc["tipo"]] / 100)
            kpi_cards([(
                f"Dolares Premio usando {clp(saldo_cc_actual)} en tu {estado_tc['tipo']}",
                f"US$ {dp_flotar:,.2f}".replace(",", "."), colores_seccion["patrimonio"], "\U00002708",
            )])
            texto_muted("Ganas por los dos lados: el interes de la fintech (arriba) y los Dolares Premio de la tarjeta al usar la misma plata.")
        else:
            texto_muted("Configura el tipo de tarjeta y el valor del dolar mas abajo para ver tambien cuantos Dolares Premio generarias usando este mismo saldo en la tarjeta.")


def _seccion_tarjeta_credito(estado_tc, df_trans, ultimo_por_cuenta_ahorro, config_tasas, gasto_tarjeta_mes, colores_seccion):
    with tarjeta():
        ui.label("\U0001F4B3 Dolares Premio y disciplina de pago").classes("text-lg font-bold")
        texto_muted(
            "La app no lee la cartola de la tarjeta de credito, solo tu cuenta corriente — el gasto se estima con lo "
            "que le transferiste este mes (categoria 'Pago tarjeta de credito'), asumiendo que pagas el total "
            "facturado y no dejas saldo revolvente."
        )

        @ui.refreshable
        def _config_tarjeta():
            if estado_tc["bloqueada"]:
                with ui.row().classes("gap-8"):
                    for etiqueta, valor in (("Tipo de tarjeta", estado_tc["tipo"]), ("Dia de corte", estado_tc["dia_corte"]), ("Dia limite de pago", estado_tc["dia_pago"])):
                        with ui.column().classes("gap-0"):
                            texto_muted(etiqueta)
                            ui.label(str(valor)).classes("font-bold")

                def _desbloquear():
                    estado_tc["bloqueada"] = False
                    _config_tarjeta.refresh()

                ui.button("✏️ Actualizar configuracion de tarjeta", on_click=_desbloquear).props("outline")
            else:
                opciones_tc = list(TASAS_DOLARES_PREMIO.keys())
                sel_tipo = ui.select(opciones_tc, value=estado_tc["tipo"], label="Tipo de tarjeta (para calcular los beneficios)").classes("w-full")
                with ui.row().classes("gap-3 w-full"):
                    num_corte = ui.number("Dia de corte", value=estado_tc["dia_corte"], min=1, max=31, step=1)
                    num_pago = ui.number("Dia limite de pago", value=estado_tc["dia_pago"], min=1, max=31, step=1)

                def _guardar():
                    guardar_config_tarjeta(sel_tipo.value, int(num_corte.value or 1), int(num_pago.value or 1))
                    estado_tc.update(tipo=sel_tipo.value, dia_corte=int(num_corte.value or 1), dia_pago=int(num_pago.value or 1), bloqueada=True)
                    _config_tarjeta.refresh()

                ui.button("\U0001F4BE Guardar configuracion de tarjeta", on_click=_guardar).props("color=primary")

        _config_tarjeta()

        contenedor_dolar = ui.row().classes("items-center gap-4")

        def _redibujar_dolar():
            contenedor_dolar.clear()
            with contenedor_dolar:
                if estado_tc["valor_dolar"] > 0:
                    with ui.column().classes("gap-0"):
                        ui.label(f"Valor del dolar hoy (CLP): {clp(estado_tc['valor_dolar'])}").classes("font-bold")
                        texto_muted("\U0001F310 Automatico, desde mindicador.cl.")
                else:
                    banner("warning", "No se pudo obtener el valor del dolar (revisa tu conexion a internet).")

                def _refrescar():
                    invalidar("valor_dolar")
                    estado_tc["valor_dolar"] = cache_ttl("valor_dolar", 3600, obtener_valor_dolar_sin_cache) or 0.0
                    _redibujar_dolar()

                ui.button("\U0001F504 Actualizar", on_click=_refrescar).props("outline dense")

        _redibujar_dolar()

        hoy = datetime.date.today()
        fecha_corte = _proxima_fecha_dia(int(estado_tc["dia_corte"]), hoy)
        fecha_pago = _proxima_fecha_dia(int(estado_tc["dia_pago"]), hoy)
        dias_para_pagar = (fecha_pago - hoy).days
        if dias_para_pagar <= 5:
            estado_txt = "hoy" if dias_para_pagar == 0 else ("vencida" if dias_para_pagar < 0 else f"en {dias_para_pagar} dias")
            banner("error", f"Recordatorio: tu tarjeta vence el **{fecha_pago.strftime('%d-%m-%Y')}** ({estado_txt}). Paga el total facturado antes de esa fecha para no generar intereses.")
        else:
            banner("info", f"Tu tarjeta vence el **{fecha_pago.strftime('%d-%m-%Y')}** (en {dias_para_pagar} dias). Proxima fecha de corte: **{fecha_corte.strftime('%d-%m-%Y')}**.")

        ui.label("Simula cuantos Dolares Premio ganarias con un gasto").classes("font-bold")
        monto_sim_input = ui.number("Monto de compra a simular (CLP)", value=0.0, min=0.0, step=10000.0, format="%.0f")
        resultado_sim = ui.row()

        def _redibujar_sim():
            resultado_sim.clear()
            monto = monto_sim_input.value or 0
            if monto > 0 and estado_tc["valor_dolar"] > 0:
                dp = (monto / estado_tc["valor_dolar"]) * (TASAS_DOLARES_PREMIO[estado_tc["tipo"]] / 100)
                with resultado_sim:
                    kpi_cards([(f"Dolares Premio gastando {clp(monto)} con tu {estado_tc['tipo']}", f"US$ {dp:,.2f}".replace(",", "."), colores_seccion["patrimonio"], "\U00002708")])
            elif monto > 0:
                with resultado_sim:
                    texto_muted("Ingresa el valor del dolar de hoy arriba para calcular los Dolares Premio de esta simulacion.")

        monto_sim_input.on_value_change(lambda _: _redibujar_sim())

        intereses_por_cuenta = []
        for _, fila in ultimo_por_cuenta_ahorro.iterrows():
            cfg = config_tasas.get(fila["cuenta"])
            if cfg and cfg.get("tasa_base"):
                intereses_por_cuenta.append({"cuenta": fila["cuenta"], "intereses_mes": ganancia_periodo(fila["saldo"], cfg, 365 / 12)})
        intereses_mes_total = sum(f["intereses_mes"] for f in intereses_por_cuenta)

        saldo_cc_actual = 0.0
        if not df_trans.empty:
            saldo_cc_actual = float(df_trans.sort_values("fecha").groupby("cuenta").tail(1)["saldo"].sum())

        if gasto_tarjeta_mes > 0:
            dolares_premio = (gasto_tarjeta_mes / estado_tc["valor_dolar"]) * (TASAS_DOLARES_PREMIO[estado_tc["tipo"]] / 100) if estado_tc["valor_dolar"] > 0 else 0.0
            kpi_cards([
                ("Gasto en tarjeta este mes", clp(gasto_tarjeta_mes), colores_seccion["gastos"], "\U0001F4B3"),
                ("Dolares Premio ganados este mes", f"US$ {dolares_premio:,.2f}".replace(",", "."), colores_seccion["patrimonio"], "\U00002708"),
                ("Intereses de tu ahorro este mes", clp(intereses_mes_total), colores_seccion["ahorros"], "\U0001F4B0"),
            ])
            if intereses_por_cuenta:
                ui.label("Cuanto rindio tu plata este mes, cuenta por cuenta").classes("font-bold")
                df_int = pd.DataFrame(intereses_por_cuenta).sort_values("intereses_mes", ascending=False)
                df_int["intereses_mes"] = df_int["intereses_mes"].apply(clp)
                tabla(df_int, {"cuenta": "Cuenta", "intereses_mes": "Intereses este mes"})

            if saldo_cc_actual >= gasto_tarjeta_mes:
                margen = saldo_cc_actual - gasto_tarjeta_mes
                banner(
                    "success",
                    f"Tu saldo en cuenta corriente (**{clp(saldo_cc_actual)}**) alcanza para pagar el total de la "
                    f"tarjeta (**{clp(gasto_tarjeta_mes)}**) antes del **{fecha_pago.strftime('%d-%m-%Y')}** "
                    f"({dias_para_pagar} dias) — te quedarian **{clp(margen)}** de margen.",
                )
            else:
                falta = gasto_tarjeta_mes - saldo_cc_actual
                banner(
                    "warning",
                    f"Tu saldo en cuenta corriente (**{clp(saldo_cc_actual)}**) no alcanza para cubrir el total de la "
                    f"tarjeta (**{clp(gasto_tarjeta_mes)}**) — te faltarian **{clp(falta)}** antes del "
                    f"**{fecha_pago.strftime('%d-%m-%Y')}** ({dias_para_pagar} dias).",
                )
        else:
            texto_muted("Aun no registras un pago de tarjeta este mes, asi que no se muestra el gasto real todavia.")

    with ui.expansion("\U0001F3E6 ¿DAP o dejarlo en una cuenta fintech?").classes("w-full"):
        texto_muted(
            "Ingresa el monto, tasa y plazo que te dio el simulador del banco para tu Deposito a Plazo (DAP), y lo "
            "comparamos contra dejar el mismo monto ese mismo plazo en tus cuentas configuradas."
        )
        tipo_tasa_radio = ui.radio(
            ["Tasa del periodo (ej: '0,30% a 30 dias', la mas comun)", "Tasa anual"],
            value="Tasa del periodo (ej: '0,30% a 30 dias', la mas comun)",
        ).props("inline")
        with ui.row().classes("gap-3 w-full"):
            monto_dap_input = ui.number("Monto a depositar", value=0.0, min=0.0, step=100000.0, format="%.0f")
            tasa_dap_input = ui.number("Tasa (%)", value=0.0, min=0.0, step=0.05, format="%.2f")
            plazo_dap_input = ui.number("Plazo (dias)", value=90, min=1, step=1)
        resultado_dap = ui.column().classes("w-full gap-2")

        def _redibujar_dap():
            resultado_dap.clear()
            monto_dap = monto_dap_input.value or 0
            tasa_dap = tasa_dap_input.value or 0
            plazo_dap = plazo_dap_input.value or 90
            tasa_es_anual = tipo_tasa_radio.value == "Tasa anual"
            if monto_dap <= 0 or tasa_dap <= 0:
                return
            with resultado_dap:
                etiqueta_tasa = f"{tasa_dap:.2f}% anual" if tasa_es_anual else f"{tasa_dap:.2f}% en {int(plazo_dap)} dias"
                opciones_comparar = [{"opcion": f"DAP ({etiqueta_tasa})", **simular_dap(monto_dap, tasa_dap, int(plazo_dap), tasa_es_anual=tasa_es_anual)}]
                for cuenta, cfg in config_tasas.items():
                    if not cfg or not cfg.get("tasa_base"):
                        continue
                    ganancia = ganancia_periodo(monto_dap, cfg, plazo_dap)
                    opciones_comparar.append({"opcion": cuenta, "monto_inicial": monto_dap, "ganancia": ganancia, "monto_final": monto_dap + ganancia, "dias": plazo_dap})
                df_comparar = pd.DataFrame(opciones_comparar).sort_values("ganancia", ascending=False)
                mejor = df_comparar.iloc[0]
                banner("success", f"Con **{clp(monto_dap)}** a **{int(plazo_dap)} dias**, lo que mas te conviene es **{mejor['opcion']}**: terminarias con **{clp(mejor['monto_final'])}** (**{clp(mejor['ganancia'])}** de ganancia).")
                df_fmt = df_comparar[["opcion", "ganancia", "monto_final"]].copy()
                df_fmt["ganancia"] = df_fmt["ganancia"].apply(clp)
                df_fmt["monto_final"] = df_fmt["monto_final"].apply(clp)
                tabla(df_fmt, {"opcion": "Opcion", "ganancia": "Ganancia", "monto_final": "Monto final"})
                texto_muted("El DAP usa interes simple sobre el plazo. Las cuentas fintech suelen componer mes a mes, asi que podrian rendir un poco mas de lo que muestra esta tabla.")

        for w in (monto_dap_input, tasa_dap_input, plazo_dap_input, tipo_tasa_radio):
            w.on_value_change(lambda _: _redibujar_dap())


def _tab_proyeccion(df_trans: pd.DataFrame, ultimo_por_cuenta: pd.DataFrame, color_proyeccion: str):
    if ultimo_por_cuenta.empty:
        ui.label("Aun no registras ningun ahorro. Ve a 'Registrar Ahorro' para empezar.")
        return

    with tarjeta("Donde tengo mis ahorros"):
        fig = px.pie(ultimo_por_cuenta, names="cuenta", values="saldo", title="Distribucion actual de ahorros por cuenta")
        plotly_chart(fig)

        config_tasas_marginal = listar_config()
        cuentas_con_tasa_marginal = {c: cfg for c, cfg in config_tasas_marginal.items() if cfg and cfg.get("tasa_base")}
        if cuentas_con_tasa_marginal:
            ui.label("¿A que cuenta conviene ingresar tu proximo ahorro?").classes("font-bold")
            monto_input = ui.number("Monto que vas a ahorrar", value=100000.0, min=0.0, step=10000.0, format="%.0f")
            resultado_marginal = ui.column().classes("w-full gap-2")

            def _redibujar_marginal():
                monto = monto_input.value or 0.0
                resultado_marginal.clear()
                if monto <= 0:
                    return
                with resultado_marginal:
                    filas_marginal = []
                    for cuenta, cfg in cuentas_con_tasa_marginal.items():
                        saldo_actual_cta = 0.0
                        if cuenta in ultimo_por_cuenta["cuenta"].values:
                            saldo_actual_cta = float(ultimo_por_cuenta.loc[ultimo_por_cuenta["cuenta"] == cuenta, "saldo"].iloc[0])
                        ganancia_extra = calcular_ganancia_anual(saldo_actual_cta + monto, cfg) - calcular_ganancia_anual(saldo_actual_cta, cfg)
                        filas_marginal.append({"cuenta": cuenta, "saldo_actual": saldo_actual_cta, "ganancia_extra_1a": ganancia_extra, "tasa_marginal_%": ganancia_extra / monto * 100})
                    df_marginal = pd.DataFrame(filas_marginal).sort_values("ganancia_extra_1a", ascending=False)
                    mejor_marginal = df_marginal.iloc[0]
                    banner(
                        "success",
                        f"Deposita tu proximo ahorro (**{clp(monto)}**) en **{mejor_marginal['cuenta']}** — hoy es la "
                        f"que te da la mejor tasa marginal (**{mejor_marginal['tasa_marginal_%']:.2f}% anual efectiva**), "
                        f"generarias aprox. **{clp(mejor_marginal['ganancia_extra_1a'])}** extra en un año.",
                    )
                    df_fmt = df_marginal.copy()
                    df_fmt["saldo_actual"] = df_fmt["saldo_actual"].apply(clp)
                    df_fmt["ganancia_extra_1a"] = df_fmt["ganancia_extra_1a"].apply(clp)
                    df_fmt["tasa_marginal_%"] = df_fmt["tasa_marginal_%"].map(lambda v: f"{v:.2f}%")
                    tabla(df_fmt, {"cuenta": "Cuenta", "saldo_actual": "Saldo actual", "ganancia_extra_1a": "Ganancia extra en 1 año", "tasa_marginal_%": "Tasa marginal"})

            monto_input.on_value_change(lambda _: _redibujar_marginal())
            _redibujar_marginal()

    config_tasas = listar_config()
    if not any(cfg.get("tasa_base") for cfg in config_tasas.values()):
        ui.label("Configura una tasa de interes anual para tus cuentas en 'Registrar Ahorro' para ver la proyeccion aqui.")
        return

    with tarjeta("Cuanto generaria si dejo la plata donde esta"):
        texto_muted("Proyeccion a 1 año, segun la tasa que configuraste en 'Registrar Ahorro' y el saldo actual de cada cuenta.")
        proy = ultimo_por_cuenta.copy()
        proy["config"] = proy["cuenta"].apply(lambda c: config_tasas.get(c))
        proy["tasa_efectiva_%"] = proy.apply(lambda r: tasa_efectiva(r["saldo"], r["config"]), axis=1)
        proy["ganancia_estimada_1a"] = proy.apply(lambda r: calcular_ganancia_anual(r["saldo"], r["config"]), axis=1)
        proy = proy[proy["ganancia_estimada_1a"] > 0][["cuenta", "saldo", "tasa_efectiva_%", "ganancia_estimada_1a"]]

        ganancia_actual_total = 0.0
        if proy.empty:
            ui.label("Ninguna de tus cuentas con saldo tiene una tasa configurada mayor a 0.")
        else:
            proy = proy.sort_values("ganancia_estimada_1a", ascending=False)
            df_proy = proy.copy()
            df_proy["saldo"] = df_proy["saldo"].apply(clp)
            df_proy["tasa_efectiva_%"] = df_proy["tasa_efectiva_%"].map(lambda v: f"{v:.2f}%")
            df_proy["ganancia_estimada_1a"] = df_proy["ganancia_estimada_1a"].apply(clp)
            tabla(df_proy, {"cuenta": "Cuenta", "saldo": "Saldo actual", "tasa_efectiva_%": "Tasa anual efectiva", "ganancia_estimada_1a": "Ganancia estimada en 1 año"})
            ganancia_actual_total = proy["ganancia_estimada_1a"].sum()
            kpi_cards([("Ganancia total estimada en 1 año (distribucion actual)", clp(ganancia_actual_total), color_proyeccion, "\U0001F4C8")])
            texto_muted("Estimacion simple con interes sobre el saldo actual; no considera aportes, retiros ni cambios de tasa futuros.")

    if not proy.empty:
        with tarjeta("Proyeccion a una fecha"):
            texto_muted(
                "Elige una fecha y estima cuanto tendrias ahorrado y cuanto seria intereses, si las tasas se "
                "mantienen y sigues aportando a tu ritmo (mes a mes, no lineal, para reflejar bien los tramos con tope)."
            )
            fecha_default = datetime.date.today() + datetime.timedelta(days=365)
            fecha_input = campo_fecha(fecha_default.isoformat(), "Proyectar hasta")
            resultado_fecha = ui.column().classes("w-full gap-3")

            def _redibujar_fecha():
                fecha_proyeccion = datetime.date.fromisoformat(fecha_input.value) if fecha_input.value else fecha_default
                meses_proy = meses_entre(datetime.date.today(), fecha_proyeccion)
                resultado_fecha.clear()
                with resultado_fecha:
                    filas_aporte = []
                    for _, fila in ultimo_por_cuenta.iterrows():
                        cfg = config_tasas.get(fila["cuenta"])
                        if not cfg or not cfg.get("tasa_base"):
                            continue
                        filas_aporte.append({"cuenta": fila["cuenta"], "saldo_actual": clp(fila["saldo"]), "aporte_mensual_estimado": 0.0})

                    if not filas_aporte:
                        ui.label("Ninguna de tus cuentas con saldo tiene una tasa configurada mayor a 0.")
                        return

                    ritmo_cartola = ritmo_mensual_total(df_trans) if not df_trans.empty else None
                    if ritmo_cartola is not None:
                        texto_muted(
                            f"Referencia de tu cartola: en promedio destinaste {clp(ritmo_cartola)}/mes a "
                            "ahorro/inversion en los ultimos meses (no se reparte solo entre tus cuentas, usalo "
                            "como guia para ajustar los montos de abajo a mano)."
                        )

                    def _guardar_aportes(originales, editados):
                        filas_proy_fecha = []
                        for fila_orig, fila_edit in zip(originales, editados):
                            cfg = config_tasas.get(fila_orig["cuenta"])
                            saldo_actual = next(f["saldo"] for f in ultimo_por_cuenta.to_dict("records") if f["cuenta"] == fila_orig["cuenta"])
                            aporte = float(fila_edit.get("aporte_mensual_estimado") or 0)
                            r = proyectar_saldo(saldo_actual, cfg, aporte, meses_proy)
                            filas_proy_fecha.append({
                                "cuenta": fila_orig["cuenta"], "saldo_actual": saldo_actual, "aporte_mensual_estimado": aporte,
                                "total_aportado": r["total_aportado"], "intereses_estimados": r["total_intereses"], "saldo_proyectado": r["saldo_proyectado"],
                            })
                        _mostrar_resultado_fecha(filas_proy_fecha, meses_proy, fecha_proyeccion)

                    editable_table(
                        filas_aporte,
                        [
                            {"campo": "cuenta", "titulo": "Cuenta", "tipo": "solo_lectura"},
                            {"campo": "saldo_actual", "titulo": "Saldo actual", "tipo": "solo_lectura"},
                            {"campo": "aporte_mensual_estimado", "titulo": "Aporte mensual estimado (editable)", "tipo": "numero"},
                        ],
                        _guardar_aportes,
                        texto_boton="Recalcular con estos aportes",
                    )
                    texto_muted("Parte en $0 -- escribe un monto a mano si quieres proyectar aportes futuros para alguna cuenta, y presiona 'Recalcular'.")

            def _mostrar_resultado_fecha(filas_proy_fecha, meses_proy, fecha_proyeccion):
                df_proy_fecha = pd.DataFrame(filas_proy_fecha).sort_values("saldo_proyectado", ascending=False)
                total_actual = df_proy_fecha["saldo_actual"].sum()
                total_aportado = df_proy_fecha["total_aportado"].sum()
                total_intereses = df_proy_fecha["intereses_estimados"].sum()
                total_proyectado = df_proy_fecha["saldo_proyectado"].sum()
                kpi_cards([
                    ("Saldo inicial (hoy)", clp(total_actual), color_proyeccion, "\U0001F4B0"),
                    (f"A aportar ({meses_proy} meses)", clp(total_aportado), color_proyeccion, "\U00002795"),
                    ("Ganancia (intereses)", clp(total_intereses), color_proyeccion, "\U0001F4C8"),
                    (f"Saldo final a {fecha_proyeccion}", clp(total_proyectado), color_proyeccion, "\U0001F3C1"),
                ])
                df_fmt = df_proy_fecha.copy()
                for col in ("saldo_actual", "aporte_mensual_estimado", "total_aportado", "intereses_estimados", "saldo_proyectado"):
                    df_fmt[col] = df_fmt[col].apply(clp)
                tabla(df_fmt, {"cuenta": "Cuenta", "saldo_actual": "Saldo actual", "aporte_mensual_estimado": "Aporte mensual",
                                "total_aportado": f"Total a aportar ({meses_proy} meses)", "intereses_estimados": "Intereses estimados",
                                "saldo_proyectado": f"Saldo proyectado a {fecha_proyeccion}"})

            fecha_input.on_value_change(lambda _: _redibujar_fecha())
            _redibujar_fecha()

        with tarjeta("¿Como repartir tu plata entre tus cuentas para maximizar la ganancia?"):
            tipos_cuenta = obtener_tipos_cuenta()
            cuentas_movimiento = {c for c in ultimo_por_cuenta["cuenta"] if tipos_cuenta.get(c, "ahorro") == "movimiento"}
            total_ahorros = ultimo_por_cuenta[ultimo_por_cuenta["cuenta"].isin(cuentas_movimiento)]["saldo"].sum()
            config_tasas_reparto = {c: cfg for c, cfg in config_tasas.items() if c in cuentas_movimiento}
            reparto = optimizar_asignacion(total_ahorros, config_tasas_reparto)

            if reparto:
                ganancia_optima = sum(r["ganancia"] for r in reparto)
                diferencia = ganancia_optima - ganancia_actual_total
                if diferencia > 1:
                    detalle = ", ".join(f"**{clp(r['monto_asignado'])}** en **{r['cuenta']}**" for r in reparto)
                    banner("success", f"Repartiendo tu total (**{clp(total_ahorros)}**) asi: {detalle} — generarias aprox. **{clp(ganancia_optima)}** al año, **{clp(diferencia)}** mas que con la distribucion actual.")
                else:
                    ui.label("Con la distribucion actual ya estas obteniendo el mejor resultado posible entre tus cuentas configuradas.")

                df_reparto = pd.DataFrame(reparto)
                df_reparto["monto_asignado"] = df_reparto["monto_asignado"].apply(clp)
                df_reparto["ganancia"] = df_reparto["ganancia"].apply(clp)
                tabla(df_reparto, {"cuenta": "Cuenta", "monto_asignado": "Monto sugerido", "ganancia": "Ganancia de ese tramo"})
                texto_muted(
                    "El reparto llena primero los tramos con mejor tasa y pone el resto en la siguiente mejor tasa "
                    "disponible. No considera topes que la app no te haya informado, asi que confirma las condiciones "
                    "reales antes de mover dinero."
                )

    estado_tc = _estado_tarjeta_credito()
    _seccion_flotar(df_trans, ultimo_por_cuenta, config_tasas, estado_tc, {"proyeccion": color_proyeccion, "deuda": colores()["danger"], "ahorros": colores()["success"], "patrimonio": colores()["accent_purple"]})
    gasto_tarjeta_mes = _gasto_tarjeta_mes(df_trans)
    _seccion_tarjeta_credito(estado_tc, df_trans, ultimo_por_cuenta, config_tasas, gasto_tarjeta_mes, {"gastos": colores()["accent_orange"], "ahorros": colores()["success"], "patrimonio": colores()["accent_purple"]})


def _tab_deuda(df_deuda: pd.DataFrame, color_deuda: str):
    if df_deuda.empty:
        ui.label("Aun no has cargado ningun informe de deuda CMF. Ve a 'Cargar Deuda CMF' para empezar.")
        return
    with tarjeta("Evolucion de mi deuda (CMF)"):
        fig = px.line(df_deuda, x="fecha_actualizacion", y="deuda_total", markers=True)
        plotly_chart(fig, color_deuda)


@ui.page("/dashboard")
def pagina_dashboard():
    with layout("/dashboard"):
        c = colores()
        colores_seccion = {
            "gastos": c["accent_orange"], "ahorros": c["success"], "proyeccion": c["accent_blue"],
            "deuda": c["danger"], "patrimonio": c["accent_purple"],
        }
        ui.label("Dashboard Financiero").classes("text-2xl font-bold")

        df_trans, df_deuda, df_ahorros, df_saldo_snapshot = _cargar_datos()

        if df_trans.empty and df_deuda.empty and df_ahorros.empty:
            ui.label("Aun no hay datos cargados. Ve a 'Cargar Cartola', 'Cargar Deuda CMF' o 'Registrar Ahorro' para empezar.")
            return

        ultimo_trans = (
            df_trans.sort_values("fecha").groupby("cuenta").tail(1)[["cuenta", "fecha", "saldo"]]
            if not df_trans.empty else pd.DataFrame(columns=["cuenta", "fecha", "saldo"])
        )
        ultimo_snapshot = (
            df_saldo_snapshot.sort_values("fecha").groupby("cuenta").tail(1)[["cuenta", "fecha", "saldo"]]
            if not df_saldo_snapshot.empty else pd.DataFrame(columns=["cuenta", "fecha", "saldo"])
        )
        saldo_actual_por_cuenta = pd.concat([ultimo_trans, ultimo_snapshot])
        if not saldo_actual_por_cuenta.empty:
            saldo_actual_por_cuenta = saldo_actual_por_cuenta.sort_values("fecha").groupby("cuenta").tail(1)
        saldo_cc_actual = saldo_actual_por_cuenta["saldo"].sum() if not saldo_actual_por_cuenta.empty else 0
        ahorros_actual = df_ahorros.sort_values("fecha").groupby("cuenta").tail(1)["saldo"].sum() if not df_ahorros.empty else 0
        deuda_actual = df_deuda.sort_values("fecha_actualizacion").tail(1)["deuda_total"].iloc[0] if not df_deuda.empty else 0

        kpi_cards([
            ("Saldo cuenta corriente", clp(saldo_cc_actual), colores_seccion["proyeccion"], "\U0001F4B3"),
            ("Ahorros / inversiones", clp(ahorros_actual), colores_seccion["ahorros"], "\U0001F4B0"),
            ("Deuda CMF vigente", clp(deuda_actual), colores_seccion["deuda"], "\U0001F4C4"),
            ("Patrimonio neto estimado", clp(saldo_cc_actual + ahorros_actual - deuda_actual), colores_seccion["patrimonio"], "\U00002696"),
        ])

        with ui.tabs().classes("w-full") as tabs:
            t_gastos = ui.tab("gastos", label="\U0001F4B8 Gastos")
            t_ahorros = ui.tab("ahorros", label="\U0001F4B0 Ahorros")
            t_proyeccion = ui.tab("proyeccion", label="\U0001F4C8 Proyeccion")
            t_deuda = ui.tab("deuda", label="\U0001F4C4 Deuda CMF")
        with ui.tab_panels(tabs, value=t_gastos).classes("w-full"):
            with ui.tab_panel(t_gastos):
                _tab_gastos(df_trans, colores_seccion)
            with ui.tab_panel(t_ahorros):
                ultimo_por_cuenta = _tab_ahorros(df_trans, df_ahorros, colores_seccion["ahorros"])
            with ui.tab_panel(t_proyeccion):
                _tab_proyeccion(df_trans, ultimo_por_cuenta if not df_ahorros.empty else pd.DataFrame(), colores_seccion["proyeccion"])
            with ui.tab_panel(t_deuda):
                _tab_deuda(df_deuda, colores_seccion["deuda"])
