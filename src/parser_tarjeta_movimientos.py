"""Tarjeta de credito en formato "Movimientos" de la banca en linea (Visa Infinite y similares).

El mismo banco entrega la tarjeta en CUATRO documentos, segun moneda y estado:

  * Facturado, pesos (.xls):   "Movimientos Facturados" + "Movimientos Nacionales"
  * Facturado, dolares (.xls): "Movimientos Facturados" + "Movimientos Internacionales"
  * Por facturar (PDF), pesos o dolares: "Saldo y Movimientos No Facturados al dd/mm/aaaa" -- lo que paso
    despues del ultimo corte (compras nuevas y pagos), con el cupo disponible/utilizado/total.

Los documentos no dicen de que banco son, asi que `banco` queda en None y la pagina de carga lo pregunta
(y lo recuerda por numero de tarjeta). Las cuentas son una por tarjeta y moneda: "TC-1234" en pesos y
"TC-1234 (USD)" en dolares.

Los pagos de la tarjeta ("MONTO CANCELADO", "PAGO PESOS/DOLAR TEF") se guardan como abono con la glosa
"PAGO TARJETA DE CREDITO (...)", que es la que reconoce la conciliacion con tu cuenta corriente.

Las compras por facturar son PROVISIONALES: al cargar el estado de cuenta facturado siguiente se reemplazan
(ver `db.reemplazar_provisionales`), asi que nunca se cuentan dos veces.
"""
import re
import unicodedata
from datetime import date, datetime

import pdfplumber

from src.dedupe import asignar_hashes
from src.parser_bancoestado import _agrupar_en_filas

FECHA_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
CUOTA_RE = re.compile(r"^(\d{2})/(\d{2})$")
NUMERO_TARJETA_RE = re.compile(r"\*{4,}\s*(\d{4})")
TOLERANCIA_CUADRATURA = {"CLP": 1.0, "USD": 0.015}

GLOSAS_PAGO = ("MONTO CANCELADO", "PAGO DOLAR TEF", "PAGO PESOS TEF")

# Un Excel de movimientos real tiene unas decenas de filas. Un archivo que declara una hoja gigante se rechaza antes de
# leer ninguna celda (`xlrd` carga toda la hoja en memoria).
MAX_FILAS_XLS = 5000
MAX_COLUMNAS_XLS = 64


def _norm(texto) -> str:
    """Minusculas, sin tildes y con espacios simples, para reconocer encabezados sin depender de la codificacion."""
    texto = unicodedata.normalize("NFD", str(texto).strip().lower())
    return " ".join("".join(c for c in texto if unicodedata.category(c) != "Mn").split())


def _fecha(texto: str) -> date:
    return datetime.strptime(texto.strip(), "%d/%m/%Y").date()


def _es_pago(descripcion: str, monto: float) -> bool:
    return monto < 0 or descripcion.strip().upper().startswith(GLOSAS_PAGO)


def _glosa(descripcion: str, es_pago: bool, cuota: str | None) -> str:
    descripcion = " ".join(descripcion.split())
    if es_pago:
        return f"PAGO TARJETA DE CREDITO ({descripcion.upper()})"
    m = CUOTA_RE.match(cuota or "")
    if m and int(m.group(2)) > 1:
        # La cuota se distingue por su numero: sin esto, la cuota 2/3 de un mes y la 3/3 del siguiente
        # tendrian el mismo hash y la segunda se descartaria como duplicada.
        return f"{descripcion} (cuota {m.group(1)}/{m.group(2)})"
    return descripcion


def _numero_tarjeta(texto: str) -> str | None:
    m = NUMERO_TARJETA_RE.search(texto)
    return f"TC-{m.group(1)}" if m else None


def _resultado(*, numero, moneda, estado, periodo_hasta, saldo_final, etiqueta_saldo, cuadratura_ok, estado_tc,
               transacciones):
    clave = f"{numero}-{moneda}"
    asignar_hashes(transacciones, clave)
    for t in transacciones:
        t["estado"] = estado
    return {
        "banco": None,
        "numero_cuenta": numero,
        "cartola_numero": None,
        "periodo_desde": None,
        "periodo_hasta": periodo_hasta,
        "saldo_inicial": None,
        "saldo_final": saldo_final,
        "saldo_disponible_fecha": None,
        "saldo_disponible_hora": None,
        "cuadratura_ok": cuadratura_ok,
        "es_tarjeta_credito": True,
        "tipo_cuenta": "tarjeta",
        "moneda": moneda,
        "estado": estado,
        "etiqueta_saldo": etiqueta_saldo,
        "sufijo_cuenta": " (USD)" if moneda == "USD" else "",
        "estado_tc": estado_tc,
        "transacciones": transacciones,
    }


# --------------------------------------------------------------------------------------------------
# Facturado (.xls)
# --------------------------------------------------------------------------------------------------

def _leer_xls(contenido: bytes) -> list[list]:
    try:
        import xlrd  # solo hace falta para este formato (.xls antiguo; openpyxl no lo lee)
    except ImportError as e:
        raise RuntimeError("Falta la libreria xlrd para leer archivos .xls: instalala con `py -m pip install xlrd`.") from e

    try:
        # on_demand: solo se carga la hoja que se pide, no todas las que declare el archivo
        hoja = xlrd.open_workbook(file_contents=contenido, on_demand=True).sheet_by_index(0)
        _validar_dimensiones(hoja.nrows, hoja.ncols)
        return [[hoja.cell_value(r, c) for c in range(hoja.ncols)] for r in range(hoja.nrows)]
    except ValueError:
        raise
    except Exception as e:  # xlrd lanza IndexError, AssertionError, struct.error... ante archivos danados
        raise ValueError("El archivo Excel esta danado o no es un .xls valido.") from e


def _validar_dimensiones(filas: int, columnas: int) -> None:
    if filas > MAX_FILAS_XLS or columnas > MAX_COLUMNAS_XLS:
        raise ValueError("El Excel declara una hoja demasiado grande para ser un movimiento de tarjeta; se rechazo por seguridad.")


def es_tarjeta_xls(contenido: bytes) -> bool:
    try:
        filas = _leer_xls(contenido)
    except RuntimeError:
        raise  # falta xlrd: que el usuario lo vea, no que parezca un formato desconocido
    except Exception:
        return False
    textos = {_norm(c) for f in filas for c in f if isinstance(c, str)}
    return "movimientos facturados" in textos and any(t.startswith("tipo de tarjeta") for t in textos)


def parse_tarjeta_facturado_xls(contenido: bytes) -> dict:
    return _parse_filas_facturado(_leer_xls(contenido))


def _parse_filas_facturado(filas: list[list]) -> dict:
    numero = None
    for f in filas:
        if f and any(isinstance(c, str) and _norm(c).startswith("tipo de tarjeta") for c in f):
            numero = _numero_tarjeta(" ".join(str(c) for c in f))

    # Totales: una fila de rotulos (Monto Facturado / Pago Minimo / Fecha de Facturacion / Pagar Hasta)
    # y, justo debajo, los valores en las mismas columnas.
    totales = {}
    for i, f in enumerate(filas):
        rotulos = {c: _norm(v) for c, v in enumerate(f) if isinstance(v, str) and v.strip()}
        if "fecha de facturacion" in rotulos.values() and i + 1 < len(filas):
            siguiente = filas[i + 1]
            for c, rotulo in rotulos.items():
                if c < len(siguiente) and siguiente[c] != "":
                    totales[rotulo] = siguiente[c]
            break
    if "fecha de facturacion" not in totales:
        raise ValueError("No se encontro la fecha de facturacion en el Excel.")
    fecha_facturacion = _fecha(totales["fecha de facturacion"])
    vencimiento = _fecha(totales["pagar hasta"]) if totales.get("pagar hasta") else None
    pago_minimo = totales.get("pago minimo")
    monto_total = totales.get("monto facturado", totales.get("deuda total en dolar"))

    # Tabla de movimientos: la fila de encabezados fija en que columna esta cada dato.
    cols, inicio, moneda = {}, None, "CLP"
    for i, f in enumerate(filas):
        rotulos = {_norm(v): c for c, v in enumerate(f) if isinstance(v, str) and v.strip()}
        if "fecha" in rotulos and "descripcion" in rotulos and ("monto ($)" in rotulos or "monto (usd)" in rotulos):
            cols = {"fecha": rotulos["fecha"], "descripcion": rotulos["descripcion"],
                    "cuotas": rotulos.get("cuotas"), "pais": rotulos.get("pais")}
            if "monto (usd)" in rotulos:
                cols["monto"], moneda = rotulos["monto (usd)"], "USD"
            else:
                cols["monto"] = rotulos["monto ($)"]
            inicio = i + 1
            break
    if inicio is None:
        raise ValueError("No se encontro la tabla de movimientos en el Excel.")

    transacciones = []
    for f in filas[inicio:]:
        texto_fecha = f[cols["fecha"]] if cols["fecha"] < len(f) else ""
        if not isinstance(texto_fecha, str) or not FECHA_RE.match(texto_fecha.strip()):
            continue
        monto = float(f[cols["monto"]])
        descripcion = str(f[cols["descripcion"]])
        cuota = f[cols["cuotas"]] if cols["cuotas"] is not None and cols["cuotas"] < len(f) else None
        pago = _es_pago(descripcion, monto)
        m_cuota = CUOTA_RE.match(str(cuota or ""))
        es_cuota_posterior = bool(m_cuota) and int(m_cuota.group(1)) > 1
        pais = f[cols["pais"]] if cols["pais"] is not None and cols["pais"] < len(f) else ""
        transacciones.append({
            # Una cuota 2/3, 3/3... se cobra en este corte, no en la fecha de la compra original.
            "fecha": fecha_facturacion if es_cuota_posterior and not pago else _fecha(texto_fecha),
            "descripcion": _glosa(descripcion, pago, str(cuota) if cuota else None),
            "sucursal": str(pais).strip(),
            "monto_cargo": 0.0 if pago else round(abs(monto), 2),
            "monto_abono": round(abs(monto), 2) if pago else 0.0,
            "saldo": None,
        })

    cuadratura_ok = None
    if monto_total is not None:
        suma = round(sum(t["monto_cargo"] for t in transacciones), 2)
        cuadratura_ok = abs(suma - float(monto_total)) < TOLERANCIA_CUADRATURA[moneda]

    transacciones.sort(key=lambda t: t["fecha"])
    return _resultado(
        numero=numero, moneda=moneda, estado="facturado", periodo_hasta=fecha_facturacion,
        saldo_final=float(monto_total) if monto_total is not None else None,
        etiqueta_saldo="Monto facturado a pagar", cuadratura_ok=cuadratura_ok,
        estado_tc={
            "periodo_hasta": fecha_facturacion,
            "monto_facturado": float(monto_total) if monto_total is not None else None,
            "pago_minimo": float(pago_minimo) if pago_minimo not in (None, "") else None,
            "fecha_vencimiento": vencimiento,
            "cupo_total": None, "cupo_utilizado": None, "cupo_disponible": None,
        },
        transacciones=transacciones,
    )


# --------------------------------------------------------------------------------------------------
# Por facturar (PDF)
# --------------------------------------------------------------------------------------------------

def es_tarjeta_no_facturada(texto_pagina1: str) -> bool:
    t = texto_pagina1.upper()
    return "NO FACTURADOS" in t and "TIPO DE TARJETA" in t


def _monto_pdf(texto: str, moneda: str) -> float:
    """Pesos: 1.234 o 1,234 (sin decimales). Dolares: 1.234,56 (coma decimal)."""
    texto = texto.strip().lstrip("$")
    if moneda == "CLP":
        return float(re.sub(r"[.,]", "", texto))
    return float(texto.replace(".", "").replace(",", "."))


def parse_tarjeta_no_facturada(path, password: str | None = None) -> dict:
    with pdfplumber.open(path, password=password or "") as pdf:
        paginas = [(p.extract_text() or "", _agrupar_en_filas(p.extract_words())) for p in pdf.pages]
    texto = "\n".join(t for t, _ in paginas)

    numero = _numero_tarjeta(texto)
    m = re.search(r"No Facturados al\s*(\d{2}/\d{2}/\d{4})", texto)
    if not m:
        raise ValueError("No se encontro la fecha del documento de movimientos no facturados.")
    fecha_consulta = _fecha(m.group(1))

    moneda = None
    cupos = None
    cols = {}
    transacciones = []
    for _, filas in paginas:
        for fila in filas:
            palabras = sorted(fila, key=lambda w: w["x0"])
            linea = " ".join(w["text"] for w in palabras)
            norm = _norm(linea)

            if norm.startswith("movimientos nacionales") or norm.startswith("movimientos internacionales"):
                nueva = "USD" if "internacionales" in norm else "CLP"
                if moneda and nueva != moneda:
                    raise ValueError("El documento mezcla movimientos en pesos y en dolares; cargalos por separado.")
                moneda, cols = nueva, {}
                continue

            if norm.startswith("cupo disponible"):
                cupos = "esperando"  # los 3 numeros vienen en la fila siguiente
                continue
            if cupos == "esperando":
                valores = [w["text"] for w in palabras]
                cupos = valores if len(valores) == 3 else None
                continue

            # Encabezado de la tabla: fija los limites de columna de lo que viene debajo.
            if palabras and _norm(palabras[0]["text"]) == "fecha" and "descripci" in norm:
                x = {_norm(w["text"]): w["x0"] for w in palabras}
                desc_x = next(w["x0"] for w in palabras if _norm(w["text"]).startswith("descripci"))
                siguiente = min((v for k, v in x.items() if k in ("pais", "ciudad")), default=desc_x + 140)
                cols = {
                    "desc": (desc_x - 4, siguiente - 4),
                    "pais": (siguiente - 4, x.get("ciudad", siguiente + 70) - 4) if "pais" in x else None,
                    "cuotas": x.get("cuotas"),
                    "monto": x["montos"] - 10,
                }
                continue

            if not cols or moneda is None:
                continue

            es_fecha = bool(palabras) and FECHA_RE.match(palabras[0]["text"])
            desc = " ".join(w["text"] for w in palabras if cols["desc"][0] <= w["x0"] < cols["desc"][1])
            pais = ""
            if cols["pais"]:
                pais = " ".join(w["text"] for w in palabras if cols["pais"][0] <= w["x0"] < cols["pais"][1])

            if not es_fecha:
                # Continuacion de la fila anterior (el banco parte las glosas y los paises largos).
                if transacciones and (desc or pais) and not any(w["x0"] >= cols["monto"] for w in palabras):
                    anterior = transacciones[-1]
                    if desc and not anterior["_pago"]:
                        anterior["descripcion"] = f"{anterior['descripcion']} {desc}"
                    if pais:
                        anterior["sucursal"] = f"{anterior['sucursal']} {pais}".strip()
                continue

            monto_txt = " ".join(w["text"] for w in palabras if w["x0"] >= cols["monto"])
            if not monto_txt:
                continue
            monto = _monto_pdf(monto_txt, moneda)
            cuota = None
            if cols["cuotas"]:
                cuota = next((w["text"] for w in palabras
                              if cols["cuotas"] - 5 <= w["x0"] < cols["monto"] and CUOTA_RE.match(w["text"])), None)
            pago = _es_pago(desc, monto)
            transacciones.append({
                "fecha": _fecha(palabras[0]["text"]),
                "descripcion": desc,
                "sucursal": pais,
                "monto_cargo": 0.0 if pago else abs(monto),
                "monto_abono": abs(monto) if pago else 0.0,
                "saldo": None,
                "_pago": pago,
                "_cuota": cuota,
            })

    if moneda is None:
        raise ValueError("No se encontro ninguna seccion de movimientos en el PDF.")
    for t in transacciones:
        t["descripcion"] = _glosa(t["descripcion"], t.pop("_pago"), t.pop("_cuota"))

    cupo_disponible = cupo_utilizado = cupo_total = None
    if isinstance(cupos, list):
        cupo_disponible, cupo_utilizado, cupo_total = (_monto_pdf(v, moneda) for v in cupos)

    transacciones.sort(key=lambda t: t["fecha"])
    return _resultado(
        numero=numero, moneda=moneda, estado="por_facturar", periodo_hasta=fecha_consulta,
        saldo_final=cupo_utilizado, etiqueta_saldo="Cupo utilizado", cuadratura_ok=None,
        estado_tc={
            "periodo_hasta": fecha_consulta, "monto_facturado": None, "pago_minimo": None, "fecha_vencimiento": None,
            "cupo_total": cupo_total, "cupo_utilizado": cupo_utilizado, "cupo_disponible": cupo_disponible,
        },
        transacciones=transacciones,
    )
