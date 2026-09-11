"""Cargar Informe de Deudas CMF -- version NiceGUI de vistas/2_Cargar_Deuda_CMF.py (Streamlit)."""
import io

import pandas as pd
from nicegui import ui

from src.db import get_conn
from src.formato import clp
from src.parser_cmf import parse_cmf
from src.ui_nicegui.components import banner, kpi_cards, tabla, texto_muted
from src.ui_nicegui.layout import layout
from src.ui_nicegui.theme import colores

MONTOS_DEUDA = ["total_credito", "vigente", "atraso_30_59", "atraso_60_89", "atraso_90_mas"]
ALIAS_DEUDA = {
    "institucion": "Institucion", "tipo_credito": "Tipo de credito", "fecha_otorgamiento": "Otorgado",
    "total_credito": "Total credito", "vigente": "Vigente", "atraso_30_59": "Atraso 30-59",
    "atraso_60_89": "Atraso 60-89", "atraso_90_mas": "Atraso 90+",
}


@ui.page("/cargar-deuda-cmf")
def pagina_cargar_deuda_cmf():
    with layout("/cargar-deuda-cmf"):
        c = colores()
        ui.label("Cargar Informe de Deudas CMF").classes("text-2xl font-bold")
        with ui.row().classes("items-baseline gap-1"):
            ui.label("Descarga tu informe en")
            ui.link("conocetudeuda.cmfchile.cl", "https://conocetudeuda.cmfchile.cl/informe-deudas/629/w4-contents.html", new_tab=True)
            ui.label("y subelo aqui para llevar un historial de tu endeudamiento.")

        resultado_col = ui.column().classes("w-full gap-3")

        async def _al_subir(e):
            contenido = await e.file.read()
            nombre = e.file.name
            resultado_col.clear()
            with resultado_col:
                try:
                    r = parse_cmf(io.BytesIO(contenido))
                except Exception as ex:
                    banner("error", f"No se pudo leer el PDF. Detalle: {ex}")
                    return

                if r["deuda_total"] is None or r["fecha_actualizacion"] is None:
                    banner("error", "No se reconocio la estructura de este PDF como informe de deudas CMF.")
                    return

                kpi_cards([
                    ("Deuda total", clp(r["deuda_total"]), c["danger"], "\U0001F4B3"),
                    ("Informe emitido", str(r["fecha_informe"]), c["accent_blue"], "\U0001F4C4"),
                    ("Informacion actualizada al", str(r["fecha_actualizacion"]), c["accent_blue"], "\U0001F550"),
                ])

                if r["deuda_directa"]:
                    ui.label("Deuda directa").classes("text-lg font-bold")
                    df_dd = pd.DataFrame(r["deuda_directa"])
                    for col in MONTOS_DEUDA:
                        df_dd[col] = df_dd[col].apply(clp)
                    tabla(df_dd, ALIAS_DEUDA)
                if r["deuda_indirecta"]:
                    ui.label("Deuda indirecta").classes("text-lg font-bold")
                    df_di = pd.DataFrame(r["deuda_indirecta"])
                    for col in MONTOS_DEUDA:
                        df_di[col] = df_di[col].apply(clp)
                    tabla(df_di, ALIAS_DEUDA)
                if r["lineas_credito_disponibles"]:
                    ui.label("Lineas de credito disponibles").classes("text-lg font-bold")
                    df_lc = pd.DataFrame(r["lineas_credito_disponibles"])
                    for col in ("directos", "indirectos"):
                        df_lc[col] = df_lc[col].apply(clp)
                    tabla(df_lc, {"institucion": "Institucion", "directos": "Directos", "indirectos": "Indirectos"})

                with get_conn() as conn:
                    existe = conn.execute(
                        "SELECT id FROM deuda_cmf_informes WHERE fecha_actualizacion = ?",
                        (r["fecha_actualizacion"].isoformat(),),
                    ).fetchone()
                if existe:
                    banner("info", "Ya existe un informe guardado con esta misma fecha de actualizacion. Guardar de nuevo reemplazara ese registro.")

                def _guardar():
                    with get_conn() as conn:
                        if existe:
                            informe_id = existe["id"]
                            conn.execute("DELETE FROM deuda_cmf_detalle WHERE informe_id = ?", (informe_id,))
                            conn.execute("DELETE FROM creditos_disponibles WHERE informe_id = ?", (informe_id,))
                            conn.execute(
                                "UPDATE deuda_cmf_informes SET fecha_informe = ?, deuda_total = ?, archivo_origen = ? WHERE id = ?",
                                (r["fecha_informe"].isoformat(), r["deuda_total"], nombre, informe_id),
                            )
                        else:
                            cur = conn.execute(
                                """
                                INSERT INTO deuda_cmf_informes (fecha_informe, fecha_actualizacion, deuda_total, archivo_origen)
                                VALUES (?, ?, ?, ?)
                                """,
                                (r["fecha_informe"].isoformat(), r["fecha_actualizacion"].isoformat(), r["deuda_total"], nombre),
                            )
                            informe_id = cur.lastrowid

                        for tipo, filas in (("directa", r["deuda_directa"]), ("indirecta", r["deuda_indirecta"])):
                            for f in filas:
                                conn.execute(
                                    """
                                    INSERT INTO deuda_cmf_detalle
                                        (informe_id, tipo, institucion, tipo_credito, fecha_otorgamiento,
                                         total_credito, vigente, atraso_30_59, atraso_60_89, atraso_90_mas)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                    """,
                                    (
                                        informe_id, tipo, f["institucion"], f["tipo_credito"],
                                        f["fecha_otorgamiento"].isoformat(), f["total_credito"], f["vigente"],
                                        f["atraso_30_59"], f["atraso_60_89"], f["atraso_90_mas"],
                                    ),
                                )
                        for f in r["lineas_credito_disponibles"]:
                            conn.execute(
                                "INSERT INTO creditos_disponibles (informe_id, tipo, institucion, directos, indirectos) VALUES (?, ?, ?, ?, ?)",
                                (informe_id, "linea_credito", f["institucion"], f["directos"], f["indirectos"]),
                            )
                    ui.notify("Informe de deuda CMF guardado correctamente.", type="positive")

                ui.button("Guardar en la base de datos", on_click=_guardar).props("color=primary")

        ui.upload(on_upload=_al_subir, auto_upload=True, label="Selecciona el PDF del informe de deudas").props('accept=".pdf"').classes("w-full")
