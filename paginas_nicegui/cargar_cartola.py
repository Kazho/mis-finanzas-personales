"""Cargar Cartola / Movimientos -- version NiceGUI de vistas/1_Cargar_Cartola.py (Streamlit).

El flujo con reintento de contraseña (para las cartolas CuentaRUT de BancoEstado, que vienen
protegidas) es el motivo por el que esta vista usa @ui.refreshable en vez de simplemente pintar todo
una vez: en Streamlit ese reintento se hacia guardando la contraseña en session_state y forzando un
st.rerun(); aca los bytes del PDF ya subido quedan en memoria (`estado`) y solo se vuelve a pintar la
seccion de procesamiento, sin re-subir el archivo ni recargar la pagina."""
import io

import pandas as pd
import pdfplumber
from nicegui import ui
from pdfminer.pdfdocument import PDFPasswordIncorrect
from pdfplumber.utils.exceptions import PdfminerException

from src.categorias import categorizar, listar_categorias
from src.db import buscar_banco_por_numero
from src.fuentes.archivo import lote_desde_resultado
from src.ingesta import guardar_lote
from src.formato import monto
from src.parser_bancoestado import es_bancoestado_cuentarut, parse_cartola_bancoestado
from src.parser_cartola import parse_cartola
from src.parser_movimientos import es_movimientos, parse_movimientos
from src.parser_tarjeta_credito import es_tarjeta_credito, parse_tarjeta_credito
from src.parser_tarjeta_movimientos import (
    es_tarjeta_no_facturada, es_tarjeta_xls, parse_tarjeta_facturado_xls, parse_tarjeta_no_facturada,
)
from src.ui_nicegui.components import banner, kpi_cards, texto_muted
from src.ui_nicegui.editable_table import editable_table
from src.ui_nicegui.layout import layout
from src.ui_nicegui.theme import colores

BANCOS = ["Banco de Chile", "BancoEstado", "Santander", "BCI", "Scotiabank", "Itau", "Banco Falabella", "Banco Security"]


@ui.page("/cargar-cartola")
def pagina_cargar_cartola():
    with layout("/cargar-cartola"):
        c = colores()
        ui.label("Cargar Cartola / Movimientos").classes("text-2xl font-bold")
        texto_muted(
            "Soporta la cartola oficial mensual de Banco de Chile ('Estado de Cuenta'), el PDF de "
            "'Movimientos al [fecha]' que puedes descargar en cualquier momento desde tu banca en linea de "
            "Banco de Chile, la cartola CuentaRUT de BancoEstado y el estado de cuenta de tarjeta de credito Santander. "
            "Para tarjetas Visa Infinite y similares: el Excel (.xls) de movimientos facturados y el PDF de "
            "'Saldo y Movimientos No Facturados', en pesos y en dolares. Puedes cargar varios sin miedo a "
            "duplicar: si un movimiento ya lo cargaste, no se repite al cargar otro documento que lo "
            "incluya de nuevo."
        )

        estado = {"contenido": None, "nombre": None, "password": ""}

        def _leer_documento():
            """Detecta el tipo de documento y lo parsea. Devuelve (resultado, tipo_documento, clase) o None si
            ya mostro un mensaje (contraseña pendiente, error de lectura o formato no reconocido)."""
            contenido = estado["contenido"]
            if estado["nombre"].lower().endswith(".xls"):
                try:
                    if not es_tarjeta_xls(contenido):
                        banner("error", "No se reconocio este Excel. Por ahora se soporta el Excel de movimientos facturados de tarjeta de credito.")
                        return None
                    return parse_tarjeta_facturado_xls(contenido), "Tarjeta de credito (facturado)", "tarjeta"
                except Exception as e:
                    banner("error", f"No se pudo leer el Excel. Detalle: {e}")
                    return None

            try:
                with pdfplumber.open(io.BytesIO(contenido), password=estado["password"]) as pdf:
                    texto_pagina1 = pdf.pages[0].extract_text() or ""
            except PdfminerException as e:
                if not isinstance(e.args[0] if e.args else None, PDFPasswordIncorrect):
                    banner("error", f"No se pudo leer el PDF. Detalle: {e}")
                    return None
                banner("warning", "Este PDF esta protegido con contraseña (comun en las cartolas CuentaRUT de BancoEstado y en los estados de cuenta de tarjeta).")
                pw_input = ui.input("Contraseña del PDF", password=True, password_toggle_button=True)

                def _desbloquear():
                    estado["password"] = pw_input.value or ""
                    _procesar.refresh()

                ui.button("Desbloquear", on_click=_desbloquear).props("color=primary")
                return None

            archivo, pw = io.BytesIO(contenido), estado["password"]
            try:
                if es_tarjeta_credito(texto_pagina1):
                    return parse_tarjeta_credito(archivo, password=pw), "Estado de cuenta tarjeta de credito", "tarjeta"
                if es_tarjeta_no_facturada(texto_pagina1):
                    return parse_tarjeta_no_facturada(archivo, password=pw), "Tarjeta de credito (por facturar)", "tarjeta"
                if es_bancoestado_cuentarut(texto_pagina1):
                    return parse_cartola_bancoestado(archivo, password=pw), "Cartola CuentaRUT", "cuenta"
                if es_movimientos(texto_pagina1):
                    return parse_movimientos(archivo), "Movimientos al dia", "movimientos"
                return parse_cartola(archivo), "Cartola oficial", "cuenta"
            except Exception as e:
                banner("error", f"No se pudo leer el PDF. Detalle: {e}")
                return None

        @ui.refreshable
        def _procesar():
            if estado["contenido"] is None:
                return
            leido = _leer_documento()
            if leido is None:
                return
            resultado, tipo_documento, clase = leido
            es_tarjeta = clase == "tarjeta"
            es_tipo_movimientos = clase == "movimientos"
            moneda = resultado.get("moneda", "CLP")
            por_facturar = resultado.get("estado") == "por_facturar"

            if not resultado["numero_cuenta"] or not resultado["transacciones"]:
                banner("error", "No se reconocio la estructura de este documento como uno soportado.")
                return

            # Algunos documentos (tarjetas) no dicen de que banco son: se reutiliza el de una cuenta ya creada
            # con ese numero de tarjeta, y si es la primera vez se le pregunta al usuario.
            banco_conocido = resultado["banco"] or buscar_banco_por_numero(resultado["numero_cuenta"])
            selector_banco = None
            if not banco_conocido:
                banner("info", f"Este documento no indica de que banco es la tarjeta {resultado['numero_cuenta']}. Elige el banco para continuar; la proxima vez se recuerda.")
                selector_banco = ui.select(
                    BANCOS, label="Banco", with_input=True, new_value_mode="add-unique",
                ).classes("w-72")

            sufijo = resultado.get("sufijo_cuenta", "")

            def _nombre_cuenta():
                banco = banco_conocido or (selector_banco.value if selector_banco else None) or "Banco sin indicar"
                return f"{banco} - {resultado['numero_cuenta']}{sufijo}"

            if por_facturar or es_tipo_movimientos:
                periodo = f"Al {resultado['periodo_hasta']}"
            elif resultado["periodo_desde"]:
                periodo = f"{resultado['periodo_desde']} a {resultado['periodo_hasta']}"
            else:
                periodo = f"Corte {resultado['periodo_hasta']}"

            nombre_visible_cuenta = _nombre_cuenta() if banco_conocido else f"Tarjeta {resultado['numero_cuenta']}{sufijo}"
            kpi_cards([
                ("Cuenta", nombre_visible_cuenta, c["accent_blue"], "\U0001F3E6"),
                ("Tipo de documento", tipo_documento, c["accent_blue"], "\U0001F4C4"),
                ("Fecha" if por_facturar or es_tipo_movimientos else "Periodo", periodo, c["accent_blue"], "\U0001F4C5"),
                (resultado.get("etiqueta_saldo", "Saldo final"), monto(resultado["saldo_final"], moneda), c["accent_blue"], "\U0001F4B0"),
            ])

            if por_facturar:
                banner(
                    "info",
                    "Estos movimientos son **provisionales**: ocurrieron despues del ultimo corte y todavia no estan en un "
                    "estado de cuenta. Cuando cargues el estado de cuenta facturado siguiente se reemplazan solos, sin duplicarse.",
                )
            elif resultado["cuadratura_ok"] is None:
                banner("info", "Este documento no trae saldo inicial explicito, asi que no se puede verificar la cuadratura — cada fila usa el saldo que trae el propio documento.")
            elif resultado["cuadratura_ok"] and es_tarjeta:
                banner("success", "Cuadratura correcta: la suma de compras y cuotas coincide con el total facturado del documento.")
            elif resultado["cuadratura_ok"]:
                banner("success", "Cuadratura correcta: saldo inicial + movimientos = saldo final.")
            else:
                banner("warning", "La cuadratura no calzo exactamente. Revisa igual las transacciones antes de guardar; puede deberse a un formato de cartola no contemplado.")

            df = pd.DataFrame(resultado["transacciones"])
            df["categoria"] = df["descripcion"].apply(categorizar)

            ui.label("Transacciones detectadas").classes("text-lg font-bold")
            texto_muted("Puedes corregir la categoria antes de guardar. Los cargos son gastos/salidas, los abonos son ingresos/entradas.")

            filas_editor = [
                {
                    "fecha": str(row["fecha"]), "descripcion": row["descripcion"], "sucursal": row["sucursal"] or "",
                    "monto_cargo": monto(row["monto_cargo"], moneda), "monto_abono": monto(row["monto_abono"], moneda),
                    "saldo": monto(row["saldo"], moneda), "categoria": row["categoria"],
                }
                for _, row in df.iterrows()
            ]

            def _guardar(_originales, editados):
                banco = banco_conocido or (selector_banco.value if selector_banco else None)
                if not banco:
                    ui.notify("Elige el banco de la tarjeta antes de guardar.", type="warning")
                    return
                lote = lote_desde_resultado(resultado, estado["nombre"], banco=banco)
                categorias = [e["categoria"] for e in editados]
                manuales = [int(cat != categorizar(t["descripcion"])) for cat, t in zip(categorias, resultado["transacciones"])]
                try:
                    r = guardar_lote(lote, categorias=categorias, manuales=manuales, banco=banco)
                except ValueError as e:
                    ui.notify(f"No se guardo nada: {e}", type="negative")
                    return
                ui.notify(f"Listo: {r.nuevas} transacciones nuevas guardadas, {r.duplicadas} ya existian y se omitieron.", type="positive")

            editable_table(
                filas_editor,
                [
                    {"campo": "fecha", "titulo": "Fecha", "tipo": "solo_lectura"},
                    {"campo": "descripcion", "titulo": "Descripcion", "tipo": "solo_lectura"},
                    {"campo": "sucursal", "titulo": "Sucursal", "tipo": "solo_lectura"},
                    {"campo": "monto_cargo", "titulo": "Cargo", "tipo": "solo_lectura"},
                    {"campo": "monto_abono", "titulo": "Abono", "tipo": "solo_lectura"},
                    {"campo": "saldo", "titulo": "Saldo", "tipo": "solo_lectura"},
                    {"campo": "categoria", "titulo": "Categoria", "tipo": "select", "opciones": listar_categorias()},
                ],
                _guardar,
                texto_boton="Guardar en la base de datos",
            )

        async def _al_subir(e):
            estado["contenido"] = await e.file.read()
            estado["nombre"] = e.file.name
            estado["password"] = ""
            _procesar.refresh()

        ui.upload(on_upload=_al_subir, auto_upload=True, label="Selecciona el PDF o Excel (.xls)").props('accept=".pdf,.xls"').classes("w-full")
        _procesar()
