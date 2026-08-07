"""Analisis de gastos por mes: comparacion mes a mes y alertas por categoria."""
import pandas as pd


def _con_mes(df_trans: pd.DataFrame) -> pd.DataFrame:
    df = df_trans.copy()
    df["mes"] = df["fecha"].dt.to_period("M")
    return df


def gasto_por_mes(df_trans: pd.DataFrame) -> pd.Series:
    df = _con_mes(df_trans)
    return df[df["monto_cargo"] > 0].groupby("mes")["monto_cargo"].sum().sort_index()


def gasto_por_categoria_mes(df_trans: pd.DataFrame) -> pd.DataFrame:
    df = _con_mes(df_trans)
    return df[df["monto_cargo"] > 0].groupby(["mes", "categoria"], as_index=False)["monto_cargo"].sum()


def comparacion_mes_actual(df_trans: pd.DataFrame) -> dict | None:
    """Compara el gasto total del ultimo mes con datos contra el mes inmediatamente anterior.

    Devuelve None si no hay al menos dos meses distintos con transacciones.
    """
    serie = gasto_por_mes(df_trans)
    if len(serie) < 2:
        return None

    mes_actual, mes_anterior = serie.index[-1], serie.index[-2]
    gasto_actual, gasto_anterior = float(serie.iloc[-1]), float(serie.iloc[-2])
    diferencia = gasto_actual - gasto_anterior
    porcentaje = (diferencia / gasto_anterior * 100) if gasto_anterior else None

    return {
        "mes_actual": str(mes_actual),
        "mes_anterior": str(mes_anterior),
        "gasto_actual": gasto_actual,
        "gasto_anterior": gasto_anterior,
        "diferencia": diferencia,
        "porcentaje": porcentaje,
    }


def comparacion_por_categoria(df_trans: pd.DataFrame) -> pd.DataFrame:
    """Gasto por categoria del mes actual y del anterior, lado a lado."""
    cat_mes = gasto_por_categoria_mes(df_trans)
    if cat_mes.empty:
        return pd.DataFrame(columns=["mes", "categoria", "monto_cargo"])
    meses = sorted(cat_mes["mes"].unique())
    if len(meses) < 2:
        return pd.DataFrame(columns=["mes", "categoria", "monto_cargo"])
    mes_actual, mes_anterior = meses[-1], meses[-2]
    comp = cat_mes[cat_mes["mes"].isin([mes_anterior, mes_actual])].copy()
    comp["mes"] = comp["mes"].astype(str)
    return comp


CATEGORIAS_POSITIVAS = ("ahorro", "inversion", "inversión")


def _es_categoria_positiva(categoria: str) -> bool:
    texto = categoria.lower()
    return any(palabra in texto for palabra in CATEGORIAS_POSITIVAS)


def _categorias_sobre_promedio(df_trans: pd.DataFrame, umbral: float, min_meses_historia: int) -> pd.DataFrame:
    """Categorias donde el monto del mes actual supera `umbral` veces el promedio historico."""
    cat_mes = gasto_por_categoria_mes(df_trans)
    if cat_mes.empty:
        return pd.DataFrame()

    mes_actual = cat_mes["mes"].max()
    historico = cat_mes[cat_mes["mes"] < mes_actual]
    if historico.empty:
        return pd.DataFrame()

    promedio = historico.groupby("categoria").agg(promedio=("monto_cargo", "mean"), n_meses=("monto_cargo", "count"))
    actual = cat_mes[cat_mes["mes"] == mes_actual].set_index("categoria")["monto_cargo"].rename("actual")

    combinado = promedio.join(actual, how="inner")
    combinado = combinado[combinado["n_meses"] >= min_meses_historia]
    combinado = combinado[combinado["actual"] > combinado["promedio"] * umbral]
    if combinado.empty:
        return pd.DataFrame()

    combinado = combinado.copy()
    combinado["exceso_pct"] = (combinado["actual"] / combinado["promedio"] - 1) * 100
    return combinado.reset_index().sort_values("actual", ascending=False)


def alertas_categoria(df_trans: pd.DataFrame, umbral: float = 1.3, min_meses_historia: int = 2) -> list[dict]:
    """Categorias de gasto (no de ahorro/inversion) donde el mes actual supera el promedio historico.

    `umbral` es el multiplicador sobre el promedio (1.3 = 30% mas que lo habitual). Una
    categoria solo genera alerta si tiene al menos `min_meses_historia` meses previos con
    gasto registrado, para no marcar falsos positivos por falta de datos. Las categorias que
    representan ahorro o inversion (ej. "Ahorro") no se consideran una alerta negativa — ver
    `logros_ahorro`.
    """
    combinado = _categorias_sobre_promedio(df_trans, umbral, min_meses_historia)
    if combinado.empty:
        return []
    combinado = combinado[~combinado["categoria"].apply(_es_categoria_positiva)]
    return combinado.to_dict("records")


def logros_ahorro(df_trans: pd.DataFrame, umbral: float = 1.3, min_meses_historia: int = 2) -> list[dict]:
    """Categorias de ahorro/inversion donde el mes actual supera el promedio historico: un buen dato, no una alerta."""
    combinado = _categorias_sobre_promedio(df_trans, umbral, min_meses_historia)
    if combinado.empty:
        return []
    combinado = combinado[combinado["categoria"].apply(_es_categoria_positiva)]
    return combinado.to_dict("records")
