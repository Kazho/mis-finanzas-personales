import datetime
import sqlite3
import unittest

from src import db
from src.fuentes.archivo import lote_desde_resultado
from src.fuentes.conector import ConectorNoConfigurado, ConectorNoDisponible, sincronizar_y_guardar
from src.fuentes.contrato import (
    FUENTE_API,
    FUENTE_PDF,
    REEMPLAZA_HASTA_CORTE,
    REEMPLAZA_TODOS,
    CuentaFuente,
    LoteImportacion,
    MovimientoFuente,
    OrigenLote,
)
from src.ingesta import guardar_lote
from tests._bd import bd_en_memoria

D = datetime.date


def _mov(fecha=D(2026, 9, 1), desc="COMPRA", cargo=1000.0, abono=0.0, **kw):
    kw.setdefault("hash_dedupe", f"h-{fecha}-{desc}-{cargo}-{abono}")
    return MovimientoFuente(fecha=fecha, descripcion=desc, monto_cargo=cargo, monto_abono=abono, **kw)


def _lote(movs, *, origen=None, banco="Banco X", tipo="tarjeta", **kw):
    return LoteImportacion(
        origen=origen or OrigenLote(FUENTE_PDF, "doc.pdf"),
        cuenta=CuentaFuente(numero="TC-1", tipo=tipo, banco=banco),
        movimientos=movs, **kw,
    )


def _filas(conn, where="1=1"):
    return [dict(r) for r in conn.execute(f"SELECT * FROM transacciones WHERE {where} ORDER BY id").fetchall()]


class GuardarLoteTest(unittest.TestCase):
    def test_guarda_con_fuente_estado_y_uid_unico(self):
        with bd_en_memoria() as conn:
            r = guardar_lote(_lote([_mov(desc="A"), _mov(desc="B", cargo=500.0)]))
            self.assertEqual((r.nuevas, r.duplicadas, r.actualizadas), (2, 0, 0))
            filas = _filas(conn)
            self.assertEqual({f["fuente"] for f in filas}, {FUENTE_PDF})
            self.assertEqual({f["estado"] for f in filas}, {"facturado"})
            self.assertTrue(all(f["uid"] and len(f["uid"]) == 32 for f in filas))
            self.assertEqual(len({f["uid"] for f in filas}), 2)

    def test_cargar_dos_veces_no_duplica(self):
        with bd_en_memoria() as conn:
            lote = _lote([_mov(desc="A")])
            guardar_lote(lote)
            r = guardar_lote(lote)
            self.assertEqual((r.nuevas, r.duplicadas), (0, 1))
            self.assertEqual(len(_filas(conn)), 1)

    def test_categoria_elegida_se_guarda(self):
        with bd_en_memoria() as conn:
            guardar_lote(_lote([_mov(desc="A")]), categorias=["Comida"], manuales=[1])
            fila = _filas(conn)[0]
            self.assertEqual((fila["categoria"], fila["categoria_manual"]), ("Comida", 1))

    def test_lote_invalido_no_guarda_nada_ni_crea_cuenta(self):
        with bd_en_memoria() as conn:
            malo = _lote([_mov(desc="A"), _mov(desc="B", cargo=-5.0)])
            with self.assertRaises(ValueError) as e:
                guardar_lote(malo)
            self.assertIn("negativos", str(e.exception))
            self.assertEqual(_filas(conn), [])
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM cuentas").fetchone()[0], 0)

    def test_sin_banco_falla(self):
        with bd_en_memoria():
            with self.assertRaises(ValueError):
                guardar_lote(_lote([_mov()], banco=None))
            self.assertEqual(guardar_lote(_lote([_mov()], banco=None), banco="Elegido").nuevas, 1)

    def test_categorias_desalineadas_fallan(self):
        with bd_en_memoria():
            with self.assertRaises(ValueError):
                guardar_lote(_lote([_mov()]), categorias=["a", "b"])


class IdExternoTest(unittest.TestCase):
    def _api(self, estado, cargo=1000.0, desc="COMPRA"):
        return _lote([_mov(desc=desc, cargo=cargo, estado=estado, id_externo="tx-1", hash_dedupe=None)],
                     origen=OrigenLote(FUENTE_API, "conector"))

    def test_pendiente_que_pasa_a_contabilizado_se_actualiza_y_respeta_la_categoria(self):
        with bd_en_memoria() as conn:
            guardar_lote(self._api("por_facturar"), categorias=["Comida"], manuales=[1])
            conn.execute("UPDATE transacciones SET categoria = 'Mi categoria'")
            r = guardar_lote(self._api("facturado", cargo=1050.0))
            self.assertEqual((r.nuevas, r.actualizadas, r.duplicadas), (0, 1, 0))
            filas = _filas(conn)
            self.assertEqual(len(filas), 1)
            self.assertEqual((filas[0]["estado"], filas[0]["monto_cargo"], filas[0]["categoria"]), ("facturado", 1050.0, "Mi categoria"))
            self.assertEqual(filas[0]["fuente"], FUENTE_API)

    def test_mismo_id_sin_cambios_es_duplicado(self):
        with bd_en_memoria() as conn:
            guardar_lote(self._api("facturado"))
            r = guardar_lote(self._api("facturado"))
            self.assertEqual((r.nuevas, r.actualizadas, r.duplicadas), (0, 0, 1))
            self.assertEqual(len(_filas(conn)), 1)

    def test_id_externo_repetido_en_el_mismo_lote_se_rechaza(self):
        with bd_en_memoria():
            lote = _lote([_mov(id_externo="x", hash_dedupe=None), _mov(desc="Z", id_externo="x", hash_dedupe=None)])
            with self.assertRaises(ValueError):
                guardar_lote(lote)

    def test_sin_id_ni_hash_se_rechaza(self):
        with self.assertRaises(ValueError):
            _lote([_mov(hash_dedupe=None)]).validar()


class ProvisionalesTest(unittest.TestCase):
    def test_por_facturar_nuevo_reemplaza_todo_lo_provisional(self):
        with bd_en_memoria() as conn:
            guardar_lote(_lote([_mov(desc="VIEJO", estado="por_facturar")], reemplaza_provisionales=REEMPLAZA_TODOS))
            r = guardar_lote(_lote([_mov(desc="NUEVO", estado="por_facturar")], reemplaza_provisionales=REEMPLAZA_TODOS))
            self.assertEqual(r.reemplazadas, 1)
            self.assertEqual([f["descripcion"] for f in _filas(conn)], ["NUEVO"])

    def test_estado_de_cuenta_reemplaza_solo_lo_anterior_a_su_corte(self):
        with bd_en_memoria() as conn:
            guardar_lote(_lote([
                _mov(fecha=D(2026, 9, 20), desc="ANTES", estado="por_facturar"),
                _mov(fecha=D(2026, 10, 2), desc="DESPUES", estado="por_facturar"),
            ]))
            guardar_lote(_lote([_mov(fecha=D(2026, 9, 20), desc="ANTES")], periodo_hasta=D(2026, 9, 22),
                               reemplaza_provisionales=REEMPLAZA_HASTA_CORTE))
            por_facturar = [f["descripcion"] for f in _filas(conn, "estado = 'por_facturar'")]
            self.assertEqual(por_facturar, ["DESPUES"])
            self.assertEqual([f["descripcion"] for f in _filas(conn, "estado = 'facturado'")], ["ANTES"])

    def test_hasta_corte_sin_periodo_es_invalido(self):
        with self.assertRaises(ValueError):
            _lote([_mov()], reemplaza_provisionales=REEMPLAZA_HASTA_CORTE).validar()


class AdaptadorArchivoTest(unittest.TestCase):
    def _resultado(self, **extra):
        base = {
            "banco": None, "numero_cuenta": "TC-9", "cartola_numero": None, "periodo_desde": None,
            "periodo_hasta": D(2026, 9, 22), "saldo_inicial": None, "saldo_final": 100.0,
            "saldo_disponible_fecha": None, "saldo_disponible_hora": None, "cuadratura_ok": True,
            "tipo_cuenta": "tarjeta", "moneda": "USD", "sufijo_cuenta": " (USD)", "es_tarjeta_credito": True,
            "estado": "facturado", "etiqueta_saldo": "Monto facturado a pagar", "estado_tc": None,
            "transacciones": [{"fecha": D(2026, 9, 1), "descripcion": "  ", "sucursal": None, "monto_cargo": 5.0,
                               "monto_abono": 0.0, "saldo": None, "hash_dedupe": "h1"}],
        }
        return {**base, **extra}

    def test_traduce_tarjeta_facturada_en_excel(self):
        lote = lote_desde_resultado(self._resultado(), "mov.xls", banco="BCI")
        self.assertEqual(lote.origen.tipo, "archivo_xls")
        self.assertEqual(lote.cuenta.nombre(), "BCI - TC-9 (USD)")
        self.assertEqual(lote.cuenta.moneda, "USD")
        self.assertEqual(lote.reemplaza_provisionales, REEMPLAZA_HASTA_CORTE)
        self.assertEqual(lote.movimientos[0].descripcion, "(sin descripcion)")
        self.assertEqual(lote.movimientos[0].sucursal, "")
        lote.validar()

    def test_por_facturar_reemplaza_todo(self):
        lote = lote_desde_resultado(self._resultado(estado="por_facturar"), "x.pdf")
        self.assertEqual(lote.reemplaza_provisionales, REEMPLAZA_TODOS)
        self.assertEqual(lote.movimientos[0].estado, "por_facturar")
        self.assertEqual(lote.origen.tipo, FUENTE_PDF)

    def test_cartola_de_cuenta_no_reemplaza_nada_y_guarda_saldo(self):
        r = self._resultado(es_tarjeta_credito=False, tipo_cuenta="corriente", moneda="CLP", sufijo_cuenta="",
                            banco="Banco de Chile", saldo_disponible_fecha=D(2026, 9, 30), saldo_final=500.0)
        del r["estado"]
        lote = lote_desde_resultado(r, "cartola.pdf")
        self.assertIsNone(lote.reemplaza_provisionales)
        self.assertEqual(lote.saldo_snapshot.saldo, 500.0)
        self.assertEqual(lote.cuenta.banco, "Banco de Chile")


class ConectorTest(unittest.TestCase):
    def test_conector_no_configurado_falla_con_mensaje_claro(self):
        c = ConectorNoConfigurado()
        self.assertEqual(c.consentimientos(), [])
        with self.assertRaises(ConectorNoDisponible):
            c.sincronizar()
        with self.assertRaises(ConectorNoDisponible):
            c.revocar("x")

    def test_un_lote_malo_no_impide_guardar_los_buenos_pero_se_informa(self):
        class Falso:
            def sincronizar(self, desde=None):
                yield _lote([_mov(desc="BUENO", id_externo="a", hash_dedupe=None)], origen=OrigenLote(FUENTE_API, "c"))
                yield _lote([_mov(desc="MALO", cargo=-1.0)], origen=OrigenLote(FUENTE_API, "c"))

        with bd_en_memoria() as conn:
            with self.assertRaises(ValueError) as e:
                sincronizar_y_guardar(Falso())
            self.assertIn("1 lote(s) rechazado(s)", str(e.exception))
            self.assertEqual([f["descripcion"] for f in _filas(conn)], ["BUENO"])


class EsquemaTest(unittest.TestCase):
    def test_filas_antiguas_reciben_uid_unico_al_migrar(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(db.SCHEMA)  # esquema anterior: sin uid, fuente ni id_externo
        conn.execute("INSERT INTO cuentas (nombre) VALUES ('Vieja')")
        for i in range(3):
            conn.execute("INSERT INTO transacciones (cuenta_id, fecha, descripcion, hash_dedupe) VALUES (1, '2026-01-01', 'x', ?)", (f"h{i}",))
        db.aplicar_esquema(conn)
        uids = [r["uid"] for r in conn.execute("SELECT uid FROM transacciones")]
        self.assertTrue(all(uids))
        self.assertEqual(len(set(uids)), 3)
        self.assertEqual(conn.execute("SELECT fuente FROM transacciones LIMIT 1").fetchone()["fuente"], "archivo")
        self.assertTrue(conn.execute("SELECT uid FROM cuentas").fetchone()["uid"])

    def test_aplicar_esquema_es_idempotente_y_el_trigger_asigna_uid(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        db.aplicar_esquema(conn)
        db.aplicar_esquema(conn)
        conn.execute("INSERT INTO cuentas (nombre) VALUES ('N')")
        conn.execute("INSERT INTO transacciones (cuenta_id, fecha, descripcion, hash_dedupe) VALUES (1, '2026-01-01', 'x', 'h')")
        self.assertTrue(conn.execute("SELECT uid FROM transacciones").fetchone()["uid"])

    def test_id_externo_unico_por_cuenta_pero_repetible_entre_cuentas(self):
        conn = sqlite3.connect(":memory:")
        db.aplicar_esquema(conn)
        conn.execute("INSERT INTO cuentas (nombre) VALUES ('A'), ('B')")
        ins = "INSERT INTO transacciones (cuenta_id, fecha, descripcion, hash_dedupe, id_externo) VALUES (?, '2026-01-01', 'x', ?, 'ext')"
        conn.execute(ins, (1, "h1"))
        conn.execute(ins, (2, "h2"))
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(ins, (1, "h3"))


if __name__ == "__main__":
    unittest.main()
