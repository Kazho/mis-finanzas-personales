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


def calcular_progresos(
    metas: list[dict], df_ahorros: pd.DataFrame, df_trans: pd.DataFrame, ultimo_por_cuenta: pd.DataFrame
) -> dict[int, dict]:
    """Progreso de todas las metas a la vez, repartiendo la plata como "sobres" entre las que
    comparten el mismo alcance (mismo total o misma cuenta), para no contar el mismo peso dos veces.

    Dentro de cada grupo se ordenan primero las con fecha limite (la mas proxima primero) y
    despues las sin fecha por antiguedad; la plata disponible se asigna en ese orden hasta llenar
    cada meta antes de pasar a la siguiente, y la fecha estimada de una meta ya considera el
    tiempo que toma terminar de llenar las anteriores.
    """
    resultado: dict[int, dict] = {}

    grupos: dict[str | None, list[dict]] = {}
    for m in metas:
        grupos.setdefault(m["cuenta"], []).append(m)

    for cuenta, metas_grupo in grupos.items():
        if cuenta:
            fila = ultimo_por_cuenta[ultimo_por_cuenta["cuenta"] == cuenta]
            pool_actual = float(fila["saldo"].iloc[0]) if not fila.empty else 0.0
            ritmo = _ritmo_mensual_cuenta(df_ahorros, cuenta)
        else:
            pool_actual = float(ultimo_por_cuenta["saldo"].sum()) if not ultimo_por_cuenta.empty else 0.0
            ritmo = _ritmo_mensual_total(df_trans)

        metas_ordenadas = sorted(
            metas_grupo,
            key=lambda m: (0 if m["fecha_objetivo"] else 1, m["fecha_objetivo"] or "", m["fecha_creacion"], m["id"]),
        )

        objetivo_acumulado = 0.0
        for m in metas_ordenadas:
            objetivo = m["monto_objetivo"]
            objetivo_acumulado += objetivo
            asignado = min(max(pool_actual - (objetivo_acumulado - objetivo), 0.0), objetivo)
            falta = max(objetivo - asignado, 0.0)
            falta_hasta_aqui = max(objetivo_acumulado - pool_actual, 0.0)

            meses_estimados = None
            fecha_estimada = None
            if falta_hasta_aqui > 0 and ritmo and ritmo > 0:
                meses_estimados = falta_hasta_aqui / ritmo
                fecha_estimada = datetime.date.today() + datetime.timedelta(days=meses_estimados * 30.44)

            resultado[m["id"]] = {
                "monto_actual": asignado,
                "porcentaje": min(asignado / objetivo * 100, 100) if objetivo else 0.0,
                "falta": falta,
                "ritmo_mensual": ritmo,
                "meses_estimados": meses_estimados,
                "fecha_estimada": fecha_estimada,
                "cumplida": asignado >= objetivo > 0,
            }

    return resultado
