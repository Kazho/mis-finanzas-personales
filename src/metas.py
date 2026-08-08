"""Metas de ahorro: definir un monto objetivo y ver el progreso / fecha estimada de cumplimiento.

El ritmo de ahorro mensual usado para proyectar la fecha se calcula distinto segun el alcance
de la meta: si es sobre una cuenta especifica, se usa el crecimiento real del saldo de esa
cuenta entre su primer y ultimo snapshot (incluye interes generado, no solo depositos); si es
sobre el total de ahorros, se usa el promedio de los ultimos meses de dinero destinado a
categorias de ahorro/inversion en la cartola (ver `src.analisis_gastos.ahorro_por_mes`), porque
reconstruir un "total historico" fiable cruzando cuentas que empezaron a registrarse en fechas
distintas es mas fragil que esta aproximacion.
"""
import datetime

import pandas as pd

from src.db import get_conn


def listar_metas() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM metas_ahorro ORDER BY completada, fecha_objetivo IS NULL, fecha_objetivo"
        ).fetchall()
    return [dict(r) for r in rows]


def agregar_meta(nombre: str, monto_objetivo: float, cuenta: str | None, fecha_objetivo: datetime.date | None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO metas_ahorro (nombre, monto_objetivo, cuenta, fecha_objetivo, fecha_creacion) VALUES (?, ?, ?, ?, ?)",
            (
                nombre,
                monto_objetivo,
                cuenta,
                fecha_objetivo.isoformat() if fecha_objetivo else None,
                datetime.date.today().isoformat(),
            ),
        )


def eliminar_meta(meta_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM metas_ahorro WHERE id = ?", (meta_id,))


def _ritmo_mensual_cuenta(df_ahorros: pd.DataFrame, cuenta: str) -> float | None:
    df = df_ahorros[df_ahorros["cuenta"] == cuenta].sort_values("fecha")
    if len(df) < 2:
        return None
    primero, ultimo = df.iloc[0], df.iloc[-1]
    meses = (ultimo["fecha"] - primero["fecha"]).days / 30.44
    if meses < 0.5:
        return None
    return (ultimo["saldo"] - primero["saldo"]) / meses


def _ritmo_mensual_total(df_trans: pd.DataFrame) -> float | None:
    from src.analisis_gastos import ahorro_por_mes

    if df_trans.empty:
        return None
    serie = ahorro_por_mes(df_trans)
    if serie.empty:
        return None
    return float(serie.tail(6).mean())


def calcular_progreso(
    meta: dict, df_ahorros: pd.DataFrame, df_trans: pd.DataFrame, ultimo_por_cuenta: pd.DataFrame
) -> dict:
    cuenta = meta["cuenta"]
    if cuenta:
        fila = ultimo_por_cuenta[ultimo_por_cuenta["cuenta"] == cuenta]
        monto_actual = float(fila["saldo"].iloc[0]) if not fila.empty else 0.0
        ritmo = _ritmo_mensual_cuenta(df_ahorros, cuenta)
    else:
        monto_actual = float(ultimo_por_cuenta["saldo"].sum()) if not ultimo_por_cuenta.empty else 0.0
        ritmo = _ritmo_mensual_total(df_trans)

    objetivo = meta["monto_objetivo"]
    porcentaje = min(monto_actual / objetivo * 100, 100) if objetivo else 0.0
    falta = max(objetivo - monto_actual, 0.0)

    meses_estimados = None
    fecha_estimada = None
    if falta > 0 and ritmo and ritmo > 0:
        meses_estimados = falta / ritmo
        fecha_estimada = datetime.date.today() + datetime.timedelta(days=meses_estimados * 30.44)

    return {
        "monto_actual": monto_actual,
        "porcentaje": porcentaje,
        "falta": falta,
        "ritmo_mensual": ritmo,
        "meses_estimados": meses_estimados,
        "fecha_estimada": fecha_estimada,
        "cumplida": monto_actual >= objetivo > 0,
    }
