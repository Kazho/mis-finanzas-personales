import datetime
import unittest

from src.cuentas import _resumen_tarjeta
from src.parser_tarjeta_movimientos import _es_pago, _glosa, _monto_pdf, _parse_filas_facturado


def _filas_nacional():
    """Misma estructura que el Excel de movimientos facturados en pesos, con datos inventados."""
    return [
        [""] * 10,
        ["", "Tipo de Tarjeta:", "Titular Visa Infinite  ****1234"] + [""] * 7,
        ["", "Movimientos Facturados"] + [""] * 8,
        ["", "Monto Facturado", "", "Pago Mínimo", "", "Fecha  de Facturación", "", "", "", "Pagar Hasta"],
        ["", 100000.0, "", 5000.0, "", "22/09/2026", "", "", "", "06/10/2026"],
        ["", "Movimientos Nacionales"] + [""] * 8,
        ["", "Categoría", "Fecha", "Descripción", "", "", "Cuotas", "Monto ($)", "", ""],
        ["", "Total de Pagos, Compras, Cuotas y Avance", "10/09/2026", "COMERCIO UNO", "", "", "01/01", 30000.0, "", ""],
        ["", "Total de Pagos, Compras, Cuotas y Avance", "28/08/2026", "MONTO CANCELADO", "", "", "01/01", 80000.0, "", ""],
        ["", "Total de Pagos, Compras, Cuotas y Avance", "19/08/2026", "TIENDA DOS TASA INT. 0,00%", "", "", "02/03", 70000.0, "", ""],
    ]


def _filas_usd():
    return [
        ["", "Tipo de Tarjeta:", "Titular Visa Infinite  ****1234"] + [""] * 6,
        ["", "Deuda Total en Dólar", "", "Traspaso de Deuda Nacional", "", "Fecha de Facturación", "", "Pagar Hasta", ""],
        ["", 25.63, "", 0.0, "", "22/09/2026", "", "06/10/2026", ""],
        ["", "Categoría", "", "Fecha", "Descripción", "", "País", "Monto Moneda Origen", "Monto (USD)"],
        ["", "Total Pagos", "", "28/08/2026", "Pago Dolar TEF", "", "CHILE", -1.07, -1.07],
        ["", "Total  Compras", "", "03/09/2026", "SERVICIO UNO", "", "ESTADOS UNIDOS", 990.0, 1.06],
        ["", "Total  Compras", "", "24/08/2026", "SERVICIO DOS", "", "ESTADOS UNIDOS", 22547.0, 24.57],
    ]


class FacturadoXlsTest(unittest.TestCase):
    def test_pesos_cuadra_y_separa_pago_y_cuota(self):
        r = _parse_filas_facturado(_filas_nacional())
        self.assertEqual(r["numero_cuenta"], "TC-1234")
        self.assertEqual(r["moneda"], "CLP")
        self.assertEqual(r["estado"], "facturado")
        self.assertTrue(r["cuadratura_ok"])
        self.assertEqual(r["periodo_hasta"], datetime.date(2026, 9, 22))
        self.assertEqual(r["estado_tc"]["pago_minimo"], 5000.0)
        self.assertEqual(r["estado_tc"]["fecha_vencimiento"], datetime.date(2026, 10, 6))
        por_desc = {t["descripcion"]: t for t in r["transacciones"]}
        pago = por_desc["PAGO TARJETA DE CREDITO (MONTO CANCELADO)"]
        self.assertEqual((pago["monto_cargo"], pago["monto_abono"]), (0.0, 80000.0))
        cuota = por_desc["TIENDA DOS TASA INT. 0,00% (cuota 02/03)"]
        self.assertEqual(cuota["monto_cargo"], 70000.0)
        # una cuota 2/3 se cobra en el corte, no en la fecha de la compra original
        self.assertEqual(cuota["fecha"], datetime.date(2026, 9, 22))
        self.assertEqual(por_desc["COMERCIO UNO"]["fecha"], datetime.date(2026, 9, 10))

    def test_dolares_usa_monto_usd_y_pais(self):
        r = _parse_filas_facturado(_filas_usd())
        self.assertEqual(r["moneda"], "USD")
        self.assertEqual(r["sufijo_cuenta"], " (USD)")
        self.assertTrue(r["cuadratura_ok"])
        self.assertEqual(r["saldo_final"], 25.63)
        compra = next(t for t in r["transacciones"] if t["descripcion"] == "SERVICIO UNO")
        self.assertEqual(compra["monto_cargo"], 1.06)
        self.assertEqual(compra["sucursal"], "ESTADOS UNIDOS")
        pago = next(t for t in r["transacciones"] if t["descripcion"].startswith("PAGO TARJETA"))
        self.assertEqual(pago["monto_abono"], 1.07)

    def test_cuadratura_falla_si_el_total_no_calza(self):
        filas = _filas_nacional()
        filas[4][1] = 99999.0
        self.assertFalse(_parse_filas_facturado(filas)["cuadratura_ok"])

    def test_hashes_distintos_entre_pesos_y_dolares(self):
        pesos = _parse_filas_facturado(_filas_nacional())
        usd = _parse_filas_facturado(_filas_usd())
        self.assertTrue({t["hash_dedupe"] for t in pesos["transacciones"]}.isdisjoint({t["hash_dedupe"] for t in usd["transacciones"]}))

    def test_sin_tabla_de_movimientos_falla_con_mensaje(self):
        with self.assertRaises(ValueError):
            _parse_filas_facturado(_filas_nacional()[:5])


class AyudasTest(unittest.TestCase):
    def test_monto_pdf_pesos_y_dolares(self):
        self.assertEqual(_monto_pdf("5,932,006", "CLP"), 5932006)
        self.assertEqual(_monto_pdf("-156,913", "CLP"), -156913)
        self.assertEqual(_monto_pdf("990", "CLP"), 990)
        self.assertEqual(_monto_pdf("978,27", "USD"), 978.27)
        self.assertEqual(_monto_pdf("1.000,00", "USD"), 1000.0)
        self.assertEqual(_monto_pdf("-25,63", "USD"), -25.63)

    def test_es_pago(self):
        self.assertTrue(_es_pago("MONTO CANCELADO", 100))
        self.assertTrue(_es_pago("PAGO PESOS TEF PAGO NORMAL", 100))
        self.assertTrue(_es_pago("Pago Dolar TEF", 1.0))
        self.assertTrue(_es_pago("CUALQUIER COSA", -5))
        self.assertFalse(_es_pago("PAGO FACIL SPA", 500))

    def test_glosa_de_cuota_solo_si_hay_mas_de_una(self):
        self.assertEqual(_glosa("COMERCIO", False, "01/01"), "COMERCIO")
        self.assertEqual(_glosa("COMERCIO", False, "02/03"), "COMERCIO (cuota 02/03)")
        self.assertEqual(_glosa("MONTO CANCELADO", True, None), "PAGO TARJETA DE CREDITO (MONTO CANCELADO)")


class ResumenTarjetaTest(unittest.TestCase):
    def _estado(self, hasta, **campos):
        base = {k: None for k in ("monto_facturado", "pago_minimo", "fecha_vencimiento", "cupo_total", "cupo_utilizado", "cupo_disponible")}
        return {**base, "periodo_hasta": hasta, **campos}

    def test_une_datos_de_documentos_distintos(self):
        estados = [
            self._estado("2026-10-03", cupo_total=6_000_000, cupo_utilizado=67_994, cupo_disponible=5_932_006),
            self._estado("2026-09-22", monto_facturado=156_913, pago_minimo=7_846, fecha_vencimiento="2026-10-06"),
        ]
        tc = _resumen_tarjeta(estados, {"n": 2, "compras": 990.0, "pagos": 156_913.0})
        self.assertEqual(tc["periodo_hasta"], "2026-10-03")
        self.assertEqual(tc["cupo_total"], 6_000_000)
        self.assertEqual(tc["monto_facturado"], 156_913)
        self.assertEqual(tc["fecha_vencimiento"], "2026-10-06")
        self.assertEqual(tc["facturado_pendiente"], 0.0)   # el pago posterior al corte lo cubre
        self.assertEqual(tc["por_facturar"], 990.0)

    def test_pago_parcial_deja_saldo_pendiente(self):
        tc = _resumen_tarjeta([self._estado("2026-09-22", monto_facturado=100_000)], {"n": 1, "compras": 0.0, "pagos": 30_000.0})
        self.assertEqual(tc["facturado_pendiente"], 70_000)

    def test_sobrepago_no_da_pendiente_negativo(self):
        tc = _resumen_tarjeta([self._estado("2026-09-22", monto_facturado=100)], {"n": 1, "compras": 0.0, "pagos": 150.0})
        self.assertEqual(tc["facturado_pendiente"], 0.0)

    def test_sin_estados_o_sin_monto_facturado(self):
        self.assertIsNone(_resumen_tarjeta([], {"n": 0, "compras": 0, "pagos": 0}))
        tc = _resumen_tarjeta([self._estado("2026-10-03", cupo_total=1000.0)], {"n": 0, "compras": 0, "pagos": 0})
        self.assertIsNone(tc["facturado_pendiente"])


if __name__ == "__main__":
    unittest.main()
