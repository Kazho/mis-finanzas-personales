"""Parser del PDF "Movimientos al [fecha]" de Banco de Chile (banca en linea / app), distinto
de la cartola oficial mensual: se puede descargar en cualquier momento y trae el saldo del dia
mas los ultimos movimientos, cada uno con su propio saldo ya impreso (no hay que reconstruirlo).

Util para saber el saldo actual antes de que salga la cartola oficial del mes; el hash de
deduplicacion (ver src.dedupe) esta pensado para que estas transacciones no se dupliquen cuando
mas tarde cargues la cartola oficial que cubra las mismas fechas.
"""
import re
from datetime import date

import pdfplumber

from src.dedupe import hash_transaccion

COL_DESC_MAX = 100
COL_SUCURSAL_MAX = 246
COL_CARGO_MAX = 307
COL_ABONO_MAX = 394
COL_SALDO_MAX = 481

FECHA_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")


def _clasificar_columna(x0: float) -> str:
    if x0 < COL_DESC_MAX:
        return "fecha"
    if x0 < COL_SUCURSAL_MAX:
        return "descripcion"
    if x0 < COL_CARGO_MAX:
        return "sucursal"
    if x0 < COL_ABONO_MAX:
        return "cargo"
    if x0 < COL_SALDO_MAX:
        return "abono"
    return "saldo"


def _agrupar_en_filas(words, tol=3):
    filas = []
    fila_actual = []
    top_actual = None
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if top_actual is None or abs(w["top"] - top_actual) > tol:
            if fila_actual:
                filas.append(fila_actual)
            fila_actual = [w]
            top_actual = w["top"]
        else:
            fila_actual.append(w)
    if fila_actual:
        filas.append(fila_actual)
    return filas


def _monto(texto: str) -> float:
    texto = texto.strip().replace(".", "").replace(",", ".")
    if not texto:
        return 0.0
    return float(texto)


def _fila_a_campos(fila):
    campos = {"fecha": [], "descripcion": [], "sucursal": [], "cargo": [], "abono": [], "saldo": []}
    for w in fila:
        campos[_clasificar_columna(w["x0"])].append(w["text"])
    return {k: " ".join(v) for k, v in campos.items()}


def _fecha(texto: str) -> date:
    d, m, a = texto.split("/")
    return date(int(a), int(m), int(d))


def es_movimientos(texto_completo: str) -> bool:
    """Detecta si el PDF es de este tipo (para el dispatcher en la pagina de carga)."""
    return "Movimientos al" in texto_completo and "Saldo Disponible" in texto_completo


def parse_movimientos(path: str) -> dict:
    with pdfplumber.open(path) as pdf:
        texto_completo = "\n".join(p.extract_text() or "" for p in pdf.pages)
        filas_crudas = []
        for page in pdf.pages:
            filas_crudas.extend(_agrupar_en_filas(page.extract_words()))

    m = re.search(r"Cuenta N.?:\s*([\d-]+)", texto_completo)
    numero_cuenta = re.sub(r"\D", "", m.group(1)).lstrip("0") if m else None

    m = re.search(r"Movimientos al (\d{2}/\d{2}/\d{4})", texto_completo)
    fecha_movimientos = _fecha(m.group(1)) if m else None

    # El PDF imprime primero las 4 etiquetas (Saldo Disponible, Saldo Contable,
    # Retenciones 24/48 Hrs.) y despues los 4 valores en el mismo orden, no una al lado
    # de la otra — el primer numero despues del bloque de etiquetas es el que corresponde
    # a "Saldo Disponible".
    m = re.search(r"Saldo Disponible.*?Retenciones 48 Hrs\.\s*([\d.]+)", texto_completo, re.DOTALL)
    saldo_disponible = _monto(m.group(1)) if m else None

    transacciones = []
    for fila in filas_crudas:
        campos = _fila_a_campos(fila)
        fecha_txt = campos["fecha"].strip()
        if not FECHA_RE.match(fecha_txt):
            continue

        descripcion = campos["descripcion"].strip()
        if not descripcion:
            continue

        saldo_txt = campos["saldo"].strip()
        t = {
            "fecha": _fecha(fecha_txt),
            "descripcion": descripcion,
            "sucursal": campos["sucursal"].strip(),
            "monto_cargo": _monto(campos["cargo"]),
            "monto_abono": _monto(campos["abono"]),
            "saldo": _monto(saldo_txt) if saldo_txt else None,
        }
        t["hash_dedupe"] = hash_transaccion(
            numero_cuenta, t["fecha"], t["descripcion"], t["monto_cargo"], t["monto_abono"], t["saldo"]
        )
        transacciones.append(t)

    # El PDF las lista de la mas reciente a la mas antigua; se invierte para que queden en
    # orden cronologico ascendente, igual que la cartola oficial. Esto importa para saber cual
    # es realmente "la ultima transaccion" cuando dos movimientos caen el mismo dia (la fecha
    # sola no alcanza para distinguirlas, pero el orden de insercion si).
    transacciones.reverse()

    return {
        "banco": "Banco de Chile",
        "numero_cuenta": numero_cuenta,
        "cartola_numero": None,
        "periodo_desde": None,
        "periodo_hasta": fecha_movimientos,
        "saldo_inicial": None,
        "saldo_final": saldo_disponible,
        "cuadratura_ok": None,
        "transacciones": transacciones,
    }
