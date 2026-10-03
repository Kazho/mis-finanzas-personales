"""Hash de deduplicacion de transacciones, compartido entre los distintos parsers de PDF.

Se basa solo en cuenta + fecha + descripcion + montos + saldo — deliberadamente NO incluye
el numero de cartola ni la sucursal/canal, porque Banco de Chile entrega la misma transaccion
con textos ligeramente distintos segun el documento (ej. cartola oficial mensual vs el PDF de
"Movimientos al [fecha]" que se puede descargar en cualquier momento): la sucursal aparece como
"OF. PZA BULNES" en una y "Plaza Bulnes" en la otra, y la descripcion cambia de mayusculas a
capitalizado. Si cargas primero un PDF de movimientos a mitad de mes y despues la cartola oficial
que cubre las mismas fechas, el saldo por fila (que es un numero real de tu cuenta en ese momento)
sigue siendo el mismo en ambos documentos, asi que es la forma mas confiable de reconocer que es
la misma transaccion sin duplicarla.
"""
import hashlib
import datetime


def hash_transaccion(
    numero_cuenta: str,
    fecha: datetime.date,
    descripcion: str,
    monto_cargo: float,
    monto_abono: float,
    saldo: float | None,
) -> str:
    base = "|".join(
        str(x)
        for x in (numero_cuenta, fecha, descripcion.strip().upper(), monto_cargo, monto_abono, saldo)
    )
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def asignar_hashes(transacciones: list[dict], clave_cuenta: str) -> None:
    """Pone `hash_dedupe` a cada movimiento de una cuenta SIN saldo por fila (tarjetas de credito).

    Sin saldo, dos compras identicas el mismo dia (mismo comercio y monto) darian el mismo hash y la
    segunda se descartaria como duplicada: se distinguen por orden de aparicion. `clave_cuenta` debe
    incluir la moneda si la misma tarjeta tiene cuentas en CLP y USD."""
    vistos: dict[tuple, int] = {}
    for t in transacciones:
        clave = (t["fecha"], t["descripcion"], t["monto_cargo"], t["monto_abono"])
        vistos[clave] = vistos.get(clave, 0) + 1
        sufijo = f" #{vistos[clave]}" if vistos[clave] > 1 else ""
        t["hash_dedupe"] = hash_transaccion(
            clave_cuenta, t["fecha"], t["descripcion"] + sufijo, t["monto_cargo"], t["monto_abono"], None
        )
