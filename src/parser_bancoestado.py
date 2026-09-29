"""Parser de cartolas CuentaRUT de BancoEstado en PDF.

La cartola trae una tabla FECHA | N OPERACION | DESCRIPCION | ABONOS | CARGOS | SALDO, con
fechas tipo "30/Jul." (dia/mes abreviado en español) y saldo YA impreso en cada fila (no hay
que reconstruirlo como en la cartola de Banco de Chile). Los movimientos vienen del mas
reciente al mas antiguo, al reves que las demas cartolas soportadas.

Cuando la descripcion es larga, BancoEstado la parte en una segunda linea sin fecha ni montos
(ej. el nombre completo de quien envio una transferencia) -- esa linea se pega a la
descripcion de la transaccion anterior en vez de tratarse como una fila nueva.

El PDF suele venir protegido con contraseña (una clave que define el banco, no necesariamente
el RUT) -- por eso todas las funciones aceptan un `password` opcional.
"""
import re
from datetime import date

import pdfplumber

from src.dedupe import hash_transaccion

COL_OPERACION_MAX = 140
COL_DESCRIPCION_MAX = 190
COL_ABONO_MAX = 340
COL_CARGO_MAX = 415
COL_SALDO_MAX = 495

FECHA_RE = re.compile(r"^(\d{2})/([A-Za-z]{3})\.?$")
RUT_RE = re.compile(r"\d{1,2}\.\d{3}\.\d{3}-[\dkK]")

MESES = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12,
}


def _clasificar_columna(x0: float) -> str:
    if x0 < COL_OPERACION_MAX:
        return "fecha"
    if x0 < COL_DESCRIPCION_MAX:
        return "operacion"
    if x0 < COL_ABONO_MAX:
        return "descripcion"
    if x0 < COL_CARGO_MAX:
        return "abono"
    if x0 < COL_SALDO_MAX:
        return "cargo"
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
    texto = texto.strip().lstrip("$").strip().replace(".", "").replace(",", ".")
    if not texto:
        return 0.0
    return float(texto)


def _fila_a_campos(fila):
    campos = {"fecha": [], "operacion": [], "descripcion": [], "abono": [], "cargo": [], "saldo": []}
    for w in fila:
        campos[_clasificar_columna(w["x0"])].append(w["text"])
    return {k: " ".join(v) for k, v in campos.items()}


def _resolver_fecha(dia_mes: str, desde: date, hasta: date) -> date | None:
    m = FECHA_RE.match(dia_mes)
    if not m:
        return None
    dia = int(m.group(1))
    mes = MESES.get(m.group(2).lower())
    if mes is None:
        return None
    anio = desde.year if desde and mes == desde.month else (hasta.year if hasta else desde.year)
    return date(anio, mes, dia)


def es_bancoestado_cuentarut(texto_pagina1: str) -> bool:
    """Detecta si el PDF es de este tipo (para el dispatcher en la pagina de carga)."""
    return "CUENTARUT" in texto_pagina1.upper()


def parse_cartola_bancoestado(path, password: str | None = None) -> dict:
    with pdfplumber.open(path, password=password or "") as pdf:
        texto_completo = "\n".join(p.extract_text() or "" for p in pdf.pages)
        filas_crudas = []
        for page in pdf.pages:
            filas_crudas.extend(_agrupar_en_filas(page.extract_words()))

    m = RUT_RE.search(texto_completo)
    numero_cuenta = m.group(0).replace(".", "").replace("-", "") if m else None

    m = re.search(r"N\S* Cartola\s*(\d+)", texto_completo)
    cartola_numero = m.group(1) if m else None

    m = re.search(r"Fecha Inicio\s*(\d{2}/\d{2}/\d{4})\s+Fecha Final\s*(\d{2}/\d{2}/\d{4})", texto_completo)
    desde = date(int(m.group(1)[6:]), int(m.group(1)[3:5]), int(m.group(1)[:2])) if m else None
    hasta = date(int(m.group(2)[6:]), int(m.group(2)[3:5]), int(m.group(2)[:2])) if m else None

    m = re.search(r"Saldo Anterior\s*\$\s*([\d.]+)", texto_completo)
    saldo_inicial = _monto(m.group(1)) if m else None

    m = re.search(r"Saldo Final\s*\$\s*([\d.]+)", texto_completo)
    saldo_final = _monto(m.group(1)) if m else None

    transacciones = []
    for fila in filas_crudas:
        campos = _fila_a_campos(fila)
        fecha_txt = campos["fecha"].strip()

        if fecha_txt == "Fecha":
            continue  # encabezado de la tabla (se repite en cada pagina)

        fecha = _resolver_fecha(fecha_txt, desde, hasta)
        if fecha is None:
            # No es una fila de movimiento nueva: puede ser texto de encabezado (antes del
            # primer movimiento), el resumen "Subtotales" del final de la tabla (tambien cae en
            # la columna de descripcion, pero trae sus propios montos), o la continuacion de una
            # descripcion larga de la fila anterior -- que nunca trae montos propios.
            texto_extra = campos["descripcion"].strip()
            tiene_montos = campos["abono"].strip() or campos["cargo"].strip() or campos["saldo"].strip()
            if texto_extra and transacciones and not tiene_montos:
                transacciones[-1]["descripcion"] = (transacciones[-1]["descripcion"] + " " + texto_extra).strip()
            continue

        saldo_txt = campos["saldo"].strip()
        transacciones.append(
            {
                "fecha": fecha,
                "descripcion": campos["descripcion"].strip(),
                "sucursal": "",
                "monto_cargo": _monto(campos["cargo"]),
                "monto_abono": _monto(campos["abono"]),
                "saldo": _monto(saldo_txt) if saldo_txt else None,
            }
        )

    # La tabla viene de la mas reciente a la mas antigua; se invierte para que quede en orden
    # cronologico ascendente, igual que las demas cartolas soportadas.
    transacciones.reverse()

    cuadratura_ok = None
    if saldo_inicial is not None:
        saldo_esperado = saldo_inicial
        cuadratura_ok = True
        for t in transacciones:
            saldo_esperado = round(saldo_esperado - t["monto_cargo"] + t["monto_abono"], 2)
            if t["saldo"] is not None and abs(saldo_esperado - t["saldo"]) >= 1:
                cuadratura_ok = False

    for t in transacciones:
        t["hash_dedupe"] = hash_transaccion(
            numero_cuenta, t["fecha"], t["descripcion"], t["monto_cargo"], t["monto_abono"], t["saldo"]
        )

    return {
        "banco": "BancoEstado",
        "numero_cuenta": numero_cuenta,
        "cartola_numero": cartola_numero,
        "periodo_desde": desde,
        "periodo_hasta": hasta,
        "saldo_inicial": saldo_inicial,
        "saldo_final": saldo_final,
        "saldo_disponible_fecha": hasta,
        "saldo_disponible_hora": None,
        "cuadratura_ok": cuadratura_ok,
        "tipo_cuenta": "vista",
        "moneda": "CLP",
        "transacciones": transacciones,
    }
