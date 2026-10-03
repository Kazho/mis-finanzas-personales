"""Lectura de documentos del banco SIN interfaz: detecta el tipo y llama al parser que corresponde.

Antes esta logica vivia dentro de la pantalla de carga. Separarla permite ejecutarla en un proceso aparte con
tiempo limite (`src/lectura_aislada.py`), que es la defensa contra archivos hostiles (ver
`src/seguridad_archivos.py`). Esta funcion es la que corre DENTRO de ese proceso, pero tambien se puede llamar
directo (pruebas).
"""
import io

import pdfplumber
from pdfminer.pdfdocument import PDFPasswordIncorrect
from pdfplumber.utils.exceptions import PdfminerException

from src.parser_bancoestado import es_bancoestado_cuentarut, parse_cartola_bancoestado
from src.parser_cartola import parse_cartola
from src.parser_cmf import parse_cmf
from src.parser_movimientos import es_movimientos, parse_movimientos
from src.parser_tarjeta_credito import es_tarjeta_credito, parse_tarjeta_credito
from src.parser_tarjeta_movimientos import (
    es_tarjeta_no_facturada,
    es_tarjeta_xls,
    parse_tarjeta_facturado_xls,
    parse_tarjeta_no_facturada,
)
from src.seguridad_archivos import MAX_PAGINAS_PDF, ArchivoNoPermitido, inspeccionar_pdf, validar_archivo


class ContrasenaRequerida(Exception):
    """El PDF esta protegido y falta la contraseña, o la entregada no es correcta."""


class FormatoNoReconocido(ValueError):
    """El archivo es valido pero no es un documento que la app sepa leer."""


def _abrir_pdf(contenido: bytes, password: str):
    try:
        pdf = pdfplumber.open(io.BytesIO(contenido), password=password or "")
    except PdfminerException as e:
        if e.args and isinstance(e.args[0], PDFPasswordIncorrect):
            raise ContrasenaRequerida() from e
        raise
    if len(pdf.pages) > MAX_PAGINAS_PDF:
        pdf.close()
        raise ArchivoNoPermitido(f"El PDF tiene demasiadas paginas (maximo {MAX_PAGINAS_PDF}).")
    return pdf


def leer_documento(nombre: str, contenido: bytes, password: str = "") -> tuple[dict, str, str]:
    """Devuelve (resultado_del_parser, nombre_del_tipo_de_documento, clase) con clase en
    {'tarjeta', 'cuenta', 'movimientos'}. Lanza ArchivoNoPermitido, ContrasenaRequerida o FormatoNoReconocido."""
    tipo = validar_archivo(nombre, contenido, ("pdf", "xls"))

    if tipo == "xls":
        if not es_tarjeta_xls(contenido):
            raise FormatoNoReconocido(
                "No se reconocio este Excel. Por ahora se soporta el Excel de movimientos facturados de tarjeta de credito."
            )
        return parse_tarjeta_facturado_xls(contenido), "Tarjeta de credito (facturado)", "tarjeta"

    inspeccionar_pdf(contenido)
    with _abrir_pdf(contenido, password) as pdf:
        texto_pagina1 = pdf.pages[0].extract_text() or ""

    archivo = io.BytesIO(contenido)
    if es_tarjeta_credito(texto_pagina1):
        return parse_tarjeta_credito(archivo, password=password), "Estado de cuenta tarjeta de credito", "tarjeta"
    if es_tarjeta_no_facturada(texto_pagina1):
        return parse_tarjeta_no_facturada(archivo, password=password), "Tarjeta de credito (por facturar)", "tarjeta"
    if es_bancoestado_cuentarut(texto_pagina1):
        return parse_cartola_bancoestado(archivo, password=password), "Cartola CuentaRUT", "cuenta"
    if es_movimientos(texto_pagina1):
        return parse_movimientos(archivo), "Movimientos al dia", "movimientos"
    return parse_cartola(archivo), "Cartola oficial", "cuenta"


def leer_informe_cmf(nombre: str, contenido: bytes) -> dict:
    """Informe de deudas de la CMF (PDF)."""
    validar_archivo(nombre, contenido, ("pdf",))
    inspeccionar_pdf(contenido)
    with _abrir_pdf(contenido, ""):
        pass
    return parse_cmf(io.BytesIO(contenido))
