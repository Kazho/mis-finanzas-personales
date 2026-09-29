import unittest

from src.cuentas import deuda_tarjeta, nombre_visible, resumen_panorama


def _c(id_, banco, tipo, saldo=None, moneda="CLP", archivada=0, tc=None, alias=None):
    return {"id": id_, "nombre": f"{banco} - {id_}", "alias": alias, "banco": banco, "tipo": tipo, "moneda": moneda,
            "archivada": archivada, "saldo": saldo, "tc": tc}


class ResumenPanoramaTest(unittest.TestCase):
    def test_separa_disponible_inversion_y_deuda(self):
        cuentas = [
            _c(1, "Banco A", "corriente", 1_000_000),
            _c(2, "Banco A", "tarjeta", tc={"cupo_utilizado": 400_000, "monto_facturado": 100_000}),
            _c(3, "Banco B", "vista", 200_000),
            _c(4, "Banco B", "inversion", 5_000_000),
        ]
        r = resumen_panorama(cuentas, None)
        self.assertEqual(r["disponible_clp"], 1_200_000)
        self.assertEqual(r["inversion_clp"], 5_000_000)
        self.assertEqual(r["deuda_clp"], 400_000)
        self.assertEqual(r["neto_clp"], 5_800_000)
        self.assertEqual(r["por_banco"]["Banco A"]["deuda_clp"], 400_000)

    def test_usd_se_convierte_con_dolar_y_avisa_sin_dolar(self):
        cuentas = [_c(1, "Banco A", "corriente", 1_000, moneda="USD"), _c(2, "Banco A", "corriente", 500_000)]
        con = resumen_panorama(cuentas, 900.0)
        self.assertEqual(con["disponible"]["USD"], 1_000)
        self.assertEqual(con["disponible_clp"], 500_000 + 900_000)
        self.assertFalse(con["usd_sin_convertir"])
        sin = resumen_panorama(cuentas, None)
        self.assertEqual(sin["disponible_clp"], 500_000)
        self.assertTrue(sin["usd_sin_convertir"])

    def test_archivadas_y_sin_datos_no_suman(self):
        cuentas = [_c(1, "A", "corriente", 100, archivada=1), _c(2, "A", "corriente", None)]
        r = resumen_panorama(cuentas, None)
        self.assertEqual(r["disponible_clp"], 0)
        self.assertEqual([c["id"] for c in r["sin_datos"]], [2])

    def test_deuda_tarjeta_prefiere_cupo_utilizado(self):
        self.assertEqual(deuda_tarjeta({"tc": {"cupo_utilizado": 10, "monto_facturado": 5}}), 10)
        self.assertEqual(deuda_tarjeta({"tc": {"cupo_utilizado": None, "monto_facturado": 5}}), 5)
        self.assertIsNone(deuda_tarjeta({"tc": None}))

    def test_nombre_visible_usa_alias(self):
        self.assertEqual(nombre_visible({"nombre": "X", "alias": " Mi cuenta "}), "Mi cuenta")
        self.assertEqual(nombre_visible({"nombre": "X", "alias": None}), "X")


if __name__ == "__main__":
    unittest.main()
