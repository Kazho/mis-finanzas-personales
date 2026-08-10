"""Proyeccion de rentabilidad de cuentas de ahorro segun una tasa anual configurada.

Soporta una tasa simple, o una tasa en dos tramos (por ejemplo cuando la
plataforma paga mas sobre cierto monto, o con un plan premium que hay que
pagar mensualmente): el tramo hasta `monto_umbral` gana `tasa_base`, y lo que
excede ese monto gana `tasa_premium`. Si el tramo tiene un `costo_mensual`
asociado (por ejemplo, la suscripcion a un plan premium), la ganancia se
calcula comparando "activar el tramo pagando el costo" contra "no activarlo y
ganar la tasa_premium (la tasa normal, sin costo) sobre todo el saldo", y se
usa la que convenga mas segun el saldo actual. Asi, con saldos chicos donde el
costo no se justifica, la proyeccion automaticamente recomienda no pagar el plan.
"""
import datetime

from src.db import get_conn


def obtener_config(cuenta: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM ahorros_config WHERE cuenta = ?", (cuenta,)).fetchone()
    return dict(row) if row else None


def listar_config() -> dict[str, dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM ahorros_config").fetchall()
    return {r["cuenta"]: dict(r) for r in rows}


def guardar_config(
    cuenta: str,
    tasa_base: float,
    monto_umbral: float | None,
    tasa_premium: float | None,
    costo_mensual: float | None = None,
):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO ahorros_config (cuenta, tasa_base, monto_umbral, tasa_premium, costo_mensual)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(cuenta) DO UPDATE SET
                tasa_base = excluded.tasa_base,
                monto_umbral = excluded.monto_umbral,
                tasa_premium = excluded.tasa_premium,
                costo_mensual = excluded.costo_mensual
            """,
            (cuenta, tasa_base, monto_umbral, tasa_premium, costo_mensual),
        )


def _ganancia_con_tramo(saldo: float, config: dict) -> float:
    tasa_base = config["tasa_base"] / 100
    umbral = config["monto_umbral"]
    tramo_base = min(saldo, umbral)
    tramo_extra = max(0.0, saldo - umbral)
    costo_anual = (config.get("costo_mensual") or 0) * 12
    return tramo_base * tasa_base + tramo_extra * (config["tasa_premium"] / 100) - costo_anual


def calcular_ganancia_anual(saldo: float, config: dict | None) -> float:
    """Ganancia estimada en un año si el saldo se mantiene constante, con interes simple."""
    if not config or not config.get("tasa_base"):
        return 0.0

    umbral = config.get("monto_umbral")
    tasa_premium = config.get("tasa_premium")

    if umbral is not None and tasa_premium is not None:
        ganancia_sin_tramo = saldo * (tasa_premium / 100)
        ganancia_con_tramo = _ganancia_con_tramo(saldo, config)
        return max(ganancia_con_tramo, ganancia_sin_tramo)

    return saldo * (config["tasa_base"] / 100)


def evaluar_plan_con_costo(saldo: float, config: dict | None) -> dict | None:
    """Para tramos con costo mensual (ej. un plan premium): compara activarlo o no al saldo actual.

    Devuelve None si la cuenta no tiene un tramo con costo configurado.
    """
    if not config or not config.get("tasa_base") or not config.get("costo_mensual"):
        return None
    if config.get("monto_umbral") is None or config.get("tasa_premium") is None:
        return None

    ganancia_con = _ganancia_con_tramo(saldo, config)
    ganancia_sin = saldo * (config["tasa_premium"] / 100)
    costo_anual = config["costo_mensual"] * 12
    tasa_base = config["tasa_base"] / 100
    tasa_normal = config["tasa_premium"] / 100

    punto_equilibrio = costo_anual / (tasa_base - tasa_normal) if tasa_base > tasa_normal else None

    return {
        "conviene_activar": ganancia_con > ganancia_sin,
        "ganancia_activando": ganancia_con,
        "ganancia_sin_activar": ganancia_sin,
        "diferencia": ganancia_con - ganancia_sin,
        "costo_anual": costo_anual,
        "punto_equilibrio": punto_equilibrio,
    }


def tasa_efectiva(saldo: float, config: dict | None) -> float:
    """Tasa anual equivalente (%) resultante de aplicar la ganancia calculada sobre el saldo."""
    if not saldo or not config:
        return 0.0
    return calcular_ganancia_anual(saldo, config) / saldo * 100


def meses_entre(desde: datetime.date, hasta: datetime.date) -> int:
    """Meses completos entre dos fechas (redondeando hacia arriba), minimo 0."""
    dias = (hasta - desde).days
    if dias <= 0:
        return 0
    return max(1, round(dias / 30.44))


def proyectar_saldo(saldo_inicial: float, config: dict | None, ritmo_mensual: float | None, meses: int) -> dict:
    """Simula mes a mes el saldo de una cuenta hasta una fecha, sumando aportes estimados
    (segun el ritmo de ahorro reciente) y el interes de cada mes segun la tasa configurada.

    Se hace mes a mes (no con una formula cerrada) porque asi el interes se recalcula sobre el
    saldo que va creciendo con los aportes, y si la cuenta tiene tramos (ej. plan premium con
    tope), el mes en que el saldo cruza el tope tambien queda bien reflejado.
    """
    saldo = saldo_inicial
    total_aportado = 0.0
    total_intereses = 0.0
    aporte = ritmo_mensual or 0.0

    for _ in range(meses):
        if aporte > 0:
            saldo += aporte
            total_aportado += aporte
        interes_mes = calcular_ganancia_anual(saldo, config) / 12
        saldo += interes_mes
        total_intereses += interes_mes

    return {
        "saldo_proyectado": saldo,
        "total_aportado": total_aportado,
        "total_intereses": total_intereses,
        "meses": meses,
    }


def simular_dap(monto: float, tasa_pct: float, dias: int, tasa_es_anual: bool = False) -> dict:
    """Simula un Deposito a Plazo (DAP).

    La mayoria de los simuladores de bancos chilenos muestran la "tasa del periodo" (la tasa ya
    calculada para el plazo completo, ej. "0,30% a 30 dias" — ahi la ganancia es directa:
    monto * tasa). Si en vez de eso tienes una tasa anual, hay que prorratearla por los dias del
    plazo (`tasa_es_anual=True`).
    """
    if tasa_es_anual:
        ganancia = monto * (tasa_pct / 100) * (dias / 365)
    else:
        ganancia = monto * (tasa_pct / 100)
    return {"monto_inicial": monto, "ganancia": ganancia, "monto_final": monto + ganancia, "dias": dias}


def optimizar_asignacion(total: float, config_por_cuenta: dict[str, dict]) -> list[dict]:
    """Reparte `total` entre las cuentas configuradas para maximizar la ganancia anual.

    Cada cuenta aporta uno o dos "tramos" de tasa (base, y premium si tiene tope). Se listan
    todos los tramos de todas las cuentas ordenados de mayor a menor tasa, y se llenan en ese
    orden con el dinero disponible. Esto es optimo cuando los tramos no tienen costo fijo; si
    una cuenta tiene un costo mensual asociado (plan premium), no se considera aqui — revisa
    la seccion de "cuanto generaria si dejo la plata donde esta" para esos casos.
    """
    segmentos = []
    for cuenta, cfg in config_por_cuenta.items():
        if not cfg or not cfg.get("tasa_base"):
            continue
        umbral = cfg.get("monto_umbral")
        tasa_premium = cfg.get("tasa_premium")
        if umbral is not None and tasa_premium is not None:
            segmentos.append({"cuenta": cuenta, "tasa": cfg["tasa_base"], "capacidad": umbral})
            segmentos.append({"cuenta": cuenta, "tasa": tasa_premium, "capacidad": float("inf")})
        else:
            segmentos.append({"cuenta": cuenta, "tasa": cfg["tasa_base"], "capacidad": float("inf")})

    segmentos.sort(key=lambda s: -s["tasa"])

    restante = total
    asignacion: dict[str, dict] = {}
    for seg in segmentos:
        if restante <= 0:
            break
        monto = min(seg["capacidad"], restante)
        if monto <= 0:
            continue
        entrada = asignacion.setdefault(seg["cuenta"], {"monto_asignado": 0.0, "ganancia": 0.0})
        entrada["monto_asignado"] += monto
        entrada["ganancia"] += monto * seg["tasa"] / 100
        restante -= monto

    resultado = [{"cuenta": c, **v} for c, v in asignacion.items()]
    resultado.sort(key=lambda r: -r["ganancia"])
    return resultado
