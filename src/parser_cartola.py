"""Parser de cartolas de Cuenta Corriente Banco de Chile en PDF.

La cartola trae una tabla FECHA | DETALLE | SUCURSAL | N DOCTO | CARGOS | ABONOS | SALDO.
El texto plano del PDF no siempre imprime el SALDO por fila (aparece solo cuando
la celda visual "cambia"), asi que reconstruimos el saldo corriente sumando
cargos/abonos a partir del saldo inicial, y usamos el saldo final solo como
verificacion.

Las columnas se distinguen por la coordenada x0 de cada palabra (ver
scratch_test.py usado durante el desarrollo para calibrar estos limites).
"""
import re
from datetime import date

import pdfplumber

from src.dedupe import hash_transaccion

COL_FECHA_MAX = 30
COL_DESC_MAX = 230
COL_SUCURSAL_MAX = 300
COL_DOCTO_MAX = 350
COL_CARGO_MAX = 430
COL_ABONO_MAX = 536

FECHA_RE = re.compile(r"^\d{2}/\d{2}$")


def _clasificar_columna(x0: float) -> str:
    if x0 < COL_FECHA_MAX:
        return "fecha"
    if x0 < COL_DESC_MAX:
        return "descripcion"
    if x0 < COL_SUCURSAL_MAX:
        return "sucursal"
    if x0 < COL_DOCTO_MAX:
        return "docto"
    if x0 < COL_CARGO_MAX:
        return "cargo"
    if x0 < COL_ABONO_MAX:
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
    campos = {"fecha": [], "descripcion": [], "sucursal": [], "docto": [], "cargo": [], "abono": [], "saldo": []}
    for w in fila:
        campos[_clasificar_columna(w["x0"])].append(w["text"])
    return {k: " ".join(v) for k, v in campos.items()}


def _extraer_metadata(texto_completo: str) -> dict:
    meta = {}
    m = re.search(r"N\S* DE CUENTA\s*:\s*(\d+)", texto_completo)
    meta["numero_cuenta"] = m.group(1).lstrip("0") if m else None
    m = re.search(r"CARTOLA N\S*\s*:\s*(\d+)", texto_completo)
    meta["cartola_numero"] = m.group(1) if m else None
    m = re.search(r"DESDE\s*:\s*(\d{2}/\d{2}/\d{4})\s+HASTA\s*:\s*(\d{2}/\d{2}/\d{4})", texto_completo)
    if m:
        meta["periodo_desde"] = m.group(1)
        meta["periodo_hasta"] = m.group(2)
    else:
        meta["periodo_desde"] = meta["periodo_hasta"] = None
    return meta


def _resolver_fecha(dia_mes: str, desde: date, hasta: date) -> date:
    dia, mes = (int(p) for p in dia_mes.split("/"))
    anio = desde.year if mes == desde.month else hasta.year
    return date(anio, mes, dia)


def parse_cartola(path: str) -> dict:
    with pdfplumber.open(path) as pdf:
        texto_completo = "\n".join(p.extract_text() or "" for p in pdf.pages)
        meta = _extraer_metadata(texto_completo)

        filas_crudas = []
        for page in pdf.pages:
            filas_crudas.extend(_agrupar_en_filas(page.extract_words()))

    desde = date.fromisoformat("-".join(reversed(meta["periodo_desde"].split("/")))) if meta["periodo_desde"] else None
    hasta = date.fromisoformat("-".join(reversed(meta["periodo_hasta"].split("/")))) if meta["periodo_hasta"] else None

    transacciones = []
    saldo_inicial = None
    saldo_final = None

    for fila in filas_crudas:
        campos = _fila_a_campos(fila)
        fecha_txt = campos["fecha"].strip()
        if not FECHA_RE.match(fecha_txt):
            continue

        descripcion = campos["descripcion"].strip()
        fecha = _resolver_fecha(fecha_txt, desde, hasta) if desde and hasta else None

        if descripcion.upper() == "SALDO INICIAL":
            saldo_inicial = _monto(campos["saldo"])
            continue
        if descripcion.upper() == "SALDO FINAL":
            saldo_final = _monto(campos["saldo"])
            continue

        transacciones.append(
            {
                "fecha": fecha,
                "descripcion": descripcion,
                "sucursal": campos["sucursal"].strip(),
                "monto_cargo": _monto(campos["cargo"]),
                "monto_abono": _monto(campos["abono"]),
                "saldo_impreso": _monto(campos["saldo"]) if campos["saldo"].strip() else None,
            }
        )

    saldo_corriente = saldo_inicial
    for t in transacciones:
        if saldo_corriente is not None:
            saldo_corriente = saldo_corriente - t["monto_cargo"] + t["monto_abono"]
            t["saldo"] = round(saldo_corriente, 2)
        else:
            t["saldo"] = t["saldo_impreso"]
        del t["saldo_impreso"]
        t["hash_dedupe"] = hash_transaccion(
            meta["numero_cuenta"], t["fecha"], t["descripcion"], t["monto_cargo"], t["monto_abono"], t["saldo"]
        )

    cuadratura_ok = None
    if saldo_corriente is not None and saldo_final is not None:
        cuadratura_ok = abs(saldo_corriente - saldo_final) < 1

    return {
        "banco": "Banco de Chile",
        "numero_cuenta": meta["numero_cuenta"],
        "cartola_numero": meta["cartola_numero"],
        "periodo_desde": desde,
        "periodo_hasta": hasta,
        "saldo_inicial": saldo_inicial,
        "saldo_final": saldo_final,
        "saldo_disponible_fecha": hasta,
        "saldo_disponible_hora": None,
        "cuadratura_ok": cuadratura_ok,
        "transacciones": transacciones,
    }
