"""Parser del Informe de Deudas de la CMF (Ley 21.680) en PDF.

El informe trae tablas de Deuda Directa / Deuda Indirecta (una fila por
institucion + tipo de credito) y de Creditos disponibles > Lineas de credito
(una fila por institucion). Estas tablas se extraen bien con extract_text()
porque cada fila queda en una sola linea de texto.

La tabla "Otros creditos" queda intercalada en el texto junto a "Lineas de
credito" (columnas lado a lado en el PDF original) y en la practica casi
siempre esta vacia para personas naturales, asi que solo se extrae su total,
no el detalle por institucion.
"""
import re
from datetime import date

import pdfplumber

FILA_INSTITUCION_RE = re.compile(
    r"^(?P<inst>.+?\(\d+\))\s+(?P<tipo>.+?)\s+(?P<fecha>\d{2}/\d{2}/\d{4})\s+"
    r"\$(?P<total>[\d.]+)\s+\$(?P<vigente>[\d.]+)\s+\$(?P<a1>[\d.]+)\s+\$(?P<a2>[\d.]+)\s+\$(?P<a3>[\d.]+)"
)
FILA_LINEA_CREDITO_RE = re.compile(r"^(?P<inst>.+?\(\d+\))\s+\$(?P<directos>[\d.]+)\s+\$(?P<indirectos>[\d.]+)")


def _monto(texto: str) -> float:
    return float(texto.replace(".", "").replace(",", "."))


def _fecha(texto: str) -> date:
    d, m, a = texto.split("/")
    return date(int(a), int(m), int(d))


def parse_cmf(path: str) -> dict:
    with pdfplumber.open(path) as pdf:
        texto = "\n".join(p.extract_text() or "" for p in pdf.pages)

    lineas = texto.split("\n")

    m = re.search(r"Deuda total\s+\$([\d.]+)", texto)
    deuda_total = _monto(m.group(1)) if m else None

    m = re.search(r"EMITIDO EL (\d{2}/\d{2}/\d{4})", texto)
    fecha_informe = _fecha(m.group(1)) if m else None

    m = re.search(r"ACTUALIZADA AL (\d{2}/\d{2}/\d{4})", texto)
    fecha_actualizacion = _fecha(m.group(1)) if m else None

    m = re.search(r"Rut:([\d.]+-[\dkK])", texto)
    rut = m.group(1) if m else None

    deuda_directa = []
    deuda_indirecta = []
    lineas_credito = []

    seccion = None
    for linea in lineas:
        if linea.startswith("Deuda Directa"):
            seccion = "directa"
            continue
        if linea.startswith("Deuda Indirecta"):
            seccion = "indirecta"
            continue
        if linea.startswith("Créditos disponibles"):
            seccion = "creditos"
            continue

        if seccion in ("directa", "indirecta"):
            m = FILA_INSTITUCION_RE.match(linea)
            if m:
                fila = {
                    "institucion": m.group("inst").strip(),
                    "tipo_credito": m.group("tipo").strip(),
                    "fecha_otorgamiento": _fecha(m.group("fecha")),
                    "total_credito": _monto(m.group("total")),
                    "vigente": _monto(m.group("vigente")),
                    "atraso_30_59": _monto(m.group("a1")),
                    "atraso_60_89": _monto(m.group("a2")),
                    "atraso_90_mas": _monto(m.group("a3")),
                }
                (deuda_directa if seccion == "directa" else deuda_indirecta).append(fila)
        elif seccion == "creditos":
            m = FILA_LINEA_CREDITO_RE.match(linea)
            if m:
                lineas_credito.append(
                    {
                        "institucion": m.group("inst").strip(),
                        "directos": _monto(m.group("directos")),
                        "indirectos": _monto(m.group("indirectos")),
                    }
                )

    return {
        "rut": rut,
        "fecha_informe": fecha_informe,
        "fecha_actualizacion": fecha_actualizacion,
        "deuda_total": deuda_total,
        "deuda_directa": deuda_directa,
        "deuda_indirecta": deuda_indirecta,
        "lineas_credito_disponibles": lineas_credito,
    }
