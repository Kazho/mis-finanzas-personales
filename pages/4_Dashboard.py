import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from src.db import get_conn, init_db
from src.proyeccion import (
    listar_config,
    calcular_ganancia_anual,
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
    ahorro_por_mes,
)
from src.metas import listar_metas, calcular_progresos, ritmo_mensual_cuenta

st.set_page_config(page_title="Dashboard", page_icon="\U0001F4C8", layout="wide")
init_db()

st.title("Dashboard Financiero")

with get_conn() as conn:
    df_trans = pd.read_sql_query(
        """
        SELECT t.fecha, t.descripcion, t.sucursal, t.monto_cargo, t.monto_abono, t.saldo, t.categoria, c.nombre AS cuenta
        FROM transacciones t JOIN cuentas c ON c.id = t.cuenta_id
        ORDER BY t.fecha
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

if df_trans.empty and df_deuda.empty and df_ahorros.empty:
    st.info("Aun no hay datos cargados. Ve a 'Cargar Cartola', 'Cargar Deuda CMF' o 'Registrar Ahorro' para empezar.")
    st.stop()

for df, col in ((df_trans, "fecha"), (df_deuda, "fecha_actualizacion"), (df_ahorros, "fecha")):
    if not df.empty:
        df[col] = pd.to_datetime(df[col])

# --- Resumen general (siempre visible arriba, sin necesidad de cambiar de pestaña) ---
saldo_cc_actual = (
    df_trans.sort_values("fecha").groupby("cuenta").tail(1)["saldo"].sum() if not df_trans.empty else 0
)
ahorros_actual = (
    df_ahorros.sort_values("fecha").groupby("cuenta").tail(1)["saldo"].sum() if not df_ahorros.empty else 0
)
deuda_actual = df_deuda.sort_values("fecha_actualizacion").tail(1)["deuda_total"].iloc[0] if not df_deuda.empty else 0

c1, c2, c3, c4 = st.columns(4)
c1.metric("Saldo cuenta corriente", clp(saldo_cc_actual))
c2.metric("Ahorros / inversiones", clp(ahorros_actual))
c3.metric("Deuda CMF vigente", clp(deuda_actual))
c4.metric("Patrimonio neto estimado", clp(saldo_cc_actual + ahorros_actual - deuda_actual))

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
            st.subheader(f"Este mes ({comp['mes_actual']}) vs el anterior ({comp['mes_anterior']})")
            delta_txt = f"{comp['porcentaje']:+.1f}% vs mes anterior" if comp["porcentaje"] is not None else None
            cm1, cm2 = st.columns(2)
            cm1.metric(f"Gasto en {comp['mes_anterior']}", clp(comp["gasto_anterior"]))
            cm2.metric(f"Gasto en {comp['mes_actual']}", clp(comp["gasto_actual"]), delta=delta_txt, delta_color="inverse")

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
                st.plotly_chart(fig, use_container_width=True)

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

        st.divider()
        st.subheader("En que gasto mi dinero")

        fmin, fmax = df_trans["fecha"].min().date(), df_trans["fecha"].max().date()
        rango = st.date_input("Periodo a analizar", value=(fmin, fmax), min_value=fmin, max_value=fmax)
        if isinstance(rango, tuple) and len(rango) == 2:
            desde, hasta = rango
        else:
            desde, hasta = fmin, fmax

        mask = (df_trans["fecha"].dt.date >= desde) & (df_trans["fecha"].dt.date <= hasta)
        df_periodo = df_trans[mask]

        es_ahorro_mask = df_periodo["categoria"].apply(es_categoria_ahorro)
        total_gastos = df_periodo.loc[~es_ahorro_mask, "monto_cargo"].sum()
        total_ahorro_periodo = df_periodo.loc[es_ahorro_mask, "monto_cargo"].sum()
        total_ingresos = df_periodo["monto_abono"].sum()

        ca, cb, cc = st.columns(3)
        ca.metric("Total gastos en el periodo", clp(total_gastos))
        cb.metric("Destinado a ahorro en el periodo", clp(total_ahorro_periodo))
        cc.metric("Total abonos (entradas) en el periodo", clp(total_ingresos))
        st.caption(
            "El gasto no incluye lo que transferiste a categorias de ahorro/inversion — esa plata sigue siendo "
            "tuya, no es consumo."
        )

        gasto_categoria = (
            df_periodo[(df_periodo["monto_cargo"] > 0) & ~es_ahorro_mask]
            .groupby("categoria", as_index=False)["monto_cargo"]
            .sum()
            .sort_values("monto_cargo", ascending=False)
        )
        gasto_categoria["porcentaje"] = gasto_categoria["monto_cargo"] / gasto_categoria["monto_cargo"].sum() * 100

        col_pie, col_lista = st.columns([3, 2])
        with col_pie:
            fig = px.pie(
                gasto_categoria,
                names="categoria",
                values="monto_cargo",
                title="Distribucion de gastos por categoria",
                hole=0.35,
            )
            fig.update_traces(textinfo="percent+label")
            fig.update_layout(height=560, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
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

        st.subheader("Evolucion del saldo en cuenta corriente")
        fig = px.line(df_trans, x="fecha", y="saldo", color="cuenta", markers=True)
        st.plotly_chart(fig, use_container_width=True)

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
            st.divider()

        fig = px.line(
            df_ahorros, x="fecha", y="saldo", color="cuenta", markers=True, title="Evolucion del saldo de ahorros"
        )
        st.plotly_chart(fig, use_container_width=True)

        serie_ahorro = ahorro_por_mes(df_trans) if not df_trans.empty else pd.Series(dtype=float)
        if len(serie_ahorro) >= 1:
            st.divider()
            st.subheader("Cuanto ahorre este mes")
            st.caption("Segun las transferencias categorizadas como ahorro/inversion en tu cartola.")

            if len(serie_ahorro) >= 2:
                mes_actual_a, mes_anterior_a = serie_ahorro.index[-1], serie_ahorro.index[-2]
                actual_a, anterior_a = float(serie_ahorro.iloc[-1]), float(serie_ahorro.iloc[-2])
                diferencia_a = actual_a - anterior_a
                pct_a = (diferencia_a / anterior_a * 100) if anterior_a else None
                delta_txt_a = f"{pct_a:+.1f}% vs mes anterior" if pct_a is not None else None
                ca1, ca2 = st.columns(2)
                ca1.metric(f"Ahorrado en {mes_anterior_a}", clp(anterior_a))
                ca2.metric(f"Ahorrado en {mes_actual_a}", clp(actual_a), delta=delta_txt_a)
            else:
                st.metric(f"Ahorrado en {serie_ahorro.index[-1]}", clp(serie_ahorro.iloc[-1]))

            df_serie_ahorro = serie_ahorro.reset_index()
            df_serie_ahorro.columns = ["mes", "monto"]
            df_serie_ahorro["mes"] = df_serie_ahorro["mes"].astype(str)
            fig = px.bar(df_serie_ahorro, x="mes", y="monto", title="Ahorro destinado por mes")
            st.plotly_chart(fig, use_container_width=True)

        if df_ahorros["rentabilidad_generada"].notna().any():
            st.divider()
            st.subheader("Cuanto he generado con mis ahorros")
            rent = df_ahorros.sort_values("fecha").groupby("cuenta").tail(1)[["cuenta", "rentabilidad_generada"]].dropna()
            fig = px.bar(rent, x="cuenta", y="rentabilidad_generada", title="Rentabilidad generada a la fecha, por cuenta")
            st.plotly_chart(fig, use_container_width=True)
            st.metric("Rentabilidad total generada", clp(rent["rentabilidad_generada"].sum()))

# --- Proyeccion de ahorros ---
with tab_proyeccion:
    if ultimo_por_cuenta.empty:
        st.info("Aun no registras ningun ahorro. Ve a 'Registrar Ahorro' para empezar.")
    else:
        st.subheader("Donde tengo mis ahorros")
        fig = px.pie(ultimo_por_cuenta, names="cuenta", values="saldo", title="Distribucion actual de ahorros por cuenta")
        st.plotly_chart(fig, use_container_width=True)
        st.divider()

        config_tasas = listar_config()
        if not any(c.get("tasa_base") for c in config_tasas.values()):
            st.info("Configura una tasa de interes anual para tus cuentas en 'Registrar Ahorro' para ver la proyeccion aqui.")
        else:
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
                st.metric("Ganancia total estimada en 1 año (con la distribucion actual)", clp(ganancia_actual_total))
                st.caption(
                    "Estimacion simple con interes sobre el saldo actual; no considera aportes, retiros ni cambios de tasa futuros."
                )

                st.divider()
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
                    st.divider()
                    st.subheader("¿Me conviene pagar el plan premium?")
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

                st.divider()
                st.subheader("¿Como repartir tu plata entre tus cuentas para maximizar la ganancia?")
                total_ahorros = ultimo_por_cuenta["saldo"].sum()
                reparto = optimizar_asignacion(total_ahorros, config_tasas)

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

            st.divider()
            st.subheader("¿DAP o dejarlo en una cuenta fintech?")
            st.caption(
                "Ingresa el monto, tasa y plazo que te dio el simulador del banco para tu Deposito a Plazo (DAP), "
                "y lo comparamos contra dejar el mismo monto ese mismo plazo en tus cuentas configuradas. Esto es "
                "solo una calculadora — si terminas abriendo el DAP, puedes agregarlo como una cuenta mas en "
                "'Registrar Ahorro' (igual que Mach o Tenpo) para seguirle la pista."
            )

            dc1, dc2, dc3 = st.columns(3)
            monto_dap = dc1.number_input("Monto a depositar", min_value=0.0, step=100000.0, format="%.0f", key="dap_monto")
            tasa_dap = dc2.number_input("Tasa anual del DAP (%)", min_value=0.0, step=0.1, format="%.2f", key="dap_tasa")
            plazo_dap = dc3.number_input("Plazo (dias)", min_value=1, step=1, value=90, key="dap_plazo")

            if monto_dap > 0 and tasa_dap > 0:
                opciones_comparar = [
                    {
                        "opcion": f"DAP ({tasa_dap:.2f}% anual)",
                        **simular_dap(monto_dap, tasa_dap, int(plazo_dap)),
                    }
                ]
                for cuenta, cfg in config_tasas.items():
                    if not cfg or not cfg.get("tasa_base"):
                        continue
                    ganancia = calcular_ganancia_anual(monto_dap, cfg) * (plazo_dap / 365)
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
        st.subheader("Evolucion de mi deuda (CMF)")
        fig = px.line(df_deuda, x="fecha_actualizacion", y="deuda_total", markers=True)
        st.plotly_chart(fig, use_container_width=True)
