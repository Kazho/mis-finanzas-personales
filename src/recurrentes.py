"""Deteccion de gastos recurrentes y suscripciones (Netflix, gimnasio, seguros, PAC, etc.) a partir de
las transacciones de la cartola -- sin que el usuario tenga que marcarlos a mano.

Un cobro se considera recurrente cuando el mismo comercio (misma descripcion normalizada) aparece:
- en al menos `MIN_MESES` meses distintos,
- con a lo sumo ~1 cobro por mes (si hay varios por mes es un comercio frecuente, como un cafe o
  Uber, no una suscripcion),
- cada ~mes (mediana de dias entre cobros dentro de [`DIAS_MIN`, `DIAS_MAX`]), y
- por un monto parecido (desviacion mediana relativa <= `VARIACION_MAX`), para no confundir un
  comercio donde compras seguido con un cobro fijo.

Solo se muestran los recurrentes ACTIVOS (el ultimo cobro fue hace menos de `DIAS_ACTIVO` dias
respecto de la ultima transaccion cargada), para no seguir contando suscripciones ya canceladas.
"""
import re

import pandas as pd

from src.analisis_gastos import es_categoria_ahorro, es_categoria_ingreso

MIN_MESES = 3
MAX_COBROS_POR_MES = 1.25
DIAS_MIN, DIAS_MAX = 24, 37
VARIACION_MAX = 0.15
DIAS_ACTIVO = 45
UMBRAL_ALZA = 0.05  # subida de precio minima para avisar (5%)
DIAS_NUEVO = 100  # "nuevo" = primer cobro dentro de los ultimos ~3 meses

# El pago de la tarjeta es recurrente por naturaleza pero no es una suscripcion (es el total de
# otros gastos), asi que se excluye igual que el ahorro y los ingresos.
CATEGORIAS_EXCLUIDAS = ("pago tarjeta de credito",)


def _normalizar(descripcion: str) -> str:
    """Quita numeros y signos que cambian entre cobros del mismo comercio (ej. numero de boleta)."""
    texto = re.sub(r"\d+", "", descripcion.lower())
    texto = re.sub(r"[^a-záéíóúñ*: ]", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _excluida(categoria: str | None) -> bool:
    if not categoria:
        return False
    return es_categoria_ahorro(categoria) or es_categoria_ingreso(categoria) or categoria.lower() in CATEGORIAS_EXCLUIDAS


def detectar_recurrentes(df_trans: pd.DataFrame) -> pd.DataFrame:
    """Devuelve un DataFrame con una fila por gasto recurrente activo:
    comercio, categoria, monto_tipico, ultimo_monto, ultima_fecha, proximo_cobro, n_cobros,
    alza_pct (None si no subio), es_nuevo, costo_anual. Ordenado por costo anual descendente."""
    columnas = ["comercio", "categoria", "monto_tipico", "ultimo_monto", "ultima_fecha", "proximo_cobro",
                "n_cobros", "alza_pct", "es_nuevo", "costo_anual"]
    if df_trans.empty:
        return pd.DataFrame(columns=columnas)

    cargos = df_trans[(df_trans["monto_cargo"] > 0) & ~df_trans["categoria"].apply(_excluida)].copy()
    if cargos.empty:
        return pd.DataFrame(columns=columnas)
    cargos["clave"] = cargos["descripcion"].map(_normalizar)
    fecha_ref = df_trans["fecha"].max()

    filas = []
    for _, grupo in cargos.groupby("clave"):
        grupo = grupo.sort_values("fecha")
        n_meses = grupo["fecha"].dt.to_period("M").nunique()
        if n_meses < MIN_MESES or len(grupo) / n_meses > MAX_COBROS_POR_MES:
            continue

        intervalos = grupo["fecha"].diff().dt.days.dropna()
        if intervalos.empty or not (DIAS_MIN <= intervalos.median() <= DIAS_MAX):
            continue

        montos = grupo["monto_cargo"]
        mediana = float(montos.median())
        if mediana <= 0 or float((montos - mediana).abs().median()) / mediana > VARIACION_MAX:
            continue

        ultima = grupo.iloc[-1]
        if (fecha_ref - ultima["fecha"]).days > DIAS_ACTIVO:
            continue

        # El alza se mide contra la mediana de los cobros ANTERIORES, para que el ultimo cobro (el
        # que subio) no arrastre la referencia hacia arriba.
        referencia = float(montos.iloc[:-1].median())
        alza = (ultima["monto_cargo"] / referencia - 1) if referencia else 0.0

        filas.append({
            "comercio": ultima["descripcion"],
            "categoria": ultima["categoria"],
            "monto_tipico": mediana,
            "ultimo_monto": float(ultima["monto_cargo"]),
            "ultima_fecha": ultima["fecha"].date(),
            "proximo_cobro": (ultima["fecha"] + pd.Timedelta(days=round(intervalos.median()))).date(),
            "n_cobros": len(grupo),
            "alza_pct": alza * 100 if alza >= UMBRAL_ALZA else None,
            "es_nuevo": (fecha_ref - grupo["fecha"].iloc[0]).days <= DIAS_NUEVO,
            "costo_anual": float(ultima["monto_cargo"]) * 12,
        })

    if not filas:
        return pd.DataFrame(columns=columnas)
    return pd.DataFrame(filas, columns=columnas).sort_values("costo_anual", ascending=False).reset_index(drop=True)
