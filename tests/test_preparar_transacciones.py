import unittest

import pandas as pd

from src.conciliacion import CATEGORIA_TRASPASO
from src.cuentas import preparar_transacciones

COLS = ["id", "fecha", "descripcion", "monto_cargo", "monto_abono", "saldo", "categoria", "cuenta", "tipo", "moneda", "archivada"]


def _df(filas):
    df = pd.DataFrame(filas, columns=COLS)
    df["fecha"] = pd.to_datetime(df["fecha"])
    return df


class PrepararTransaccionesTest(unittest.TestCase):
    def setUp(self):
        self.df = _df([
            (1, "2026-09-01", "SUPER", 10_000, 0, 500_000.0, "Comida", "CC", "corriente", "CLP", 0),
            (2, "2026-09-02", "COMPRA TC", 20_000, 0, None, "Retail", "TC", "tarjeta", "CLP", 0),
            (3, "2026-09-03", "AMAZON", 10.0, 0, 90.0, "Retail", "USD", "corriente", "USD", 0),
            (4, "2026-09-04", "VIEJA", 5_000, 0, 1.0, "Otros", "Vieja", "corriente", "CLP", 1),
        ])

    def test_convierte_usd_y_anula_saldos_inutiles(self):
        r = preparar_transacciones(self.df, 900.0)
        self.assertEqual(r.loc[r["id"] == 3, "monto_cargo"].iloc[0], 9_000)
        self.assertEqual(r["saldo"].notna().sum(), 1)
        self.assertEqual(r.loc[r["id"] == 1, "saldo"].iloc[0], 500_000)
        self.assertEqual(r.attrs["n_usd_convertidos"], 1)
        self.assertEqual(r.attrs["n_usd_omitidos"], 0)

    def test_sin_dolar_deja_fuera_los_usd(self):
        r = preparar_transacciones(self.df, None)
        self.assertNotIn(3, set(r["id"]))
        self.assertEqual(r.attrs["n_usd_omitidos"], 1)

    def test_pago_tc_conciliado_no_cuenta_como_gasto(self):
        df = _df([
            (1, "2026-08-31", "PAGO TARJETA DE CREDITO (MONTO CANCELADO)", 0, 100_000, None, "Pago tarjeta de credito", "TC", "tarjeta", "CLP", 0),
            (2, "2026-08-31", "PAGO TC", 100_000, 0, 1.0, "Pago tarjeta de credito", "CC", "corriente", "CLP", 0),
        ])
        r = preparar_transacciones(df, None)
        self.assertEqual(set(r["categoria"]), {CATEGORIA_TRASPASO})
        self.assertEqual(r.attrs["n_conciliados"], 1)

    def test_vacio(self):
        self.assertTrue(preparar_transacciones(_df([]), 900.0).empty)


if __name__ == "__main__":
    unittest.main()
