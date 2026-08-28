import datetime

import streamlit as st
import pandas as pd

from src.db import get_conn, init_db, obtener_tipos_cuenta, guardar_tipo_cuenta
from src.proyeccion import listar_config, guardar_config
from src.formato import clp, clp_md
from src.metas import listar_metas, agregar_meta, eliminar_meta

TOTAL_AHORROS = "Total de mis ahorros"

init_db()

st.title("Registrar Ahorro / Inversion")
st.caption(
    "Para cuentas como Tenpo o Mach, que no entregan cartola, registra manualmente el saldo total "
    "que muestra la app cada vez que revises. Con eso se arma el historico de tus ahorros. "
    "Tambien puedes usar esto para cuentas que no son de ahorro pero quieres seguir igual, como una "
    "Cuenta RUT que uses para gastos de la casa y familia; en ese caso simplemente no le configures tasa de interes."
)

with get_conn() as conn:
    cuentas_existentes = [
        r["cuenta"] for r in conn.execute("SELECT DISTINCT cuenta FROM ahorros_snapshot ORDER BY cuenta").fetchall()
    ]
    snapshots = pd.read_sql_query(
        "SELECT id, fecha, cuenta, saldo, rentabilidad_generada, nota FROM ahorros_snapshot ORDER BY fecha DESC, cuenta",
        conn,
    )

opciones = cuentas_existentes + ["+ Nueva cuenta"]

# No se usa st.form: dentro de un form los widgets no se refrescan hasta enviar,
# asi que el campo de texto que aparece al elegir "+ Nueva cuenta" nunca se mostraba.
# Con un "form_id" que cambia despues de guardar forzamos que todos los widgets
# vuelvan a su valor por defecto (equivalente al clear_on_submit de los forms).
if "ahorro_form_id" not in st.session_state:
    st.session_state.ahorro_form_id = 0
fid = st.session_state.ahorro_form_id

col1, col2 = st.columns(2)
fecha = col1.date_input("Fecha", value=datetime.date.today(), key=f"fecha_{fid}")
seleccion = col2.selectbox(
    "Cuenta / app", opciones, index=len(opciones) - 1 if not cuentas_existentes else 0, key=f"cuenta_sel_{fid}"
)
nueva_cuenta = ""
tipo_nueva_cuenta = "ahorro"
if seleccion == "+ Nueva cuenta":
    nueva_cuenta = st.text_input("Nombre de la cuenta nueva (ej: Tenpo, Mach, Fintual)", key=f"nueva_cuenta_{fid}")
    tipo_label = st.radio(
        "Tipo de cuenta",
        [
            "🔄 Movimiento (la usas seguido, entra y sale plata)",
            "💰 Ahorro estatica (plata quieta, tipo bajo el colchon)",
        ],
        key=f"tipo_nueva_cuenta_{fid}",
    )
    tipo_nueva_cuenta = "movimiento" if tipo_label.startswith("🔄") else "ahorro"

col3, col4 = st.columns(2)
saldo = col3.number_input("Saldo total", min_value=0.0, step=1000.0, format="%.0f", key=f"saldo_{fid}")
rentabilidad = col4.number_input(
    "Rentabilidad generada a la fecha (opcional)", min_value=0.0, step=100.0, format="%.0f", key=f"rent_{fid}"
)
nota = st.text_input("Nota (opcional)", key=f"nota_{fid}")

if st.button("Guardar snapshot", type="primary"):
    cuenta_final = nueva_cuenta.strip() if seleccion == "+ Nueva cuenta" else seleccion
    if not cuenta_final:
        st.error("Debes indicar el nombre de la cuenta.")
    else:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO ahorros_snapshot (fecha, cuenta, saldo, rentabilidad_generada, nota)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(fecha, cuenta) DO UPDATE SET
                    saldo = excluded.saldo,
                    rentabilidad_generada = excluded.rentabilidad_generada,
                    nota = excluded.nota
                """,
                (fecha.isoformat(), cuenta_final, saldo, rentabilidad or None, nota or None),
            )
        if seleccion == "+ Nueva cuenta":
            guardar_tipo_cuenta(cuenta_final, tipo_nueva_cuenta)
        st.success(f"Guardado: **{cuenta_final}** el {fecha} con saldo **{clp_md(saldo)}**")
        st.session_state.ahorro_form_id += 1
        st.rerun()

if cuentas_existentes:
    st.divider()
    st.subheader("Proyeccion: tasa de interes anual por cuenta")
    st.caption(
        "Para estimar cuanto generarias si dejas la plata donde esta. Si la cuenta paga distinto sobre "
        "cierto monto (por plan premium u otro motivo), completa tambien el monto tope y la tasa sobre ese tope; "
        "si no aplica, dejalos en blanco. Para cuentas que no generan rentabilidad (como una Cuenta RUT de gastos "
        "familiares) deja todo en 0. Si el tope corresponde a un plan pagado (como Mach Premium), completa tambien "
        "el costo mensual: la app va a comparar sola si te conviene pagarlo segun tu saldo actual. Si la cuenta "
        "recien ABONA el interes a tu saldo una vez al mes (como Mach, que paga los primeros dias del mes "
        "siguiente) en vez de dia a dia, marca la casilla 'abona 1 vez al mes' para que la ganancia estimada "
        "no asuma que compone a diario."
    )

    config_actual = listar_config()
    tipos_actuales = obtener_tipos_cuenta()
    filas_config = []
    for cuenta in cuentas_existentes:
        c = config_actual.get(cuenta, {})
        filas_config.append(
            {
                "cuenta": cuenta,
                "tipo": "Movimiento" if tipos_actuales.get(cuenta, "ahorro") == "movimiento" else "Ahorro estatica",
                "tasa_base_%": c.get("tasa_base") or 0.0,
                "monto_tope": c.get("monto_umbral"),
                "tasa_sobre_tope_%": c.get("tasa_premium"),
                "costo_mensual_del_tope": c.get("costo_mensual"),
                "abona_1_vez_al_mes": bool(c.get("abono_mensual")),
            }
        )
    df_config = pd.DataFrame(filas_config)

    editado_config = st.data_editor(
        df_config,
        hide_index=True,
        use_container_width=True,
        disabled=["cuenta"],
        column_config={
            "tipo": st.column_config.SelectboxColumn("tipo de cuenta", options=["Movimiento", "Ahorro estatica"]),
            "tasa_base_%": st.column_config.NumberColumn("tasa hasta el tope %", min_value=0.0, step=0.1, format="%.2f"),
            "monto_tope": st.column_config.NumberColumn("monto tope (opcional)", min_value=0.0, step=10000.0),
            "tasa_sobre_tope_%": st.column_config.NumberColumn(
                "tasa normal / sobre el tope (opcional)", min_value=0.0, step=0.1, format="%.2f"
            ),
            "costo_mensual_del_tope": st.column_config.NumberColumn(
                "costo mensual del plan (opcional)", min_value=0.0, step=100.0
            ),
            "abona_1_vez_al_mes": st.column_config.CheckboxColumn("abona 1 vez al mes (ej. Mach)"),
        },
        key="editor_config_tasas",
    )

    if st.button("Guardar tasas"):
        for _, fila in editado_config.iterrows():
            tiene_tramo = pd.notna(fila["monto_tope"]) and pd.notna(fila["tasa_sobre_tope_%"])
            guardar_config(
                cuenta=fila["cuenta"],
                tasa_base=float(fila["tasa_base_%"] or 0),
                monto_umbral=float(fila["monto_tope"]) if tiene_tramo else None,
                tasa_premium=float(fila["tasa_sobre_tope_%"]) if tiene_tramo else None,
                costo_mensual=float(fila["costo_mensual_del_tope"]) if pd.notna(fila["costo_mensual_del_tope"]) else None,
                abono_mensual=bool(fila["abona_1_vez_al_mes"]),
            )
            guardar_tipo_cuenta(fila["cuenta"], "movimiento" if fila["tipo"] == "Movimiento" else "ahorro")
        st.success("Tasas y tipo de cuenta guardados. Ve al Dashboard para ver la proyeccion de ganancia estimada.")

if cuentas_existentes:
    st.divider()
    st.subheader("Metas de ahorro")
    st.caption(
        "Define un monto objetivo (para el total de tus ahorros o para una cuenta especifica) y la app va a "
        "mostrarte el avance y una fecha estimada de cumplimiento segun tu ritmo de ahorro reciente."
    )

    # No se usa st.form: dentro de un form los widgets no se refrescan hasta enviar,
    # asi que el campo de fecha que aparece al marcar "Ponerle fecha limite" no llegaba
    # a mostrarse (mismo problema que hubo antes en esta misma pagina).
    if "meta_form_id" not in st.session_state:
        st.session_state.meta_form_id = 0
    mfid = st.session_state.meta_form_id

    mc1, mc2 = st.columns(2)
    nombre_meta = mc1.text_input("Nombre de la meta (ej: Pie departamento, Viaje)", key=f"meta_nombre_{mfid}")
    cuenta_meta = mc2.selectbox("Aplica a", [TOTAL_AHORROS] + cuentas_existentes, key=f"meta_cuenta_{mfid}")
    mc3, mc4 = st.columns(2)
    monto_objetivo = mc3.number_input("Monto objetivo", min_value=0.0, step=10000.0, format="%.0f", key=f"meta_monto_{mfid}")
    tiene_fecha = mc4.checkbox("Ponerle fecha limite", key=f"meta_tiene_fecha_{mfid}")
    fecha_objetivo = (
        st.date_input("Fecha limite", value=datetime.date.today(), key=f"meta_fecha_{mfid}") if tiene_fecha else None
    )

    if st.button("Crear meta", type="primary"):
        if not nombre_meta.strip() or monto_objetivo <= 0:
            st.error("Debes indicar un nombre y un monto objetivo mayor a 0.")
        else:
            agregar_meta(
                nombre_meta.strip(),
                monto_objetivo,
                None if cuenta_meta == TOTAL_AHORROS else cuenta_meta,
                fecha_objetivo,
            )
            st.success(f"Meta '{nombre_meta.strip()}' creada.")
            st.session_state.meta_form_id += 1
            st.rerun()

    metas = listar_metas()
    if metas:
        with st.expander("Eliminar una meta"):
            opciones_meta = {f"{m['nombre']} ({clp(m['monto_objetivo'])})": m["id"] for m in metas}
            elegida = st.selectbox("Selecciona la meta a eliminar", list(opciones_meta.keys()))
            if st.button("Eliminar meta", type="secondary"):
                eliminar_meta(opciones_meta[elegida])
                st.success("Meta eliminada.")
                st.rerun()
    st.caption("El avance de cada meta se ve en el Dashboard, pestaña Ahorros.")

st.subheader("Historico registrado")
if snapshots.empty:
    st.info("Aun no registras ningun snapshot de ahorro.")
else:
    df_snapshots = snapshots.drop(columns=["id"]).copy()
    df_snapshots["saldo"] = df_snapshots["saldo"].apply(clp)
    df_snapshots["rentabilidad_generada"] = df_snapshots["rentabilidad_generada"].apply(clp)
    st.dataframe(
        df_snapshots,
        hide_index=True,
        use_container_width=True,
        column_config={"rentabilidad_generada": "rentabilidad generada"},
    )

    with st.expander("Eliminar un registro"):
        opciones_borrar = {
            f"{r.fecha} - {r.cuenta} - {clp(r.saldo)}": r.id for r in snapshots.itertuples()
        }
        elegido = st.selectbox("Selecciona el registro a eliminar", list(opciones_borrar.keys()))
        if st.button("Eliminar", type="secondary"):
            with get_conn() as conn:
                conn.execute("DELETE FROM ahorros_snapshot WHERE id = ?", (opciones_borrar[elegido],))
            st.success("Registro eliminado.")
            st.rerun()
