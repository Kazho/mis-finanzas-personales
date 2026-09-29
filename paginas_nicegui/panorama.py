"""Panorama -- todas tus cuentas de todos los bancos en una sola vista.

Separa lo que es plata disponible (corriente, vista, ahorro), inversion y DEUDA de tarjetas de credito,
para que el patrimonio neto no mezcle lo que tienes con lo que debes. Las cuentas en USD se muestran en
dolares y con un equivalente aproximado en pesos (cada banco aplica su propio tipo de cambio)."""
import datetime

import pandas as pd
from nicegui import ui

from src.cuentas import TIPOS, deuda_tarjeta, listar_cuentas, nombre_visible, resumen_panorama
from src.formato import clp, monto, usd
from src.fx_core import obtener_valor_dolar_sin_cache
from src.ui_nicegui.cache import cache_ttl
from src.ui_nicegui.components import banner, kpi_cards, tabla, tarjeta, texto_muted
from src.ui_nicegui.layout import layout
from src.ui_nicegui.theme import colores

DIAS_AVISO_VENCIMIENTO = 7


def _fecha(texto: str | None) -> str:
    if not texto:
        return "—"
    return datetime.date.fromisoformat(texto[:10]).strftime("%d/%m/%Y")


def _fila_cuenta(c: dict, dolar: float | None) -> dict:
    moneda = c.get("moneda") or "CLP"
    es_tc = c["tipo"] == "tarjeta"
    valor = deuda_tarjeta(c) if es_tc else c.get("saldo")
    equivalente = ""
    if valor is not None and moneda == "USD" and dolar:
        equivalente = "≈ " + clp(valor * dolar)
    fecha = c["tc"]["periodo_hasta"] if es_tc and c.get("tc") else c.get("saldo_fecha")
    if valor is None:
        texto_monto = "sin datos"
    else:
        texto_monto = ("Deuda " if es_tc else "") + monto(valor, moneda)
    return {
        "Cuenta": nombre_visible(c),
        "Tipo": TIPOS.get(c["tipo"], c["tipo"]),
        "Moneda": moneda,
        "Saldo": texto_monto,
        "En pesos": equivalente,
        "Al": _fecha(fecha),
    }


def _seccion_tarjetas(cuentas: list[dict]):
    tarjetas = [c for c in cuentas if c["tipo"] == "tarjeta" and not c.get("archivada") and c.get("tc")]
    if not tarjetas:
        return
    c_ = colores()
    hoy = datetime.date.today()
    with tarjeta("Tarjetas de credito"):
        texto_muted("Datos del ultimo estado de cuenta cargado de cada tarjeta.")
        for c in tarjetas:
            tc, moneda = c["tc"], c.get("moneda") or "CLP"
            with ui.column().classes("w-full gap-1"):
                ui.label(f"{c.get('banco') or ''} — {nombre_visible(c)}".strip(" —")).classes("font-bold")
                items = []
                if tc.get("cupo_total"):
                    uso = (tc["cupo_utilizado"] or 0) / tc["cupo_total"] * 100
                    items += [
                        ("Cupo utilizado", monto(tc["cupo_utilizado"], moneda), c_["danger"], "\U0001F4B3",
                         f"{uso:.0f}% de {monto(tc['cupo_total'], moneda)}", None),
                        ("Cupo disponible", monto(tc["cupo_disponible"], moneda), c_["success"], "\U0001F7E2"),
                    ]
                items += [
                    ("Facturado a pagar", monto(tc["monto_facturado"], moneda), c_["accent_orange"], "\U0001F9FE",
                     f"Minimo {monto(tc['pago_minimo'], moneda)}" if tc.get("pago_minimo") is not None else None, None),
                    ("Vence", _fecha(tc.get("fecha_vencimiento")), c_["accent_blue"], "\U0001F4C5"),
                ]
                kpi_cards(items)
                if tc.get("fecha_vencimiento"):
                    dias = (datetime.date.fromisoformat(tc["fecha_vencimiento"]) - hoy).days
                    if 0 <= dias <= DIAS_AVISO_VENCIMIENTO:
                        banner("warning", f"**{nombre_visible(c)}** vence en **{dias} dia(s)** ({_fecha(tc['fecha_vencimiento'])}).")
                    elif dias < 0:
                        banner("info", f"El estado de cuenta de **{nombre_visible(c)}** ya vencio ({_fecha(tc['fecha_vencimiento'])}). "
                                       "Carga el del mes siguiente para actualizar estos datos.")


@ui.page("/panorama")
def pagina_panorama():
    with layout("/panorama"):
        c = colores()
        ui.label("Panorama").classes("text-2xl font-bold")
        texto_muted(
            "Todas tus cuentas de todos los bancos en una vista. Lo disponible y lo invertido se separa de la deuda "
            "de tarjetas, para que el patrimonio neto no mezcle lo que tienes con lo que debes. Administra los "
            "tipos y nombres en la pagina Cuentas."
        )

        cuentas = listar_cuentas()
        if not cuentas:
            ui.label("Aun no hay cuentas. Ve a 'Cargar Cartola' para agregar la primera.")
            return

        dolar = cache_ttl("valor_dolar", 3600, obtener_valor_dolar_sin_cache)
        r = resumen_panorama(cuentas, dolar)

        def _con_usd(por_moneda):
            return f"incluye {usd(por_moneda['USD'])} (≈ {clp(por_moneda['USD'] * dolar)})" if por_moneda["USD"] and dolar else (
                f"incluye {usd(por_moneda['USD'])} sin convertir" if por_moneda["USD"] else None)

        kpi_cards([
            ("Disponible", clp(r["disponible_clp"]), c["accent_blue"], "\U0001F4B5", _con_usd(r["disponible"]), None),
            ("Inversiones", clp(r["inversion_clp"]), c["success"], "\U0001F4C8", _con_usd(r["inversion"]), None),
            ("Deuda de tarjetas", clp(r["deuda_clp"]), c["danger"], "\U0001F4B3", _con_usd(r["deuda"]), None),
            ("Patrimonio neto", clp(r["neto_clp"]), c["accent_purple"], "⚖️",
             f"Dolar de referencia: {clp(dolar)}" if dolar else None, None),
        ])
        texto_muted(
            "El patrimonio de esta vista suma solo lo cargado por cartola. Los ahorros y la deuda CMF que registras "
            "aparte se ven en el Dashboard."
        )

        if r["usd_sin_convertir"]:
            banner("info", "No se pudo consultar el dolar: las cuentas en USD se muestran en dolares pero no estan sumadas en pesos.")
        elif dolar and any(v["USD"] for v in (r["disponible"], r["inversion"], r["deuda"])):
            banner("info", f"Las cuentas en USD se convierten al dolar observado (**{clp(dolar)}**). Es un valor aproximado: cada banco aplica su propio tipo de cambio.")
        if r["sin_datos"]:
            nombres = ", ".join(nombre_visible(x) for x in r["sin_datos"])
            banner("warning", f"Sin saldo o deuda conocidos (no suman en los totales): **{nombres}**. Carga una cartola que traiga saldo.")

        _seccion_tarjetas(cuentas)

        ui.label("Por banco").classes("text-lg font-bold")
        if not r["por_banco"]:
            texto_muted("Todas tus cuentas estan archivadas.")
        for banco, datos in sorted(r["por_banco"].items()):
            with tarjeta(banco):
                kpi_cards([
                    ("Disponible", clp(datos["disponible_clp"]), c["accent_blue"], "\U0001F4B5"),
                    ("Inversiones", clp(datos["inversion_clp"]), c["success"], "\U0001F4C8"),
                    ("Deuda", clp(datos["deuda_clp"]), c["danger"], "\U0001F4B3"),
                ])
                tabla(pd.DataFrame([_fila_cuenta(x, dolar) for x in datos["cuentas"]]))
