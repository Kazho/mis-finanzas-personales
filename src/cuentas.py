"""Cuentas de todos los bancos en un solo lugar: tipo, moneda, saldo actual y panorama consolidado.

Cada cuenta tiene un TIPO (corriente, vista, ahorro, tarjeta, inversion) y una MONEDA (CLP o USD). El tipo
decide como se cuenta en el panorama: corriente/vista/ahorro son plata disponible, inversion es patrimonio
que no se gasta a diario, y tarjeta es DEUDA (lo que debes, no plata tuya). Las cuentas en USD se muestran
en su moneda y, aparte, con un equivalente en pesos al dolar observado -- aproximado, porque cada banco
aplica su propio tipo de cambio.
"""
from src.db import get_conn

TIPOS = {
    "corriente": "Cuenta corriente",
    "vista": "Cuenta vista / RUT",
    "ahorro": "Cuenta de ahorro",
    "inversion": "Inversion",
    "tarjeta": "Tarjeta de credito",
}
TIPOS_LIQUIDOS = ("corriente", "vista", "ahorro")
MONEDAS = ("CLP", "USD")


def nombre_visible(cuenta: dict) -> str:
    return (cuenta.get("alias") or "").strip() or cuenta["nombre"]


def listar_cuentas() -> list[dict]:
    """Todas las cuentas con su saldo actual (el mas reciente entre el ultimo movimiento con saldo y el
    ultimo saldo_snapshot) y, para tarjetas, los datos del ultimo estado de cuenta cargado."""
    with get_conn() as conn:
        cuentas = [dict(r) for r in conn.execute("SELECT * FROM cuentas ORDER BY banco, nombre").fetchall()]
        for c in cuentas:
            ultimo = conn.execute(
                "SELECT saldo, fecha FROM transacciones WHERE cuenta_id = ? AND saldo IS NOT NULL "
                "ORDER BY fecha DESC, id DESC LIMIT 1",
                (c["id"],),
            ).fetchone()
            snapshot = conn.execute(
                "SELECT saldo, fecha FROM saldo_snapshot WHERE cuenta_id = ? ORDER BY fecha DESC, hora DESC LIMIT 1",
                (c["id"],),
            ).fetchone()
            elegido = ultimo
            if snapshot and (ultimo is None or snapshot["fecha"] >= ultimo["fecha"]):
                elegido = snapshot
            c["saldo"] = elegido["saldo"] if elegido else None
            c["saldo_fecha"] = elegido["fecha"] if elegido else None

            resumen = conn.execute(
                "SELECT COUNT(*) AS n, MAX(fecha) AS ultimo FROM transacciones WHERE cuenta_id = ?", (c["id"],)
            ).fetchone()
            c["n_movimientos"] = resumen["n"]
            c["ultimo_movimiento"] = resumen["ultimo"]

            estados = conn.execute(
                "SELECT * FROM tc_estados WHERE cuenta_id = ? ORDER BY periodo_hasta DESC", (c["id"],)
            ).fetchall()
            provisionales = conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(monto_cargo), 0) AS compras, COALESCE(SUM(monto_abono), 0) AS pagos "
                "FROM transacciones WHERE cuenta_id = ? AND estado = 'por_facturar'",
                (c["id"],),
            ).fetchone()
            c["tc"] = _resumen_tarjeta([dict(e) for e in estados], dict(provisionales))
    return cuentas


def _resumen_tarjeta(estados: list[dict], provisionales: dict) -> dict | None:
    """Une los datos de la tarjeta que vienen de documentos distintos: el estado facturado trae monto a pagar y
    vencimiento, y la consulta de movimientos por facturar trae el cupo. De cada dato vale el mas reciente que
    exista (`estados` viene del mas nuevo al mas viejo).

    Tambien calcula lo que sigue pendiente: del monto facturado se descuentan los pagos hechos DESPUES del
    corte (aparecen como abonos por facturar), y las compras por facturar son lo que viene en el proximo corte."""
    if not estados:
        return None
    campos = ("monto_facturado", "pago_minimo", "fecha_vencimiento", "cupo_total", "cupo_utilizado", "cupo_disponible")
    tc = {"periodo_hasta": estados[0]["periodo_hasta"]}
    for campo in campos:
        tc[campo] = next((e[campo] for e in estados if e[campo] is not None), None)
    tc["por_facturar"] = round(provisionales["compras"], 2)
    tc["pagos_posteriores"] = round(provisionales["pagos"], 2)
    tc["n_provisionales"] = provisionales["n"]
    if tc["monto_facturado"] is not None:
        tc["facturado_pendiente"] = max(0.0, round(tc["monto_facturado"] - provisionales["pagos"], 2))
    else:
        tc["facturado_pendiente"] = None
    return tc


def actualizar_cuenta(cuenta_id: int, *, alias: str, banco: str, tipo: str, moneda: str, archivada: bool):
    if tipo not in TIPOS:
        raise ValueError(f"Tipo de cuenta invalido: {tipo!r}")
    if moneda not in MONEDAS:
        raise ValueError(f"Moneda invalida: {moneda!r}")
    with get_conn() as conn:
        conn.execute(
            "UPDATE cuentas SET alias = ?, banco = ?, tipo = ?, moneda = ?, archivada = ? WHERE id = ?",
            ((alias or "").strip() or None, (banco or "").strip() or None, tipo, moneda, int(archivada), cuenta_id),
        )


def deuda_tarjeta(cuenta: dict) -> float | None:
    """Lo que se debe en la tarjeta: cupo utilizado del ultimo estado de cuenta (incluye las cuotas
    futuras ya comprometidas); si ese dato no viene, el monto facturado a pagar."""
    tc = cuenta.get("tc")
    if not tc:
        return None
    if tc.get("cupo_utilizado") is not None:
        return tc["cupo_utilizado"]
    return tc.get("monto_facturado")


def _a_clp(monto: float, moneda: str, dolar: float | None) -> float | None:
    if moneda == "CLP":
        return monto
    return monto * dolar if dolar else None


def resumen_panorama(cuentas: list[dict], dolar: float | None) -> dict:
    """Totales consolidados de las cuentas activas.

    `disponible`, `inversion` y `deuda` vienen por moneda ({"CLP": x, "USD": y}); `*_clp` suman todo en
    pesos usando `dolar` (None si no hay tipo de cambio: las cuentas en USD quedan fuera de esa suma y
    `usd_sin_convertir` avisa). `por_banco` agrupa lo mismo por banco para la vista de detalle."""
    vacio = lambda: {"CLP": 0.0, "USD": 0.0}
    disponible, inversion, deuda = vacio(), vacio(), vacio()
    por_banco: dict[str, dict] = {}
    sin_datos = []

    for c in cuentas:
        if c.get("archivada"):
            continue
        banco = c.get("banco") or "Sin banco"
        fila = por_banco.setdefault(banco, {"disponible_clp": 0.0, "inversion_clp": 0.0, "deuda_clp": 0.0, "cuentas": []})
        fila["cuentas"].append(c)
        moneda = c.get("moneda") or "CLP"

        if c["tipo"] == "tarjeta":
            monto = deuda_tarjeta(c)
            destino, clave = deuda, "deuda_clp"
        elif c["tipo"] == "inversion":
            monto = c.get("saldo")
            destino, clave = inversion, "inversion_clp"
        else:
            monto = c.get("saldo")
            destino, clave = disponible, "disponible_clp"

        if monto is None:
            sin_datos.append(c)
            continue
        destino[moneda] += monto
        en_clp = _a_clp(monto, moneda, dolar)
        if en_clp is not None:
            fila[clave] += en_clp

    def _total_clp(por_moneda):
        return por_moneda["CLP"] + (por_moneda["USD"] * dolar if dolar else 0.0)

    disponible_clp, inversion_clp, deuda_clp = _total_clp(disponible), _total_clp(inversion), _total_clp(deuda)
    return {
        "disponible": disponible, "inversion": inversion, "deuda": deuda,
        "disponible_clp": disponible_clp, "inversion_clp": inversion_clp, "deuda_clp": deuda_clp,
        "neto_clp": disponible_clp + inversion_clp - deuda_clp,
        "usd_sin_convertir": (not dolar) and any(v["USD"] for v in (disponible, inversion, deuda)),
        "por_banco": por_banco,
        "sin_datos": sin_datos,
    }


def preparar_transacciones(df, dolar: float | None):
    """Deja el DataFrame de movimientos listo para el analisis de gastos del Dashboard.

    1. Concilia pagos de tarjeta y traspasos entre cuentas propias (ver src/conciliacion.py) ANTES de
       convertir, cuando los montos todavia estan en su moneda original (el dolar sirve para conciliar el pago
       de una tarjeta en USD hecho desde una cuenta en pesos).
    2. Convierte los movimientos en USD a pesos con el dolar observado (aproximado); sin dolar se dejan
       fuera, porque sumar dolares como si fueran pesos falsearia todos los totales.
    3. Anula `saldo` en tarjetas, cuentas en USD y cuentas archivadas: el Dashboard suma el ultimo saldo
       de cada cuenta como "saldo cuenta corriente", y eso solo tiene sentido para cuentas en pesos.

    Espera las columnas de `conciliar_traspasos` mas `archivada` y `saldo`. En `.attrs` deja
    `n_conciliados`, `n_usd_convertidos` y `n_usd_omitidos` para avisar al usuario."""
    from src.conciliacion import conciliar_traspasos

    df = conciliar_traspasos(df, dolar)
    n_conciliados = df.attrs.get("n_conciliados", 0)
    n_usd_convertidos = n_usd_omitidos = 0
    if not df.empty:
        es_usd = df["moneda"] == "USD"
        if dolar:
            df.loc[es_usd, ["monto_cargo", "monto_abono"]] = df.loc[es_usd, ["monto_cargo", "monto_abono"]] * dolar
            n_usd_convertidos = int(es_usd.sum())
        else:
            n_usd_omitidos = int(es_usd.sum())
            df = df[~es_usd].copy()
        sin_saldo_util = (df["moneda"] != "CLP") | (df["tipo"] == "tarjeta") | (df["archivada"] == 1)
        df.loc[sin_saldo_util, "saldo"] = None
    df.attrs.update(n_conciliados=n_conciliados, n_usd_convertidos=n_usd_convertidos, n_usd_omitidos=n_usd_omitidos)
    return df
