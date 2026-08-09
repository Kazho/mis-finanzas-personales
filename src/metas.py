"""Metas de ahorro: definir un monto objetivo y ver el progreso / fecha estimada de cumplimiento.

La fecha estimada se calcula simulando mes a mes (no con una division simple), sumando cada mes
el aporte esperado y el interes de ese mes segun la tasa configurada — asi el interes generado
tambien cuenta para llegar antes a la meta, no solo lo que aportas tu.

El aporte y la tasa a usar dependen del alcance de la meta:
- Cuenta especifica: se usa la tasa configurada de esa cuenta (con sus tramos si tiene), y el
  aporte mensual sale del crecimiento real del saldo entre su primer y ultimo snapshot.
- Total de tus ahorros: no hay una sola tasa (cada cuenta puede tener la suya), asi que se usa
  una tasa promedio ponderada por saldo entre todas tus cuentas configuradas, y el aporte
  mensual sale del promedio reciente de transferencias a categorias de ahorro/inversion en tu
  cartola (ver `src.analisis_gastos.ahorro_por_mes`).
"""
import datetime

import pandas as pd

from src.db import get_conn
from src.proyeccion import calcular_ganancia_anual, tasa_efectiva, listar_config


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


def ritmo_mensual_cuenta(df_ahorros: pd.DataFrame, cuenta: str) -> float | None:
    df = df_ahorros[df_ahorros["cuenta"] == cuenta].sort_values("fecha")
    if len(df) < 2:
        return None
    primero, ultimo = df.iloc[0], df.iloc[-1]
    meses = (ultimo["fecha"] - primero["fecha"]).days / 30.44
    if meses < 0.5:
        return None
    return (ultimo["saldo"] - primero["saldo"]) / meses


def ritmo_mensual_total(df_trans: pd.DataFrame) -> float | None:
    from src.analisis_gastos import ahorro_por_mes

    if df_trans.empty:
        return None
    serie = ahorro_por_mes(df_trans)
    if serie.empty:
        return None
    return float(serie.tail(6).mean())


def _config_total_ponderado(ultimo_por_cuenta: pd.DataFrame, config_tasas: dict[str, dict]) -> dict | None:
    """Tasa flat promedio, ponderada por saldo, para tratar el total de ahorros como una sola
    "cuenta" sintetica al proyectar. Ignora cual cuenta especifica recibe cada peso nuevo."""
    total = float(ultimo_por_cuenta["saldo"].sum()) if not ultimo_por_cuenta.empty else 0.0
    if total <= 0:
        return None
    suma_ponderada = 0.0
    for _, fila in ultimo_por_cuenta.iterrows():
        cfg = config_tasas.get(fila["cuenta"])
        suma_ponderada += tasa_efectiva(fila["saldo"], cfg) * fila["saldo"]
    tasa_promedio = suma_ponderada / total
    if tasa_promedio <= 0:
        return None
    return {"tasa_base": tasa_promedio, "monto_umbral": None, "tasa_premium": None}


def _meses_hasta_objetivo(
    pool_actual: float, config: dict | None, ritmo: float | None, objetivo: float, max_meses: int = 600
) -> int | None:
    """Simula mes a mes (aporte + interes del mes) hasta que el saldo alcance el objetivo.

    Devuelve None si no se alcanza dentro de max_meses (50 años) o si no hay forma de crecer.
    """
    if pool_actual >= objetivo:
        return 0
    if not config or not config.get("tasa_base"):
        return None

    saldo = pool_actual
    aporte = ritmo or 0.0
    for mes in range(1, max_meses + 1):
        if aporte > 0:
            saldo += aporte
        saldo += calcular_ganancia_anual(saldo, config) / 12
        if saldo >= objetivo:
            return mes
    return None


def calcular_progresos(
    metas: list[dict], df_ahorros: pd.DataFrame, df_trans: pd.DataFrame, ultimo_por_cuenta: pd.DataFrame
) -> dict[int, dict]:
    """Progreso de todas las metas a la vez, repartiendo la plata como "sobres" entre las que
    comparten el mismo alcance (mismo total o misma cuenta), para no contar el mismo peso dos veces.

    Dentro de cada grupo se ordenan primero las con fecha limite (la mas proxima primero) y
    despues las sin fecha por antiguedad; la plata disponible se asigna en ese orden hasta llenar
    cada meta antes de pasar a la siguiente, y la fecha estimada de una meta ya considera el
    tiempo que toma terminar de llenar las anteriores, incluyendo el interes que se va generando.
    """
    resultado: dict[int, dict] = {}
    config_tasas = listar_config()

    grupos: dict[str | None, list[dict]] = {}
    for m in metas:
        grupos.setdefault(m["cuenta"], []).append(m)

    for cuenta, metas_grupo in grupos.items():
        if cuenta:
            fila = ultimo_por_cuenta[ultimo_por_cuenta["cuenta"] == cuenta]
            pool_actual = float(fila["saldo"].iloc[0]) if not fila.empty else 0.0
            ritmo = ritmo_mensual_cuenta(df_ahorros, cuenta)
            config = config_tasas.get(cuenta)
        else:
            pool_actual = float(ultimo_por_cuenta["saldo"].sum()) if not ultimo_por_cuenta.empty else 0.0
            ritmo = ritmo_mensual_total(df_trans)
            config = _config_total_ponderado(ultimo_por_cuenta, config_tasas)

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

            meses_estimados = _meses_hasta_objetivo(pool_actual, config, ritmo, objetivo_acumulado)
            fecha_estimada = (
                datetime.date.today() + datetime.timedelta(days=meses_estimados * 30.44)
                if meses_estimados
                else None
            )

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
