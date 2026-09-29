"""Conciliacion de movimientos entre TUS propias cuentas, para que no se cuenten dos veces como gasto o ingreso.

Al juntar varios bancos en una sola plataforma aparecen dos casos que, sin conciliar, inflan gastos e ingresos:

  * Pago de tarjeta de credito: sale plata de tu cuenta corriente (cargo "PAGO TARJETA...") y entra a la
    tarjeta (abono "PAGO TARJETA DE CREDITO"). El gasto real ya esta en las compras de la tarjeta.
  * Traspaso entre tus cuentas: cargo en una cuenta y abono del mismo monto en otra, con pocos dias de
    diferencia.

Un par se concilia solo si ambos lados existen (asi, un pago de tarjeta cuya tarjeta no has cargado sigue
contando como gasto, que es lo correcto: esa es la unica huella de ese consumo) y solo entre movimientos
de la MISMA moneda. Los pares conciliados quedan en la categoria neutra `CATEGORIA_TRASPASO`, que el
analisis excluye de gastos e ingresos. No se toca la base de datos: se recalcula al cargar los datos, asi
que cargar la cartola que faltaba concilia sola lo que antes quedaba suelto.
"""
import pandas as pd

CATEGORIA_TRASPASO = "Traspaso propio"

VENTANA_PAGO_TC_DIAS = 7
VENTANA_TRASPASO_DIAS = 3

_PALABRAS_TRASPASO = ("TRASPASO", "TRANSFERENCIA", "TRANSF")
_PREFIJO_PAGO_TC = "PAGO TARJETA DE CREDITO"


def _mejor_par(fecha_a, monto_a, candidatos: pd.DataFrame, columna_monto: str, ventana_dias: int, usados: set):
    """Id del candidato del mismo monto (a $1) y fecha mas cercana dentro de la ventana, o None."""
    if candidatos.empty:
        return None
    dif_monto = (candidatos[columna_monto] - monto_a).abs()
    dif_dias = (candidatos["fecha"] - fecha_a).abs().dt.days
    ok = (dif_monto < 1) & (dif_dias <= ventana_dias) & ~candidatos["id"].isin(usados)
    if not ok.any():
        return None
    return candidatos.loc[ok].assign(_d=dif_dias[ok]).sort_values(["_d", "id"]).iloc[0]["id"]


def conciliar_traspasos(df: pd.DataFrame) -> pd.DataFrame:
    """Devuelve una copia de `df` con categoria = CATEGORIA_TRASPASO en los movimientos conciliados.

    Espera las columnas id, fecha (datetime), descripcion, monto_cargo, monto_abono, categoria, cuenta, tipo y
    moneda. Los movimientos cuya categoria fue elegida a mano (`categoria_manual` == 1, si la columna existe)
    no se tocan: si el usuario los clasifico, se respeta. `.attrs["n_conciliados"]` trae la cantidad de pares."""
    df = df.copy()
    df.attrs["n_conciliados"] = 0
    if df.empty or "tipo" not in df.columns:
        return df

    libre = pd.Series(True, index=df.index)
    if "categoria_manual" in df.columns:
        libre = df["categoria_manual"].fillna(0).astype(int) == 0
    df["_libre"] = libre
    desc = df["descripcion"].fillna("").str.upper()
    df["_desc"] = desc

    usados: set = set()
    pares: list[tuple] = []

    def _buscar(origen: pd.DataFrame, destino: pd.DataFrame, col_origen: str, col_destino: str, ventana: int, misma_cuenta_ok: bool):
        for _, fila in origen.sort_values(["fecha", "id"]).iterrows():
            if fila["id"] in usados:
                continue
            cand = destino[destino["moneda"] == fila["moneda"]]
            if not misma_cuenta_ok:
                cand = cand[cand["cuenta"] != fila["cuenta"]]
            par = _mejor_par(fila["fecha"], fila[col_origen], cand, col_destino, ventana, usados)
            if par is not None:
                usados.update((fila["id"], par))
                pares.append((fila["id"], par))

    sin_tc = df["tipo"] != "tarjeta"
    # 1) pago de tarjeta: abono "PAGO TARJETA DE CREDITO" en la tarjeta <-> cargo del mismo monto en otra cuenta
    pagos_tc = df[(df["tipo"] == "tarjeta") & (df["monto_abono"] > 0) & df["_desc"].str.startswith(_PREFIJO_PAGO_TC) & df["_libre"]]
    cargos_cuenta = df[sin_tc & (df["monto_cargo"] > 0) & df["_libre"]]
    _buscar(pagos_tc, cargos_cuenta, "monto_abono", "monto_cargo", VENTANA_PAGO_TC_DIAS, misma_cuenta_ok=True)

    # 2) traspaso entre cuentas propias: ambos lados con glosa de transferencia, en cuentas distintas
    es_transf = df["_desc"].apply(lambda d: any(p in d for p in _PALABRAS_TRASPASO))
    cargos_transf = df[sin_tc & (df["monto_cargo"] > 0) & es_transf & df["_libre"]]
    abonos_transf = df[sin_tc & (df["monto_abono"] > 0) & es_transf & df["_libre"]]
    _buscar(cargos_transf, abonos_transf, "monto_cargo", "monto_abono", VENTANA_TRASPASO_DIAS, misma_cuenta_ok=False)

    ids = {i for par in pares for i in par}
    df.loc[df["id"].isin(ids), "categoria"] = CATEGORIA_TRASPASO
    df.attrs["n_conciliados"] = len(pares)
    return df.drop(columns=["_libre", "_desc"])
