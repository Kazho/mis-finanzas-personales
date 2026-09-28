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
from src.db import get_conn, get_or_create_cuenta, guardar_saldo_snapshot
from src.formato import clp
from src.parser_bancoestado import es_bancoestado_cuentarut, parse_cartola_bancoestado
from src.parser_cartola import parse_cartola
from src.parser_movimientos import es_movimientos, parse_movimientos
from src.ui_nicegui.components import banner, kpi_cards, texto_muted
from src.ui_nicegui.editable_table import editable_table
from src.ui_nicegui.layout import layout
from src.ui_nicegui.theme import colores


@ui.page("/cargar-cartola")
def pagina_cargar_cartola():
    with layout("/cargar-cartola"):
        c = colores()
        ui.label("Cargar Cartola / Movimientos").classes("text-2xl font-bold")
        texto_muted(
            "Soporta la cartola oficial mensual de Banco de Chile ('Estado de Cuenta'), el PDF de "
            "'Movimientos al [fecha]' que puedes descargar en cualquier momento desde tu banca en linea de "
            "Banco de Chile, y la cartola CuentaRUT de BancoEstado. Puedes cargar varios sin miedo a "
            "duplicar: si un movimiento ya lo cargaste, no se repite al cargar otro documento que lo "
            "incluya de nuevo."
        )

        estado = {"contenido": None, "nombre": None, "password": ""}

        @ui.refreshable
        def _procesar():
            if estado["contenido"] is None:
                return
            try:
                with pdfplumber.open(io.BytesIO(estado["contenido"]), password=estado["password"]) as pdf:
                    texto_pagina1 = pdf.pages[0].extract_text() or ""
            except PdfminerException as e:
                if not isinstance(e.args[0] if e.args else None, PDFPasswordIncorrect):
                    banner("error", f"No se pudo leer el PDF. Detalle: {e}")
                    return
                banner("warning", "Este PDF esta protegido con contraseña (comun en las cartolas CuentaRUT de BancoEstado).")
                pw_input = ui.input("Contraseña del PDF", password=True, password_toggle_button=True)

                def _desbloquear():
                    estado["password"] = pw_input.value or ""
                    _procesar.refresh()

                ui.button("Desbloquear", on_click=_desbloquear).props("color=primary")
                return

            es_tipo_bancoestado = es_bancoestado_cuentarut(texto_pagina1)
            es_tipo_movimientos = es_movimientos(texto_pagina1) if not es_tipo_bancoestado else False

            try:
                if es_tipo_bancoestado:
                    resultado = parse_cartola_bancoestado(io.BytesIO(estado["contenido"]), password=estado["password"])
                elif es_tipo_movimientos:
                    resultado = parse_movimientos(io.BytesIO(estado["contenido"]))
                else:
                    resultado = parse_cartola(io.BytesIO(estado["contenido"]))
            except Exception as e:
                banner("error", f"No se pudo leer el PDF. Detalle: {e}")
                return

            if not resultado["numero_cuenta"] or not resultado["transacciones"]:
                banner("error", "No se reconocio la estructura de este PDF como un documento soportado.")
                return

            nombre_cuenta = f"{resultado['banco']} - {resultado['numero_cuenta']}"
            tipo_documento = (
                "Movimientos al dia" if es_tipo_movimientos
                else "Cartola CuentaRUT" if es_tipo_bancoestado
                else "Cartola oficial"
            )
            periodo = (
                str(resultado["periodo_hasta"]) if es_tipo_movimientos
                else f"{resultado['periodo_desde']} a {resultado['periodo_hasta']}"
            )

            kpi_cards([
                ("Cuenta", nombre_cuenta, c["accent_blue"], "\U0001F3E6"),
                ("Tipo de documento", tipo_documento, c["accent_blue"], "\U0001F4C4"),
                ("Periodo" if not es_tipo_movimientos else "Movimientos al", periodo, c["accent_blue"], "\U0001F4C5"),
                ("Saldo final", clp(resultado["saldo_final"]), c["accent_blue"], "\U0001F4B0"),
            ])

            if resultado["cuadratura_ok"] is None:
                banner("info", "Este documento no trae saldo inicial explicito, asi que no se puede verificar la cuadratura — cada fila usa el saldo que trae el propio PDF.")
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
                    "monto_cargo": clp(row["monto_cargo"]), "monto_abono": clp(row["monto_abono"]), "saldo": clp(row["saldo"]),
                    "categoria": row["categoria"],
                }
                for _, row in df.iterrows()
            ]

            def _guardar(_originales, editados):
                cuenta_id = get_or_create_cuenta(nombre_cuenta, banco=resultado["banco"], numero_cuenta=resultado["numero_cuenta"])
                nuevas, duplicadas = 0, 0
                with get_conn() as conn:
                    for i, t in enumerate(resultado["transacciones"]):
                        categoria = editados[i]["categoria"]
                        categoria_manual = int(categoria != categorizar(t["descripcion"]))
                        cur = conn.execute(
                            """
                            INSERT OR IGNORE INTO transacciones
                                (cuenta_id, fecha, descripcion, sucursal, monto_cargo, monto_abono, saldo,
                                 categoria, categoria_manual, cartola_numero, archivo_origen, hash_dedupe)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                cuenta_id, t["fecha"].isoformat(), t["descripcion"], t["sucursal"],
                                t["monto_cargo"], t["monto_abono"], t["saldo"], categoria, categoria_manual,
                                resultado["cartola_numero"], estado["nombre"], t["hash_dedupe"],
                            ),
                        )
                        if cur.rowcount:
                            nuevas += 1
                        else:
                            duplicadas += 1

                if resultado["saldo_final"] is not None and resultado["saldo_disponible_fecha"] is not None:
                    guardar_saldo_snapshot(
                        cuenta_id, resultado["saldo_disponible_fecha"].isoformat(),
                        resultado["saldo_disponible_hora"], resultado["saldo_final"],
                    )
                ui.notify(f"Listo: {nuevas} transacciones nuevas guardadas, {duplicadas} ya existian y se omitieron.", type="positive")

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

        ui.upload(on_upload=_al_subir, auto_upload=True, label="Selecciona el PDF").props('accept=".pdf"').classes("w-full")
        _procesar()
