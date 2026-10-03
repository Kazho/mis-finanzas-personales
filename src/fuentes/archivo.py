"""Adaptador de ARCHIVOS: convierte lo que devuelven los parsers de PDF/Excel al contrato de ingesta.

Los parsers (`src/parser_*.py`) siguen devolviendo su diccionario de siempre; este adaptador es el unico lugar
que sabe como traducirlo a un `LoteImportacion`. Asi, cuando exista una fuente por API, se escribe otro
adaptador con la misma salida y nada mas cambia.
"""
import re

from src.fuentes.contrato import (
    MAX_LARGO_TEXTO,
    ESTADO_FACTURADO,
    FUENTE_PDF,
    FUENTE_XLS,
    REEMPLAZA_HASTA_CORTE,
    REEMPLAZA_TODOS,
    CuentaFuente,
    LoteImportacion,
    MovimientoFuente,
    OrigenLote,
    SaldoFuente,
)


_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _texto_limpio(texto, largo: int = MAX_LARGO_TEXTO) -> str:
    """Sin caracteres de control (se cuelan en PDF corruptos) y de largo acotado."""
    return " ".join(_CONTROL.sub(" ", str(texto or "")).split())[:largo]


def lote_desde_resultado(resultado: dict, nombre_archivo: str, banco: str | None = None) -> LoteImportacion:
    """`resultado` es el diccionario de cualquier parser. `banco` pisa al que traiga el documento (se usa cuando
    el documento no lo dice y el usuario lo eligio)."""
    es_xls = nombre_archivo.lower().endswith((".xls", ".xlsx"))
    estado_lote = resultado.get("estado", ESTADO_FACTURADO)

    # Lo pendiente es provisional: una consulta nueva de "por facturar" trae todo lo pendiente (reemplaza todo), y
    # un estado de cuenta facturado de tarjeta ya incluye lo pendiente anterior a su corte.
    if estado_lote == "por_facturar":
        reemplazo = REEMPLAZA_TODOS
    elif resultado.get("es_tarjeta_credito"):
        reemplazo = REEMPLAZA_HASTA_CORTE
    else:
        reemplazo = None

    movimientos = [
        MovimientoFuente(
            fecha=t["fecha"],
            descripcion=_texto_limpio(t["descripcion"]) or "(sin descripcion)",
            monto_cargo=t["monto_cargo"],
            monto_abono=t["monto_abono"],
            saldo=t.get("saldo"),
            sucursal=_texto_limpio(t.get("sucursal")),
            estado=t.get("estado", estado_lote),
            hash_dedupe=t["hash_dedupe"],
        )
        for t in resultado["transacciones"]
    ]

    snapshot = None
    if resultado.get("saldo_final") is not None and resultado.get("saldo_disponible_fecha") is not None:
        snapshot = SaldoFuente(
            fecha=resultado["saldo_disponible_fecha"],
            hora=resultado.get("saldo_disponible_hora"),
            saldo=resultado["saldo_final"],
        )

    return LoteImportacion(
        origen=OrigenLote(tipo=FUENTE_XLS if es_xls else FUENTE_PDF, nombre=nombre_archivo),
        cuenta=CuentaFuente(
            numero=resultado["numero_cuenta"],
            tipo=resultado.get("tipo_cuenta", "corriente"),
            banco=banco or resultado.get("banco"),
            moneda=resultado.get("moneda", "CLP"),
            sufijo_nombre=resultado.get("sufijo_cuenta", ""),
        ),
        movimientos=movimientos,
        periodo_desde=resultado.get("periodo_desde"),
        periodo_hasta=resultado.get("periodo_hasta"),
        cartola_numero=resultado.get("cartola_numero"),
        saldo_inicial=resultado.get("saldo_inicial"),
        saldo_final=resultado.get("saldo_final"),
        cuadratura_ok=resultado.get("cuadratura_ok"),
        etiqueta_saldo=resultado.get("etiqueta_saldo", "Saldo final"),
        estado_tc=resultado.get("estado_tc"),
        saldo_snapshot=snapshot,
        reemplaza_provisionales=reemplazo,
    )
