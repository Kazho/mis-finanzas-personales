import unittest

import pandas as pd

from src.analisis_gastos import es_categoria_ingreso
from src.conciliacion import CATEGORIA_TRASPASO, conciliar_traspasos


def _df(filas):
    cols = ["id", "fecha", "descripcion", "monto_cargo", "monto_abono", "categoria", "cuenta", "tipo", "moneda"]
    df = pd.DataFrame(filas, columns=cols)
    df["fecha"] = pd.to_datetime(df["fecha"])
    return df


def _cat(df, id_):
    return df.loc[df["id"] == id_, "categoria"].iloc[0]


class ConciliarTraspasosTest(unittest.TestCase):
    def test_pago_de_tarjeta_concilia_ambos_lados(self):
        df = _df([
            (1, "2026-08-31", "PAGO TARJETA DE CREDITO (MONTO CANCELADO)", 0, 540351, "Pago tarjeta de credito", "TC", "tarjeta", "CLP"),
            (2, "2026-09-01", "PAGO TC 0425", 540351, 0, "Pago tarjeta de credito", "CC", "corriente", "CLP"),
            (3, "2026-09-02", "SUPERMERCADO", 12000, 0, "Comida y almacen", "CC", "corriente", "CLP"),
        ])
        r = conciliar_traspasos(df)
        self.assertEqual(_cat(r, 1), CATEGORIA_TRASPASO)
        self.assertEqual(_cat(r, 2), CATEGORIA_TRASPASO)
        self.assertEqual(_cat(r, 3), "Comida y almacen")
        self.assertEqual(r.attrs["n_conciliados"], 1)

    def test_pago_sin_tarjeta_cargada_sigue_siendo_gasto(self):
        df = _df([(1, "2026-09-01", "PAGO TARJETA DE CREDITO", 300000, 0, "Pago tarjeta de credito", "CC", "corriente", "CLP")])
        self.assertEqual(_cat(conciliar_traspasos(df), 1), "Pago tarjeta de credito")

    def test_fuera_de_ventana_no_concilia(self):
        df = _df([
            (1, "2026-08-01", "PAGO TARJETA DE CREDITO (MONTO CANCELADO)", 0, 100000, "x", "TC", "tarjeta", "CLP"),
            (2, "2026-08-20", "PAGO TC", 100000, 0, "x", "CC", "corriente", "CLP"),
        ])
        self.assertEqual(conciliar_traspasos(df).attrs["n_conciliados"], 0)

    def test_moneda_distinta_no_concilia(self):
        df = _df([
            (1, "2026-08-31", "PAGO TARJETA DE CREDITO (MONTO CANCELADO)", 0, 500, "x", "TC USD", "tarjeta", "USD"),
            (2, "2026-08-31", "PAGO TC", 500, 0, "x", "CC", "corriente", "CLP"),
        ])
        self.assertEqual(conciliar_traspasos(df).attrs["n_conciliados"], 0)

    def test_traspaso_entre_cuentas_propias(self):
        df = _df([
            (1, "2026-09-05", "TRASPASO A:MI CUENTA", 200000, 0, "Transferencia enviada", "CC", "corriente", "CLP"),
            (2, "2026-09-05", "TRASPASO DE:MI CUENTA", 0, 200000, "Transferencia recibida", "Vista", "vista", "CLP"),
        ])
        r = conciliar_traspasos(df)
        self.assertEqual({_cat(r, 1), _cat(r, 2)}, {CATEGORIA_TRASPASO})

    def test_traspaso_misma_cuenta_o_sin_glosa_no_concilia(self):
        df = _df([
            (1, "2026-09-05", "TRASPASO A:X", 200000, 0, "a", "CC", "corriente", "CLP"),
            (2, "2026-09-05", "TRASPASO DE:X", 0, 200000, "b", "CC", "corriente", "CLP"),
            (3, "2026-09-05", "COMPRA", 50000, 0, "c", "CC", "corriente", "CLP"),
            (4, "2026-09-05", "DEPOSITO", 0, 50000, "d", "Vista", "vista", "CLP"),
        ])
        self.assertEqual(conciliar_traspasos(df).attrs["n_conciliados"], 0)

    def test_respeta_categoria_manual_y_un_abono_solo_concilia_un_cargo(self):
        df = _df([
            (1, "2026-09-05", "TRASPASO A:X", 1000, 0, "a", "CC", "corriente", "CLP"),
            (2, "2026-09-05", "TRASPASO A:Y", 1000, 0, "a", "CC", "corriente", "CLP"),
            (3, "2026-09-05", "TRASPASO DE:Z", 0, 1000, "b", "Vista", "vista", "CLP"),
        ])
        self.assertEqual(conciliar_traspasos(df).attrs["n_conciliados"], 1)
        df["categoria_manual"] = [1, 1, 0]
        self.assertEqual(conciliar_traspasos(df).attrs["n_conciliados"], 0)

    def test_dataframe_vacio(self):
        self.assertTrue(conciliar_traspasos(_df([])).empty)

    def test_traspaso_propio_no_es_gasto_ni_ingreso(self):
        self.assertTrue(es_categoria_ingreso(CATEGORIA_TRASPASO))


if __name__ == "__main__":
    unittest.main()
