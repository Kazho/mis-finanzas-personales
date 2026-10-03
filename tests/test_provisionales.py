import sqlite3
import unittest
from contextlib import contextmanager
from unittest import mock

from src import db


def _base_en_memoria():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(db.SCHEMA)
    for tabla, columna, alter in db.MIGRACIONES:
        if columna not in {r["name"] for r in conn.execute(f"PRAGMA table_info({tabla})").fetchall()}:
            conn.execute(alter)
    return conn


class ProvisionalesTest(unittest.TestCase):
    def setUp(self):
        self.conn = _base_en_memoria()

        @contextmanager
        def _get_conn():
            yield self.conn

        patcher = mock.patch.object(db, "get_conn", _get_conn)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cuenta = db.get_or_create_cuenta("Banco - TC-1", banco="Banco", numero_cuenta="TC-1", tipo="tarjeta")
        self._n = 0
        for fecha, estado in (("2026-09-10", "facturado"), ("2026-09-24", "por_facturar"), ("2026-10-02", "por_facturar")):
            self._insertar(self.cuenta, fecha, estado)
        self.otra = db.get_or_create_cuenta("Banco - TC-2", banco="Banco", numero_cuenta="TC-2", tipo="tarjeta")
        self._insertar(self.otra, "2026-09-24", "por_facturar")

    def _insertar(self, cuenta, fecha, estado):
        self._n += 1
        self.conn.execute(
            "INSERT INTO transacciones (cuenta_id, fecha, descripcion, monto_cargo, monto_abono, hash_dedupe, estado) "
            "VALUES (?, ?, 'X', 100, 0, ?, ?)",
            (cuenta, fecha, f"h{self._n}", estado),
        )

    def _fechas(self, cuenta, estado):
        rows = self.conn.execute(
            "SELECT fecha FROM transacciones WHERE cuenta_id = ? AND estado = ? ORDER BY fecha", (cuenta, estado)
        ).fetchall()
        return [r["fecha"] for r in rows]

    def test_estado_facturado_reemplaza_solo_lo_anterior_a_su_corte(self):
        borradas = db.reemplazar_provisionales(self.cuenta, "2026-09-30")
        self.assertEqual(borradas, 1)
        self.assertEqual(self._fechas(self.cuenta, "por_facturar"), ["2026-10-02"])

    def test_consulta_nueva_por_facturar_reemplaza_todo_lo_provisional_de_esa_cuenta(self):
        self.assertEqual(db.reemplazar_provisionales(self.cuenta), 2)
        self.assertEqual(self._fechas(self.cuenta, "por_facturar"), [])
        self.assertEqual(self._fechas(self.cuenta, "facturado"), ["2026-09-10"])

    def test_no_toca_otras_cuentas(self):
        db.reemplazar_provisionales(self.cuenta)
        self.assertEqual(self._fechas(self.otra, "por_facturar"), ["2026-09-24"])

    def test_banco_se_recuerda_por_numero_de_tarjeta(self):
        self.assertEqual(db.buscar_banco_por_numero("TC-1"), "Banco")
        self.assertIsNone(db.buscar_banco_por_numero("TC-999"))

    def test_estado_tc_no_pisa_datos_con_vacios(self):
        import datetime
        db.guardar_estado_tc(self.cuenta, {"periodo_hasta": datetime.date(2026, 10, 3), "cupo_total": 1000.0, "cupo_utilizado": 50.0, "cupo_disponible": 950.0})
        db.guardar_estado_tc(self.cuenta, {"periodo_hasta": datetime.date(2026, 10, 3), "monto_facturado": 70.0})
        fila = self.conn.execute("SELECT * FROM tc_estados WHERE cuenta_id = ?", (self.cuenta,)).fetchone()
        self.assertEqual((fila["cupo_total"], fila["monto_facturado"]), (1000.0, 70.0))


if __name__ == "__main__":
    unittest.main()
