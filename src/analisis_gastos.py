"""Analisis de gastos por mes: comparacion mes a mes y alertas por categoria."""
import pandas as pd

from src.categorias import BUCKETS, SIN_CLASIFICAR
from src.conciliacion import CATEGORIA_TRASPASO

CATEGORIAS_POSITIVAS = ("ahorro", "inversion", "inversión")
CATEGORIAS_INGRESO = ("ingreso", "transferencia recibida", CATEGORIA_TRASPASO.lower())


def es_categoria_ahorro(categoria: str) -> bool:
    """Categorias que representan plata movida a ahorro/inversion, no consumo real.

    Se usan para excluirlas de los totales y graficos de "gasto" (no es gasto, es plata que
    sigue siendo tuya) y para mostrarlas por separado como un buen dato en vez de una alerta.
    """
    texto = categoria.lower()
    return any(palabra in texto for palabra in CATEGORIAS_POSITIVAS)


def es_categoria_ingreso(categoria: str) -> bool:
    """Categorias que representan ingresos genuinos (sueldo, transferencias recibidas sin
    asociar a un gasto propio) o movimientos entre tus propias cuentas ya conciliados (pago de
    tarjeta, traspasos: no son ni gasto ni ingreso), para no restarlos del gasto al netear cargos
    y abonos.

    Si quieres que un abono SI descuente del gasto (ej. te devuelven tu parte de una salida
    grupal), categorizalo con la MISMA categoria del gasto original en vez de dejarlo aqui.
    """
    texto = categoria.lower()
    return any(palabra in texto for palabra in CATEGORIAS_INGRESO)


def _con_mes(df_trans: pd.DataFrame) -> pd.DataFrame:
    df = df_trans.copy()
    df["mes"] = df["fecha"].dt.to_period("M")
    return df


def gasto_por_categoria_mes(df_trans: pd.DataFrame) -> pd.DataFrame:
    """Monto NETO (cargos menos abonos) por mes y categoria, incluyendo ahorro e ingreso (se
    filtran despues segun el uso).

    Es neto para que un reembolso categorizado en la MISMA categoria del gasto original (ej.
    alguien te devuelve su parte de una salida grupal que tu pagaste completa) descuente del
    gasto de ese mes, en vez de aparecer como un ingreso suelto que no compensa nada y deja el
    gasto de esa categoria inflado."""
    df = _con_mes(df_trans)
    agg = df.groupby(["mes", "categoria"], as_index=False).agg(
        _cargo=("monto_cargo", "sum"), _abono=("monto_abono", "sum")
    )
    agg["monto_cargo"] = agg["_cargo"] - agg["_abono"]
    return agg[["mes", "categoria", "monto_cargo"]]


def gasto_por_mes(df_trans: pd.DataFrame) -> pd.Series:
    """Gasto real por mes: neto de cargos/abonos, sin contar ahorro/inversion ni ingresos genuinos."""
    cat_mes = gasto_por_categoria_mes(df_trans)
    if cat_mes.empty:
        return pd.Series(dtype=float)
    cat_mes = cat_mes[~cat_mes["categoria"].apply(es_categoria_ahorro)]
    cat_mes = cat_mes[~cat_mes["categoria"].apply(es_categoria_ingreso)]
    return cat_mes.groupby("mes")["monto_cargo"].sum().sort_index()


def ahorro_por_mes(df_trans: pd.DataFrame) -> pd.Series:
    """Cuanto se destino a categorias de ahorro/inversion por mes."""
    cat_mes = gasto_por_categoria_mes(df_trans)
    if cat_mes.empty:
        return pd.Series(dtype=float)
    cat_mes = cat_mes[cat_mes["categoria"].apply(es_categoria_ahorro)]
    return cat_mes.groupby("mes")["monto_cargo"].sum().sort_index()


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
    """Gasto real (sin ahorro/inversion) por categoria del mes actual y del anterior, lado a lado."""
    cat_mes = gasto_por_categoria_mes(df_trans)
    if cat_mes.empty:
        return pd.DataFrame(columns=["mes", "categoria", "monto_cargo"])
    cat_mes = cat_mes[~cat_mes["categoria"].apply(es_categoria_ahorro)]
    cat_mes = cat_mes[~cat_mes["categoria"].apply(es_categoria_ingreso)]
    meses = sorted(cat_mes["mes"].unique())
    if len(meses) < 2:
        return pd.DataFrame(columns=["mes", "categoria", "monto_cargo"])
    mes_actual, mes_anterior = meses[-1], meses[-2]
    comp = cat_mes[cat_mes["mes"].isin([mes_anterior, mes_actual])].copy()
    comp["mes"] = comp["mes"].astype(str)
    return comp


def _categorias_sobre_promedio(df_trans: pd.DataFrame, umbral: float, min_meses_historia: int) -> pd.DataFrame:
    """Categorias donde el monto del mes actual supera `umbral` veces el promedio historico."""
    cat_mes = gasto_por_categoria_mes(df_trans)
    if cat_mes.empty:
        return pd.DataFrame()
    cat_mes = cat_mes[~cat_mes["categoria"].apply(es_categoria_ingreso)]

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
    combinado = combinado[~combinado["categoria"].apply(es_categoria_ahorro)]
    return combinado.to_dict("records")


def logros_ahorro(df_trans: pd.DataFrame, umbral: float = 1.3, min_meses_historia: int = 2) -> list[dict]:
    """Categorias de ahorro/inversion donde el mes actual supera el promedio historico: un buen dato, no una alerta."""
    combinado = _categorias_sobre_promedio(df_trans, umbral, min_meses_historia)
    if combinado.empty:
        return []
    combinado = combinado[combinado["categoria"].apply(es_categoria_ahorro)]
    return combinado.to_dict("records")


def resumen_50_30_20(df_trans: pd.DataFrame, categoria_bucket: dict[str, str]) -> dict | None:
    """Gasto neto del mes actual agrupado en necesidad/gusto/ahorro segun `categoria_bucket`
    (categoria -> balde, definido por el usuario en la pagina Categorias).

    Las categorias de ahorro/inversion se clasifican solas como "Ahorro" (via
    `es_categoria_ahorro`); cualquier otra categoria que no este en `categoria_bucket` -- ya sea
    porque el usuario todavia no la clasifico, o porque la transaccion no tiene categoria
    asignada -- cae en "Sin clasificar" en vez de forzarse a un balde, para no mostrar un
    grafico que parezca mas representativo de lo que realmente es.
    """
    cat_mes = gasto_por_categoria_mes(df_trans)
    if cat_mes.empty:
        return None
    cat_mes = cat_mes[~cat_mes["categoria"].apply(es_categoria_ingreso)]
    if cat_mes.empty:
        return None

    mes_actual = cat_mes["mes"].max()
    cat_actual = cat_mes[cat_mes["mes"] == mes_actual].copy()

    def _balde(categoria: str) -> str:
        if es_categoria_ahorro(categoria):
            return "Ahorro"
        return categoria_bucket.get(categoria, SIN_CLASIFICAR)

    cat_actual["balde"] = cat_actual["categoria"].apply(_balde)

    total = float(cat_actual["monto_cargo"].sum())
    por_balde = cat_actual.groupby("balde")["monto_cargo"].sum().to_dict()
    sin_clasificar = float(por_balde.get(SIN_CLASIFICAR, 0.0))
    categorias_sin_clasificar = sorted(
        cat_actual.loc[cat_actual["balde"] == SIN_CLASIFICAR, "categoria"].unique().tolist()
    )

    return {
        "mes": str(mes_actual),
        "total": total,
        "montos": {b: float(por_balde.get(b, 0.0)) for b in BUCKETS},
        "sin_clasificar": sin_clasificar,
        "categorias_sin_clasificar": categorias_sin_clasificar,
    }
