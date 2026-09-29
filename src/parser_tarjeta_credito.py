"""Parser de estados de cuenta de TARJETA DE CREDITO (Santander, "Estado de cuenta en moneda nacional") en PDF.

A diferencia de una cartola de cuenta, aca no hay saldo por fila: la tabla "2. PERIODO ACTUAL" lista
las compras del periodo facturado y el pago del periodo anterior. Hay dos tipos de fila:

  * Compra normal:  [LUGAR] dd/mm/aaaa DESCRIPCION [monto en moneda origen] $ MONTO
  * Compra en cuotas (viene primero, agrupada con el subtotal): dd/mm/aaaa DESCRIPCION TIPO tasa %
    $ monto_original $ total_a_pagar N/M $ valor_cuota  -- lo que se carga este mes es el valor de la cuota.

"MONTO CANCELADO" (monto negativo) es el pago que hiciste de la factura anterior; se guarda como abono con
la descripcion "PAGO TARJETA DE CREDITO" para que caiga en la categoria del mismo nombre y netee contra el
cargo equivalente de tu cuenta corriente (ver `gasto_por_categoria_mes`).

Cuadratura: la suma de compras + cuotas (sin el pago) debe calzar con "1. TOTAL OPERACIONES" de la pagina 1.

El PDF viene protegido con contraseña, por eso las funciones aceptan un `password` opcional.
"""
import re
from datetime import date, datetime

import pdfplumber

from src.dedupe import hash_transaccion

FECHA = r"\d{2}/\d{2}/\d{4}"

CUOTA_RE = re.compile(
    rf"^(?P<f>{FECHA})\s+(?P<desc>.+?)\s+\d+,\d+\s*%\s+\$\s*[\d.]+\s+\$\s*[\d.]+\s+"
    r"(?P<n>\d+)/(?P<m>\d+)\s+\$\s*(?P<valor>[\d.]+)$"
)
COMPRA_RE = re.compile(
    rf"^(?:(?P<lugar>.+?)\s+)?(?P<f>{FECHA})\s+(?P<desc>.+?)\s+(?:[\d.]+,\d{{2}}\s+)?\$\s*(?P<monto>-?[\d.]+)$"
)

INICIO_SECCION = "2. PERIODO ACTUAL"
FIN_SECCION = ("EMISOR CLIENTE", "COMPROBANTE", "2. PRODUCTOS", "3. CARGOS", "4. INFORMACION")


def _fecha(texto: str) -> date:
    return datetime.strptime(texto, "%d/%m/%Y").date()


def _monto(texto: str) -> float:
    return float(texto.replace(".", ""))


def es_tarjeta_credito(texto_pagina1: str) -> bool:
    """Detecta si el PDF es de este tipo (para el dispatcher en la pagina de carga)."""
    return "ESTADO DE CUENTA EN MONEDA NACIONAL DE TARJETA DE CR" in texto_pagina1.upper()


def parse_tarjeta_credito(path, password: str | None = None) -> dict:
    with pdfplumber.open(path, password=password or "") as pdf:
        paginas = [p.extract_text() or "" for p in pdf.pages]
    texto_completo = "\n".join(paginas)

    m = re.search(r"(?:X{4}\s+){3}(\d{4})", texto_completo)
    numero_cuenta = f"TC-{m.group(1)}" if m else None

    banco = "Santander" if "SANTANDER" in texto_completo.upper() else "Tarjeta de credito"

    m = re.search(rf"PERIODO FACTURADO\s+({FECHA})\s+({FECHA})", texto_completo)
    desde, hasta = (_fecha(m.group(1)), _fecha(m.group(2))) if m else (None, None)

    m = re.search(r"1\. TOTAL OPERACIONES\s*\$\s*([\d.]+)", texto_completo)
    total_operaciones = _monto(m.group(1)) if m else None

    m = re.search(r"MONTO TOTAL FACTURADO A PAGAR\s*\$\s*([\d.]+)", texto_completo)
    total_facturado = _monto(m.group(1)) if m else None

    m = re.search(r"CUPO TOTAL\s*\$\s*([\d.]+)\s*\$\s*([\d.]+)\s*\$\s*([\d.]+)", texto_completo)
    cupo_total, cupo_utilizado, cupo_disponible = (_monto(g) for g in m.groups()) if m else (None, None, None)

    m = re.search(rf"PAGAR HASTA\s+({FECHA})", texto_completo)
    fecha_vencimiento = _fecha(m.group(1)) if m else None

    m = re.search(r"MONTO M.NIMO A PAGAR\s*\$\s*([\d.]+)", texto_completo)
    pago_minimo = _monto(m.group(1)) if m else None

    transacciones = []
    en_seccion = False
    for linea in texto_completo.split("\n"):
        linea = linea.strip()
        if linea.startswith(INICIO_SECCION):
            en_seccion = True
            continue
        if linea.startswith(FIN_SECCION):
            en_seccion = False
            continue
        if not en_seccion:
            continue

        m = CUOTA_RE.match(linea)
        if m:
            # La cuota se cobra en la facturacion de este periodo, no en la fecha de la compra original
            # (que puede ser de hace un año): asi el gasto cae en el mes correcto.
            transacciones.append({
                "fecha": hasta or _fecha(m.group("f")),
                "descripcion": f"{m.group('desc')} (cuota {m.group('n')}/{m.group('m')})",
                "sucursal": "",
                "monto_cargo": _monto(m.group("valor")),
                "monto_abono": 0.0,
                "saldo": None,
            })
            continue

        m = COMPRA_RE.match(linea)
        if not m:
            continue
        monto = _monto(m.group("monto"))
        es_pago = monto < 0 or "MONTO CANCELADO" in m.group("desc").upper()
        transacciones.append({
            "fecha": _fecha(m.group("f")),
            "descripcion": "PAGO TARJETA DE CREDITO (MONTO CANCELADO)" if es_pago else m.group("desc"),
            "sucursal": m.group("lugar") or "",
            "monto_cargo": 0.0 if es_pago else monto,
            "monto_abono": abs(monto) if es_pago else 0.0,
            "saldo": None,
        })

    cuadratura_ok = None
    if total_operaciones is not None:
        cuadratura_ok = abs(sum(t["monto_cargo"] for t in transacciones) - total_operaciones) < 1

    transacciones.sort(key=lambda t: t["fecha"])

    # Sin saldo por fila, dos compras identicas el mismo dia (mismo comercio y monto) darian el mismo
    # hash y la segunda se descartaria como duplicada: se distinguen por orden de aparicion.
    vistos = {}
    for t in transacciones:
        clave = (t["fecha"], t["descripcion"], t["monto_cargo"], t["monto_abono"])
        vistos[clave] = vistos.get(clave, 0) + 1
        sufijo = f" #{vistos[clave]}" if vistos[clave] > 1 else ""
        t["hash_dedupe"] = hash_transaccion(
            numero_cuenta, t["fecha"], t["descripcion"] + sufijo, t["monto_cargo"], t["monto_abono"], None
        )

    return {
        "banco": banco,
        "numero_cuenta": numero_cuenta,
        "cartola_numero": None,
        "periodo_desde": desde,
        "periodo_hasta": hasta,
        "saldo_inicial": None,
        # Monto facturado a pagar, no un saldo de cuenta. `saldo_disponible_fecha` en None evita que se
        # guarde como saldo_snapshot (no es plata tuya, es deuda).
        "saldo_final": total_facturado,
        "saldo_disponible_fecha": None,
        "saldo_disponible_hora": None,
        "cuadratura_ok": cuadratura_ok,
        "es_tarjeta_credito": True,
        "tipo_cuenta": "tarjeta",
        "moneda": "CLP",
        "estado_tc": {
            "periodo_hasta": hasta,
            "monto_facturado": total_facturado,
            "pago_minimo": pago_minimo,
            "fecha_vencimiento": fecha_vencimiento,
            "cupo_total": cupo_total,
            "cupo_utilizado": cupo_utilizado,
            "cupo_disponible": cupo_disponible,
        } if hasta else None,
        "transacciones": transacciones,
    }
