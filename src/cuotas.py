"""Compras en cuotas con tarjeta de credito: cuanto de tus proximas facturaciones ya esta comprometido.

La app no lee la cartola de la tarjeta, asi que cada compra en cuotas se registra a mano (descripcion,
valor de la cuota, total de cuotas y cuantas ya se facturaron). Internamente se guarda el MES de la
primera cuota (YYYY-MM) en vez de "cuotas pagadas", para que el conteo avance solo con el tiempo sin
tener que actualizar nada: la cuota k se factura en el mes `mes_primera_cuota + (k - 1)`.
"""
import datetime

import pandas as pd

from src.db import get_conn


def _mes(fecha: datetime.date) -> pd.Period:
    return pd.Period(fecha, freq="M")


def listar_compras() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM compras_cuotas ORDER BY mes_primera_cuota, id").fetchall()
    return [dict(r) for r in rows]


def agregar_compra(descripcion: str, valor_cuota: float, total_cuotas: int, cuotas_ya_facturadas: int,
                   hoy: datetime.date | None = None):
    """`cuotas_ya_facturadas` son las que ya aparecieron en estados de cuenta ANTERIORES: la
    siguiente (la numero cuotas_ya_facturadas + 1) se factura en el mes actual."""
    hoy = hoy or datetime.date.today()
    mes_primera = _mes(hoy) - cuotas_ya_facturadas
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO compras_cuotas (descripcion, valor_cuota, total_cuotas, mes_primera_cuota, fecha_registro) VALUES (?, ?, ?, ?, ?)",
            (descripcion, valor_cuota, total_cuotas, str(mes_primera), hoy.isoformat()),
        )


def eliminar_compra(compra_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM compras_cuotas WHERE id = ?", (compra_id,))


def estado_compra(compra: dict, hoy: datetime.date | None = None) -> dict:
    """Cuota que se factura este mes, cuantas quedan (incluida la de este mes) y el ultimo mes."""
    hoy = hoy or datetime.date.today()
    primera = pd.Period(compra["mes_primera_cuota"], freq="M")
    ultima = primera + (compra["total_cuotas"] - 1)
    cuota_actual = (_mes(hoy) - primera).n + 1
    pendientes = max(0, min(compra["total_cuotas"], compra["total_cuotas"] - cuota_actual + 1))
    return {
        "cuota_actual": cuota_actual,
        "pendientes": pendientes,
        "saldo_pendiente": pendientes * compra["valor_cuota"],
        "ultimo_mes": str(ultima),
        "terminada": pendientes == 0,
    }


def compromiso_por_mes(compras: list[dict], meses: int = 12, hoy: datetime.date | None = None) -> pd.DataFrame:
    """Monto total en cuotas que se factura en cada uno de los proximos `meses` (incluido el actual)."""
    hoy = hoy or datetime.date.today()
    inicio = _mes(hoy)
    periodos = [inicio + i for i in range(meses)]
    montos = dict.fromkeys(periodos, 0.0)
    for compra in compras:
        primera = pd.Period(compra["mes_primera_cuota"], freq="M")
        ultima = primera + (compra["total_cuotas"] - 1)
        for p in periodos:
            if primera <= p <= ultima:
                montos[p] += compra["valor_cuota"]
    return pd.DataFrame({"mes": [str(p) for p in periodos], "monto": list(montos.values())})
