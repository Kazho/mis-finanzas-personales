"""Registrar Ahorro / Inversion -- version NiceGUI de vistas/3_Registrar_Ahorro.py (Streamlit).

Las 4 secciones de la pagina original (snapshot, tasas, metas, historico) se dependian unas de otras
via variables compartidas en el mismo script + st.rerun(). Aca cada una es su propio @ui.refreshable:
guardar un snapshot nuevo, por ejemplo, refresca la seccion de tasas/metas/historico (porque puede
haber aparecido una cuenta nueva) sin tocar el resto de la pagina ni recargarla."""
import datetime

import pandas as pd
from nicegui import ui

from src.db import get_conn, obtener_tipos_cuenta, guardar_tipo_cuenta
from src.proyeccion import listar_config, guardar_config
from src.formato import clp
from src.metas import listar_metas, agregar_meta, eliminar_meta
from src.ui_nicegui.components import tarjeta, tabla, texto_muted, campo_fecha
from src.ui_nicegui.editable_table import editable_table
from src.ui_nicegui.layout import layout

TOTAL_AHORROS = "Total de mis ahorros"


def _cuentas_existentes() -> list[str]:
    with get_conn() as conn:
        return [r["cuenta"] for r in conn.execute("SELECT DISTINCT cuenta FROM ahorros_snapshot ORDER BY cuenta").fetchall()]


@ui.refreshable
def _seccion_form_snapshot():
    cuentas = _cuentas_existentes()
    opciones = cuentas + ["+ Nueva cuenta"]

    with ui.row().classes("gap-3 w-full items-end"):
        fecha_input = campo_fecha(datetime.date.today().isoformat(), "Fecha")
        sel_cuenta = ui.select(opciones, value=(opciones[-1] if not cuentas else opciones[0]), label="Cuenta / app").classes("flex-1")

    nueva_cuenta_input = ui.input("Nombre de la cuenta nueva (ej: Tenpo, Mach, Fintual)").classes("w-full")
    nueva_cuenta_input.bind_visibility_from(sel_cuenta, "value", backward=lambda v: v == "+ Nueva cuenta")
    tipo_radio = ui.radio(
        [
            "\U0001F504 Movimiento (la usas seguido, entra y sale plata)",
            "\U0001F4B0 Ahorro estatica (plata quieta, tipo bajo el colchon)",
        ],
        value="\U0001F504 Movimiento (la usas seguido, entra y sale plata)",
    )
    tipo_radio.bind_visibility_from(sel_cuenta, "value", backward=lambda v: v == "+ Nueva cuenta")

    with ui.row().classes("gap-3 w-full"):
        saldo_input = ui.number("Saldo total", value=0.0, min=0.0, step=1000.0, format="%.0f").classes("flex-1")
        rent_input = ui.number(
            "Rentabilidad generada a la fecha (opcional)", value=0.0, min=0.0, step=100.0, format="%.0f",
        ).classes("flex-1")
        rent_input.tooltip(
            "El rendimiento acumulado que la propia app de la fintech te muestra (ej. 'Rendimientos generados' en "
            "Mercado Pago). Llenalo cada vez: con 2 registros seguidos, el Dashboard calcula la tasa real que te "
            "esta pagando la cuenta y avisa si no coincide con la que configuraste mas abajo."
        )
    nota_input = ui.input("Nota (opcional)").classes("w-full")

    def _guardar():
        seleccion = sel_cuenta.value
        cuenta_final = (nueva_cuenta_input.value or "").strip() if seleccion == "+ Nueva cuenta" else seleccion
        if not cuenta_final:
            ui.notify("Debes indicar el nombre de la cuenta.", type="negative")
            return
        fecha = datetime.date.fromisoformat(fecha_input.value) if fecha_input.value else datetime.date.today()
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO ahorros_snapshot (fecha, cuenta, saldo, rentabilidad_generada, nota)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(fecha, cuenta) DO UPDATE SET
                    saldo = excluded.saldo, rentabilidad_generada = excluded.rentabilidad_generada, nota = excluded.nota
                """,
                (fecha.isoformat(), cuenta_final, saldo_input.value or 0, rent_input.value or None, nota_input.value or None),
            )
        if seleccion == "+ Nueva cuenta":
            tipo_nueva = "movimiento" if tipo_radio.value.startswith("\U0001F504") else "ahorro"
            guardar_tipo_cuenta(cuenta_final, tipo_nueva)
        ui.notify(f"Guardado: {cuenta_final} el {fecha} con saldo {clp(saldo_input.value or 0)}", type="positive")
        _seccion_form_snapshot.refresh()
        _seccion_tasas.refresh()
        _seccion_metas.refresh()
        _seccion_historico.refresh()

    ui.button("Guardar snapshot", on_click=_guardar).props("color=primary")


@ui.refreshable
def _seccion_tasas():
    cuentas = _cuentas_existentes()
    if not cuentas:
        return
    with tarjeta("Proyeccion: tasa de interes anual por cuenta"):
        texto_muted(
            "Para estimar cuanto generarias si dejas la plata donde esta. Si la cuenta paga distinto sobre cierto "
            "monto (por plan premium u otro motivo), completa tambien el monto tope y la tasa sobre ese tope; si no "
            "aplica, dejalos en 0. Si el tope corresponde a un plan pagado (como Mach Premium), completa tambien el "
            "costo mensual. Si la cuenta recien ABONA el interes una vez al mes (como Mach) en vez de dia a dia, "
            "marca 'abona 1 vez al mes'."
        )
        config_actual = listar_config()
        tipos_actuales = obtener_tipos_cuenta()
        filas = [
            {
                "cuenta": cuenta,
                "tipo": "Movimiento" if tipos_actuales.get(cuenta, "ahorro") == "movimiento" else "Ahorro estatica",
                "tasa_base_%": (config_actual.get(cuenta, {}).get("tasa_base")) or 0.0,
                "monto_tope": config_actual.get(cuenta, {}).get("monto_umbral") or 0.0,
                "tasa_sobre_tope_%": config_actual.get(cuenta, {}).get("tasa_premium") or 0.0,
                "costo_mensual_del_tope": config_actual.get(cuenta, {}).get("costo_mensual") or 0.0,
                "abona_1_vez_al_mes": bool(config_actual.get(cuenta, {}).get("abono_mensual")),
            }
            for cuenta in cuentas
        ]

        def _guardar_tasas(_originales, editados):
            for fila in editados:
                monto_tope = float(fila.get("monto_tope") or 0)
                tasa_tope = float(fila.get("tasa_sobre_tope_%") or 0)
                tiene_tramo = monto_tope > 0 and tasa_tope > 0
                costo = float(fila.get("costo_mensual_del_tope") or 0)
                guardar_config(
                    cuenta=fila["cuenta"],
                    tasa_base=float(fila.get("tasa_base_%") or 0),
                    monto_umbral=monto_tope if tiene_tramo else None,
                    tasa_premium=tasa_tope if tiene_tramo else None,
                    costo_mensual=costo if costo > 0 else None,
                    abono_mensual=bool(fila.get("abona_1_vez_al_mes")),
                )
                guardar_tipo_cuenta(fila["cuenta"], "movimiento" if fila["tipo"] == "Movimiento" else "ahorro")
            ui.notify("Tasas y tipo de cuenta guardados. Ve al Dashboard para ver la proyeccion de ganancia estimada.", type="positive")
            _seccion_tasas.refresh()

        editable_table(
            filas,
            [
                {"campo": "cuenta", "titulo": "Cuenta", "tipo": "solo_lectura"},
                {"campo": "tipo", "titulo": "Tipo de cuenta", "tipo": "select", "opciones": ["Movimiento", "Ahorro estatica"]},
                {"campo": "tasa_base_%", "titulo": "Tasa hasta el tope %", "tipo": "numero"},
                {"campo": "monto_tope", "titulo": "Monto tope (opcional)", "tipo": "numero"},
                {"campo": "tasa_sobre_tope_%", "titulo": "Tasa normal / sobre el tope (opcional)", "tipo": "numero"},
                {"campo": "costo_mensual_del_tope", "titulo": "Costo mensual del plan (opcional)", "tipo": "numero"},
                {"campo": "abona_1_vez_al_mes", "titulo": "Abona 1 vez al mes (ej. Mach)", "tipo": "checkbox"},
            ],
            _guardar_tasas,
            texto_boton="Guardar tasas",
        )


@ui.refreshable
def _seccion_metas():
    cuentas = _cuentas_existentes()
    if not cuentas:
        return
    with tarjeta("Metas de ahorro"):
        texto_muted(
            "Define un monto objetivo (para el total de tus ahorros o para una cuenta especifica) y la app va a "
            "mostrarte el avance y una fecha estimada de cumplimiento segun tu ritmo de ahorro reciente."
        )
        with ui.row().classes("gap-3 w-full"):
            nombre_input = ui.input("Nombre de la meta (ej: Pie departamento, Viaje)").classes("flex-1")
            cuenta_sel = ui.select([TOTAL_AHORROS] + cuentas, value=TOTAL_AHORROS, label="Aplica a").classes("flex-1")
        with ui.row().classes("gap-3 items-center w-full"):
            monto_input = ui.number("Monto objetivo", value=0.0, min=0.0, step=10000.0, format="%.0f").classes("flex-1")
            tiene_fecha_check = ui.checkbox("Ponerle fecha limite")
        fecha_input = campo_fecha(datetime.date.today().isoformat(), "Fecha limite")
        fecha_input.bind_visibility_from(tiene_fecha_check, "value")

        def _crear():
            nombre = (nombre_input.value or "").strip()
            monto = monto_input.value or 0
            if not nombre or monto <= 0:
                ui.notify("Debes indicar un nombre y un monto objetivo mayor a 0.", type="negative")
                return
            fecha_obj = datetime.date.fromisoformat(fecha_input.value) if tiene_fecha_check.value and fecha_input.value else None
            agregar_meta(nombre, monto, None if cuenta_sel.value == TOTAL_AHORROS else cuenta_sel.value, fecha_obj)
            ui.notify(f"Meta '{nombre}' creada.", type="positive")
            _seccion_metas.refresh()

        ui.button("Crear meta", on_click=_crear).props("color=primary")

        metas = listar_metas()
        if metas:
            with ui.expansion("Eliminar una meta"):
                opciones_meta = {f"{m['nombre']} ({clp(m['monto_objetivo'])})": m["id"] for m in metas}
                sel_eliminar = ui.select(list(opciones_meta.keys()), label="Selecciona la meta a eliminar")

                def _eliminar():
                    if sel_eliminar.value:
                        eliminar_meta(opciones_meta[sel_eliminar.value])
                        ui.notify("Meta eliminada.", type="positive")
                        _seccion_metas.refresh()

                ui.button("Eliminar meta", on_click=_eliminar).props("color=negative outline")
        texto_muted("El avance de cada meta se ve en el Dashboard, pestaña Ahorros.")


@ui.refreshable
def _seccion_historico():
    with get_conn() as conn:
        snapshots = pd.read_sql_query(
            "SELECT id, fecha, cuenta, saldo, rentabilidad_generada, nota FROM ahorros_snapshot ORDER BY fecha DESC, cuenta",
            conn,
        )
    ui.label("Historico registrado").classes("text-lg font-bold")
    if snapshots.empty:
        ui.label("Aun no registras ningun snapshot de ahorro.")
        return

    df = snapshots.drop(columns=["id"]).copy()
    df["saldo"] = df["saldo"].apply(clp)
    df["rentabilidad_generada"] = df["rentabilidad_generada"].apply(clp)
    tabla(df, {"rentabilidad_generada": "Rentabilidad generada"})

    with ui.expansion("Eliminar un registro"):
        opciones_borrar = {f"{r.fecha} - {r.cuenta} - {clp(r.saldo)}": r.id for r in snapshots.itertuples()}
        sel_borrar = ui.select(list(opciones_borrar.keys()), label="Selecciona el registro a eliminar")

        def _eliminar():
            if sel_borrar.value:
                with get_conn() as conn:
                    conn.execute("DELETE FROM ahorros_snapshot WHERE id = ?", (opciones_borrar[sel_borrar.value],))
                ui.notify("Registro eliminado.", type="positive")
                _seccion_historico.refresh()
                _seccion_tasas.refresh()
                _seccion_metas.refresh()

        ui.button("Eliminar", on_click=_eliminar).props("color=negative outline")


@ui.page("/registrar-ahorro")
def pagina_registrar_ahorro():
    with layout("/registrar-ahorro"):
        ui.label("Registrar Ahorro / Inversion").classes("text-2xl font-bold")
        texto_muted(
            "Para cuentas como Tenpo o Mach, que no entregan cartola, registra manualmente el saldo total que "
            "muestra la app cada vez que revises. Tambien puedes usar esto para cuentas que no son de ahorro pero "
            "quieres seguir igual, como una Cuenta RUT que uses para gastos de la casa; en ese caso simplemente no "
            "le configures tasa de interes."
        )
        with tarjeta():
            _seccion_form_snapshot()
        _seccion_tasas()
        _seccion_metas()
        _seccion_historico()
