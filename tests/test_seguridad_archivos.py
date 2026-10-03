"""Pruebas de seguridad de la carga de archivos: formatos falsos, bombas de descompresion, archivos danados, tiempo limite,
y datos absurdos que intenten colarse a la base. Los archivos de prueba se fabrican aca, sin datos personales."""
import datetime
import io
import random
import sys
import time
import unittest
import zlib
from unittest import mock

from src import lectura_aislada
from src.fuentes.archivo import lote_desde_resultado
from src.fuentes.contrato import (
    FUENTE_PDF,
    CuentaFuente,
    LoteImportacion,
    MovimientoFuente,
    OrigenLote,
)
from src.lectura_aislada import LecturaFallida, codificar, decodificar, ejecutar_hijo, leer_documento_aislado
from src.lectura_documentos import FormatoNoReconocido
from src.parser_tarjeta_movimientos import _validar_dimensiones, parse_tarjeta_facturado_xls
from src.seguridad_archivos import (
    MAGIC_OLE2,
    MAX_BYTES,
    ArchivoNoPermitido,
    inspeccionar_pdf,
    nombre_seguro,
    tipo_por_contenido,
    validar_archivo,
)


# ------------------------------------------------------------------------------------------------------------
# Fabrica de PDF a mano
# ------------------------------------------------------------------------------------------------------------

def _pdf(flujo: bytes, comprimir: bool = False) -> bytes:
    """PDF de una pagina con `flujo` como contenido."""
    cuerpo = zlib.compress(flujo, 9) if comprimir else flujo
    filtro = b" /Filter /FlateDecode" if comprimir else b""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d%s >>\nstream\n" % (len(cuerpo), filtro) + cuerpo + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offs = []
    for i, o in enumerate(objs, start=1):
        offs.append(out.tell())
        out.write(b"%d 0 obj\n" % i + o + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for off in offs:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref))
    return out.getvalue()


def _pdf_con_texto(items: list[tuple[float, float, str]]) -> bytes:
    """items: (x, distancia desde arriba, texto). Cada texto se coloca en su posicion exacta, como una tabla."""
    partes = []
    for x, arriba, texto in items:
        t = texto.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        partes.append(f"BT /F1 9 Tf {x} {792 - arriba} Td ({t}) Tj ET")
    return _pdf("\n".join(partes).encode("latin-1"))


def _pdf_bomba(mb: float) -> bytes:
    unidad = b"BT /F1 12 Tf 100 700 Td (hola) Tj ET\n"
    return _pdf(unidad * (int(mb * 1024 * 1024) // len(unidad)), comprimir=True)


def _pdf_por_facturar_sintetico() -> bytes:
    """Imita el PDF 'Saldo y Movimientos No Facturados' (pesos), con datos inventados."""
    return _pdf_con_texto([
        (34, 82, "Sr(a).:"), (171, 82, "Cliente de Prueba"),
        (34, 106, "Tipo de Tarjeta:"), (171, 106, "Titular Visa Infinite ********1234"),
        (34, 180, "Saldo y Movimientos No Facturados al 03/10/2026"),
        (89, 210, "Cupo Disponible"), (276, 210, "Cupo Utilizado"), (466, 210, "Cupo Total"),
        (105, 224, "5,932,006"), (294, 224, "67,994"), (470, 224, "6,000,000"),
        (34, 270, "Movimientos Nacionales"),
        (40, 288, "Fecha"), (92, 288, "Tipo de Tarjeta"), (204, 288, "Descripcion"), (342, 288, "Ciudad"),
        (413, 288, "Cuotas"), (475, 288, "Montos ($)"),
        (37, 308, "02/10/2026"), (89, 308, "Titular********1234"), (201, 308, "COMERCIO PRUEBA"), (429, 308, "01/01"), (565, 308, "990"),
        (37, 328, "01/10/2026"), (89, 328, "Titular********1234"), (201, 328, "PAGO PESOS TEF PAGO NORMAL"), (429, 328, "01/01"), (548, 328, "-156,913"),
    ])


# ------------------------------------------------------------------------------------------------------------
# Capa 1: tipo, tamaño y nombre
# ------------------------------------------------------------------------------------------------------------

class ValidarArchivoTest(unittest.TestCase):
    def test_acepta_pdf_y_xls_reales_por_firma(self):
        self.assertEqual(validar_archivo("a.pdf", b"%PDF-1.4 resto"), "pdf")
        self.assertEqual(validar_archivo("A.XLS", MAGIC_OLE2 + b"resto"), "xls")

    def test_rechaza_ejecutable_disfrazado(self):
        with self.assertRaises(ArchivoNoPermitido):
            validar_archivo("cartola.pdf", b"MZ\x90\x00 programa de windows")

    def test_rechaza_contenido_que_no_coincide_con_la_extension(self):
        with self.assertRaises(ArchivoNoPermitido):
            validar_archivo("cartola.xls", b"%PDF-1.4 esto es un pdf")
        with self.assertRaises(ArchivoNoPermitido):
            validar_archivo("cartola.pdf", MAGIC_OLE2 + b"x")

    def test_rechaza_extensiones_no_permitidas_y_sin_extension(self):
        for nombre in ("virus.exe", "macro.xlsm", "datos.zip", "sin_extension", "doble.pdf.exe"):
            with self.subTest(nombre=nombre):
                with self.assertRaises(ArchivoNoPermitido):
                    validar_archivo(nombre, b"%PDF-1.4")

    def test_rechaza_vacio_y_demasiado_grande(self):
        with self.assertRaises(ArchivoNoPermitido):
            validar_archivo("a.pdf", b"")
        with self.assertRaises(ArchivoNoPermitido):
            validar_archivo("a.pdf", b"%PDF-" + b"0" * MAX_BYTES)

    def test_respeta_la_lista_de_permitidos(self):
        with self.assertRaises(ArchivoNoPermitido):
            validar_archivo("a.xls", MAGIC_OLE2, permitidos=("pdf",))

    def test_tipo_por_contenido(self):
        self.assertIsNone(tipo_por_contenido(b"PK\x03\x04 un zip"))
        self.assertEqual(tipo_por_contenido(b"basura\n%PDF-1.7"), "pdf")

    def test_nombre_seguro_quita_rutas_y_caracteres_de_control(self):
        self.assertEqual(nombre_seguro("..\\..\\windows\\system32\\a.pdf"), "a.pdf")
        self.assertEqual(nombre_seguro("/etc/pasw\x00d\n.pdf"), "paswd.pdf")
        self.assertEqual(len(nombre_seguro("x" * 1000 + ".pdf")), 120)
        self.assertEqual(nombre_seguro(None), "archivo")
        self.assertEqual(nombre_seguro("   "), "archivo")


# ------------------------------------------------------------------------------------------------------------
# Capa 2: inspeccion de PDF
# ------------------------------------------------------------------------------------------------------------

class InspeccionPdfTest(unittest.TestCase):
    def test_rechaza_bomba_de_descompresion_en_milisegundos(self):
        bomba = _pdf_bomba(5)
        self.assertLess(len(bomba), 40 * 1024)  # chico: pasaria cualquier filtro por tamaño de archivo
        t0 = time.time()
        with self.assertRaises(ArchivoNoPermitido):
            inspeccionar_pdf(bomba)
        self.assertLess(time.time() - t0, 2)

    def test_pdf_normal_pasa(self):
        inspeccionar_pdf(_pdf_por_facturar_sintetico())
        inspeccionar_pdf(_pdf(b"BT /F1 12 Tf 100 700 Td (hola) Tj ET " * 2000, comprimir=True))

    def test_rechaza_demasiadas_paginas(self):
        falso = b"%PDF-1.4\n" + b"<< /Type /Page /Parent 2 0 R >>\n" * 250
        with self.assertRaises(ArchivoNoPermitido):
            inspeccionar_pdf(falso)

    def test_no_confunde_pages_con_page(self):
        inspeccionar_pdf(b"%PDF-1.4\n" + b"<< /Type /Pages /Kids [] >>\n" * 500)

    def test_flujo_corrupto_no_rompe_la_inspeccion(self):
        inspeccionar_pdf(b"%PDF-1.4\n1 0 obj\n<< >>\nstream\n\x00\x01\x02basura\nendstream\nendobj\n")
        inspeccionar_pdf(b"%PDF-1.4\n1 0 obj\n<< >>\nstream\nsin cierre")


# ------------------------------------------------------------------------------------------------------------
# Excel dañado
# ------------------------------------------------------------------------------------------------------------

class ExcelHostilTest(unittest.TestCase):
    def test_hoja_declarada_gigante_se_rechaza(self):
        with self.assertRaises(ValueError):
            _validar_dimensiones(100_000, 5)
        with self.assertRaises(ValueError):
            _validar_dimensiones(10, 5_000)
        _validar_dimensiones(60, 12)

    def test_excel_danado_da_un_error_claro_y_no_una_excepcion_interna(self):
        rng = random.Random(7)
        for _ in range(25):
            basura = MAGIC_OLE2 + bytes(rng.randrange(256) for _ in range(rng.randint(8, 4000)))
            with self.assertRaises(ValueError) as e:
                parse_tarjeta_facturado_xls(basura)
            self.assertIn("danado", str(e.exception))


# ------------------------------------------------------------------------------------------------------------
# Capa 3: proceso aparte con tiempo limite
# ------------------------------------------------------------------------------------------------------------

class ProcesoAisladoTest(unittest.TestCase):
    def test_un_proceso_colgado_se_mata_al_pasar_el_tiempo(self):
        t0 = time.time()
        with self.assertRaises(LecturaFallida) as e:
            ejecutar_hijo([sys.executable, "-c", "import time; time.sleep(60)"], b"", timeout=1.5)
        self.assertLess(time.time() - t0, 10)
        self.assertIn("cancelo", str(e.exception))

    def test_un_proceso_que_muere_se_informa_sin_detalles_internos(self):
        with self.assertRaises(LecturaFallida) as e:
            ejecutar_hijo([sys.executable, "-c", "raise SystemExit(3)"], b"", timeout=10)
        self.assertNotIn("Traceback", str(e.exception))

    def test_salida_desmedida_se_descarta(self):
        with mock.patch.object(lectura_aislada, "MAX_SALIDA", 100):
            with self.assertRaises(LecturaFallida):
                ejecutar_hijo([sys.executable, "-c", "print('x' * 5000)"], b"", timeout=10)

    def test_ida_y_vuelta_json_conserva_fechas(self):
        original = {"a": datetime.date(2026, 10, 3), "b": [{"c": datetime.datetime(2026, 1, 2, 3, 4)}], "d": 1.5, "e": None,
                    "f": datetime.time(12, 30)}
        self.assertEqual(decodificar(codificar(original)), original)

    def test_json_no_permite_serializar_objetos_arbitrarios(self):
        with self.assertRaises(TypeError):
            codificar({"x": object()})

    def test_lee_un_documento_sintetico_de_punta_a_punta(self):
        resultado, tipo, clase = leer_documento_aislado("por_facturar.pdf", _pdf_por_facturar_sintetico())
        self.assertEqual((clase, tipo), ("tarjeta", "Tarjeta de credito (por facturar)"))
        self.assertEqual(resultado["moneda"], "CLP")
        self.assertEqual(resultado["numero_cuenta"], "TC-1234")
        self.assertEqual(resultado["periodo_hasta"], datetime.date(2026, 10, 3))  # la fecha vuelve como fecha
        self.assertEqual(resultado["estado_tc"]["cupo_total"], 6_000_000.0)
        movs = {t["descripcion"]: t for t in resultado["transacciones"]}
        self.assertEqual(movs["COMERCIO PRUEBA"]["monto_cargo"], 990.0)
        self.assertEqual(movs["PAGO TARJETA DE CREDITO (PAGO PESOS TEF PAGO NORMAL)"]["monto_abono"], 156913.0)
        self.assertIsInstance(resultado["transacciones"][0]["fecha"], datetime.date)

    def test_bomba_se_rechaza_antes_de_lanzar_el_proceso_o_dentro_de_el(self):
        t0 = time.time()
        with self.assertRaises(ArchivoNoPermitido):
            leer_documento_aislado("bomba.pdf", _pdf_bomba(5))
        self.assertLess(time.time() - t0, 15)

    def test_pdf_corrupto_da_mensaje_generico(self):
        with self.assertRaises((LecturaFallida, FormatoNoReconocido)) as e:
            leer_documento_aislado("roto.pdf", b"%PDF-1.4\n" + bytes(range(256)) * 20)
        self.assertNotIn("Traceback", str(e.exception))
        self.assertNotIn("pdfminer", str(e.exception).lower())

    def test_excel_corrupto_se_informa(self):
        with self.assertRaises((LecturaFallida, FormatoNoReconocido)):
            leer_documento_aislado("roto.xls", MAGIC_OLE2 + b"\x00" * 600)

    def test_la_lectura_completa_respeta_el_tiempo_limite(self):
        # Un lector que se cuelga (aqui simulado) debe cancelarse a los TIMEOUT_S, no dejar la app esperando.
        with mock.patch.object(lectura_aislada, "_comando", return_value=[sys.executable, "-c", "import time; time.sleep(60)"]),                 mock.patch.object(lectura_aislada, "TIMEOUT_S", 1.5):
            t0 = time.time()
            with self.assertRaises(LecturaFallida):
                leer_documento_aislado("a.pdf", _pdf_por_facturar_sintetico())
            self.assertLess(time.time() - t0, 15)


# ------------------------------------------------------------------------------------------------------------
# Datos absurdos que intenten llegar a la base
# ------------------------------------------------------------------------------------------------------------

def _lote(**kw):
    mov = dict(fecha=datetime.date(2026, 9, 1), descripcion="COMPRA", monto_cargo=1000.0, hash_dedupe="h")
    mov.update(kw)
    return LoteImportacion(origen=OrigenLote(FUENTE_PDF, "a.pdf"), cuenta=CuentaFuente(numero="TC-1", tipo="tarjeta", banco="B"),
                           movimientos=[MovimientoFuente(**mov)])


class ContratoHostilTest(unittest.TestCase):
    def _rechaza(self, lote, texto):
        with self.assertRaises(ValueError) as e:
            lote.validar()
        self.assertIn(texto, str(e.exception))

    def test_montos_no_finitos_o_gigantes(self):
        self._rechaza(_lote(monto_cargo=float("nan")), "monto")
        self._rechaza(_lote(monto_cargo=float("inf")), "monto")
        self._rechaza(_lote(monto_cargo=1e15), "monto")
        self._rechaza(_lote(monto_cargo="1000"), "monto")
        self._rechaza(_lote(saldo=float("inf")), "saldo")

    def test_fechas_absurdas_que_romperian_el_dashboard(self):
        self._rechaza(_lote(fecha=datetime.date(9999, 12, 31)), "rango")
        self._rechaza(_lote(fecha=datetime.date(1900, 1, 1)), "rango")
        _lote(fecha=datetime.date.today() + datetime.timedelta(days=30)).validar()

    def test_textos_con_control_o_demasiado_largos(self):
        self._rechaza(_lote(descripcion="a" * 600), "descripcion")
        self._rechaza(_lote(descripcion="x\x00y"), "descripcion")
        lote = _lote()
        lote.cuenta = CuentaFuente(numero="TC-1\n<script>", tipo="tarjeta", banco="B")
        self._rechaza(lote, "numero de cuenta")
        lote.cuenta = CuentaFuente(numero="TC-1", tipo="tarjeta", banco="B\x00")
        self._rechaza(lote, "banco")

    def test_el_adaptador_de_archivos_sanea_el_texto(self):
        resultado = {
            "numero_cuenta": "TC-1", "banco": "B", "tipo_cuenta": "tarjeta", "moneda": "CLP",
            "transacciones": [{"fecha": datetime.date(2026, 9, 1), "descripcion": "COMPRA\x00\x07  CON\tCONTROL " + "z" * 900,
                               "sucursal": "SANT\x1fIAGO", "monto_cargo": 5.0, "monto_abono": 0.0, "saldo": None, "hash_dedupe": "h"}],
        }
        lote = lote_desde_resultado(resultado, "a.pdf")
        m = lote.movimientos[0]
        self.assertLessEqual(len(m.descripcion), 500)
        self.assertNotIn("\x00", m.descripcion)
        self.assertTrue(m.descripcion.startswith("COMPRA CON CONTROL"))
        self.assertEqual(m.sucursal, "SANT IAGO")
        lote.validar()


if __name__ == "__main__":
    unittest.main()
