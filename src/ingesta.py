"""Guardado de lotes de movimientos: el UNICO camino de entrada de datos a la base, venga de un archivo o de una API.

Antes esta logica vivia dentro de la pantalla "Cargar Cartola". Moverla aca tiene dos efectos: la pantalla queda
solo como interfaz, y una futura sincronizacion automatica (conector) pasa por exactamente las mismas reglas:

  * Todo el lote se valida primero (`LoteImportacion.validar`) y se guarda en UNA transaccion: si algo falla no
    queda un lote a medias.
  * Idempotencia: si el movimiento trae `id_externo` se identifica por (cuenta, id_externo), y si ya existia se
    ACTUALIZA lo que el banco pueda haber cambiado (un pendiente que pasa a contabilizado, un monto corregido);
    si no lo trae, se identifica por `hash_dedupe`. Nunca se pisa la categoria que eligio el usuario.
  * Los movimientos provisionales (por facturar) se reemplazan segun la regla del lote.
  * Cada movimiento queda con su fuente y un UUID global (lo asigna el trigger de la base si no se pasa).
"""
import uuid
from dataclasses import dataclass

from src.db import (
    get_conn,
    get_or_create_cuenta,
    guardar_estado_tc,
    guardar_saldo_snapshot,
    reemplazar_provisionales,
)
from src.fuentes.contrato import REEMPLAZA_HASTA_CORTE, REEMPLAZA_TODOS, LoteImportacion

CATEGORIA_POR_DEFECTO = "Sin categoria"


@dataclass
class ResultadoIngesta:
    cuenta_id: int
    nuevas: int = 0
    actualizadas: int = 0
    duplicadas: int = 0
    reemplazadas: int = 0


def guardar_lote(
    lote: LoteImportacion,
    *,
    categorias: list[str] | None = None,
    manuales: list[int] | None = None,
    banco: str | None = None,
) -> ResultadoIngesta:
    """Guarda `lote` en la base. `categorias` y `manuales` (opcionales) van alineados con `lote.movimientos`:
    la categoria elegida para cada uno y si el usuario la cambio a mano. `banco` pisa al del lote."""
    banco_final = banco or lote.cuenta.banco
    if not banco_final:
        raise ValueError("Falta el banco de la cuenta: el documento no lo indica y no se eligio uno.")
    lote.validar()
    n = len(lote.movimientos)
    if categorias is not None and len(categorias) != n:
        raise ValueError("`categorias` debe tener una entrada por movimiento.")
    if manuales is not None and len(manuales) != n:
        raise ValueError("`manuales` debe tener una entrada por movimiento.")

    with get_conn() as conn:  # una sola transaccion: o se guarda todo el lote o nada
        cuenta_id = get_or_create_cuenta(
            lote.cuenta.nombre(banco_final), banco=banco_final, numero_cuenta=lote.cuenta.numero,
            tipo=lote.cuenta.tipo, moneda=lote.cuenta.moneda, id_externo=lote.cuenta.id_externo,
        )
        res = ResultadoIngesta(cuenta_id=cuenta_id)

        if lote.reemplaza_provisionales == REEMPLAZA_TODOS:
            res.reemplazadas = reemplazar_provisionales(cuenta_id)
        elif lote.reemplaza_provisionales == REEMPLAZA_HASTA_CORTE:
            res.reemplazadas = reemplazar_provisionales(cuenta_id, lote.periodo_hasta.isoformat())

        for i, m in enumerate(lote.movimientos):
            categoria = categorias[i] if categorias else CATEGORIA_POR_DEFECTO
            manual = manuales[i] if manuales else 0

            if m.id_externo is not None:
                existente = conn.execute(
                    "SELECT id, estado, monto_cargo, monto_abono, descripcion FROM transacciones "
                    "WHERE cuenta_id = ? AND id_externo = ?",
                    (cuenta_id, m.id_externo),
                ).fetchone()
                if existente is not None:
                    cambio = (existente["estado"], existente["monto_cargo"], existente["monto_abono"], existente["descripcion"]) != (
                        m.estado, m.monto_cargo, m.monto_abono, m.descripcion,
                    )
                    if cambio:
                        # El banco puede contabilizar o corregir un movimiento; la categoria es del usuario y no se toca.
                        conn.execute(
                            "UPDATE transacciones SET estado = ?, monto_cargo = ?, monto_abono = ?, descripcion = ?, "
                            "saldo = ?, sucursal = ? WHERE id = ?",
                            (m.estado, m.monto_cargo, m.monto_abono, m.descripcion, m.saldo, m.sucursal, existente["id"]),
                        )
                        res.actualizadas += 1
                    else:
                        res.duplicadas += 1
                    continue

            cur = conn.execute(
                """
                INSERT OR IGNORE INTO transacciones
                    (cuenta_id, fecha, descripcion, sucursal, monto_cargo, monto_abono, saldo, categoria,
                     categoria_manual, cartola_numero, archivo_origen, hash_dedupe, estado, fuente, id_externo, uid)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cuenta_id, m.fecha.isoformat(), m.descripcion, m.sucursal, m.monto_cargo, m.monto_abono, m.saldo,
                    categoria, manual, lote.cartola_numero, lote.origen.nombre, m.hash_dedupe, m.estado,
                    lote.origen.tipo, m.id_externo, uuid.uuid4().hex,
                ),
            )
            if cur.rowcount:
                res.nuevas += 1
            else:
                res.duplicadas += 1

        if lote.estado_tc:
            guardar_estado_tc(cuenta_id, lote.estado_tc)
        if lote.saldo_snapshot is not None:
            s = lote.saldo_snapshot
            guardar_saldo_snapshot(cuenta_id, s.fecha.isoformat(), s.hora, s.saldo)
    return res
