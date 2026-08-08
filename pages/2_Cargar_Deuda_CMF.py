import streamlit as st
import pandas as pd

from src.db import get_conn, init_db
from src.parser_cmf import parse_cmf
from src.formato import clp

st.set_page_config(page_title="Cargar Deuda CMF", page_icon="\U0001F4CA", layout="wide")
init_db()

st.title("Cargar Informe de Deudas CMF")
st.caption(
    "Descarga tu informe en [conocetudeuda.cmfchile.cl](https://conocetudeuda.cmfchile.cl/informe-deudas/629/w4-contents.html) "
    "y subelo aqui para llevar un historial de tu endeudamiento."
)

archivo = st.file_uploader("Selecciona el PDF del informe de deudas", type="pdf")

if archivo is not None:
    try:
        r = parse_cmf(archivo)
    except Exception as e:
        st.error(f"No se pudo leer el PDF. Detalle: {e}")
        st.stop()

    if r["deuda_total"] is None or r["fecha_actualizacion"] is None:
        st.error("No se reconocio la estructura de este PDF como informe de deudas CMF.")
        st.stop()

    col1, col2, col3 = st.columns(3)
    col1.metric("Deuda total", clp(r["deuda_total"]))
    col2.metric("Informe emitido", str(r["fecha_informe"]))
    col3.metric("Informacion actualizada al", str(r["fecha_actualizacion"]))

    montos_deuda = ["total_credito", "vigente", "atraso_30_59", "atraso_60_89", "atraso_90_mas"]
    if r["deuda_directa"]:
        st.subheader("Deuda directa")
        df_dd = pd.DataFrame(r["deuda_directa"])
        for col in montos_deuda:
            df_dd[col] = df_dd[col].apply(clp)
        st.dataframe(df_dd, hide_index=True, use_container_width=True)
    if r["deuda_indirecta"]:
        st.subheader("Deuda indirecta")
        df_di = pd.DataFrame(r["deuda_indirecta"])
        for col in montos_deuda:
            df_di[col] = df_di[col].apply(clp)
        st.dataframe(df_di, hide_index=True, use_container_width=True)
    if r["lineas_credito_disponibles"]:
        st.subheader("Lineas de credito disponibles")
        df_lc = pd.DataFrame(r["lineas_credito_disponibles"])
        for col in ("directos", "indirectos"):
            df_lc[col] = df_lc[col].apply(clp)
        st.dataframe(df_lc, hide_index=True, use_container_width=True)

    with get_conn() as conn:
        existe = conn.execute(
            "SELECT id FROM deuda_cmf_informes WHERE fecha_actualizacion = ?",
            (r["fecha_actualizacion"].isoformat(),),
        ).fetchone()

    if existe:
        st.info("Ya existe un informe guardado con esta misma fecha de actualizacion. Guardar de nuevo reemplazara ese registro.")

    if st.button("Guardar en la base de datos", type="primary"):
        with get_conn() as conn:
            if existe:
                informe_id = existe["id"]
                conn.execute("DELETE FROM deuda_cmf_detalle WHERE informe_id = ?", (informe_id,))
                conn.execute("DELETE FROM creditos_disponibles WHERE informe_id = ?", (informe_id,))
                conn.execute(
                    "UPDATE deuda_cmf_informes SET fecha_informe = ?, deuda_total = ?, archivo_origen = ? WHERE id = ?",
                    (r["fecha_informe"].isoformat(), r["deuda_total"], archivo.name, informe_id),
                )
            else:
                cur = conn.execute(
                    """
                    INSERT INTO deuda_cmf_informes (fecha_informe, fecha_actualizacion, deuda_total, archivo_origen)
                    VALUES (?, ?, ?, ?)
                    """,
                    (r["fecha_informe"].isoformat(), r["fecha_actualizacion"].isoformat(), r["deuda_total"], archivo.name),
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

        st.success("Informe de deuda CMF guardado correctamente.")
