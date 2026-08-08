import streamlit as st
import pandas as pd

from src.db import get_conn, get_or_create_cuenta, init_db
from src.parser_cartola import parse_cartola
from src.categorias import categorizar, listar_categorias, asegurar_reglas_default
from src.formato import clp

st.set_page_config(page_title="Cargar Cartola", page_icon="\U0001F4C4", layout="wide")
init_db()
asegurar_reglas_default()

st.title("Cargar Cartola de Cuenta Corriente")
st.caption("Formato soportado por ahora: Cuenta Corriente Banco de Chile (PDF 'Estado de Cuenta').")

archivo = st.file_uploader("Selecciona el PDF de la cartola", type="pdf")

if archivo is not None:
    try:
        resultado = parse_cartola(archivo)
    except Exception as e:
        st.error(f"No se pudo leer el PDF. Detalle: {e}")
        st.stop()

    if not resultado["numero_cuenta"] or not resultado["transacciones"]:
        st.error("No se reconocio la estructura de este PDF como cartola Banco de Chile.")
        st.stop()

    nombre_cuenta = f"{resultado['banco']} - {resultado['numero_cuenta']}"

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Cuenta", nombre_cuenta)
    col2.metric("Cartola N°", resultado["cartola_numero"])
    col3.metric("Periodo", f"{resultado['periodo_desde']} a {resultado['periodo_hasta']}")
    col4.metric("Saldo final", clp(resultado["saldo_final"]))

    if resultado["cuadratura_ok"]:
        st.success("Cuadratura correcta: saldo inicial + movimientos = saldo final.")
    else:
        st.warning(
            "La cuadratura no calzo exactamente. Revisa igual las transacciones antes de guardar; "
            "puede deberse a un formato de cartola no contemplado."
        )

    df = pd.DataFrame(resultado["transacciones"])
    df["categoria"] = df["descripcion"].apply(categorizar)
    df = df[["fecha", "descripcion", "sucursal", "monto_cargo", "monto_abono", "saldo", "categoria", "hash_dedupe"]]
    for col in ("monto_cargo", "monto_abono", "saldo"):
        df[col] = df[col].apply(clp)

    st.subheader("Transacciones detectadas")
    st.caption("Puedes corregir la categoria antes de guardar. Los cargos son gastos/salidas, los abonos son ingresos/entradas.")

    editado = st.data_editor(
        df.drop(columns=["hash_dedupe"]),
        column_config={
            "categoria": st.column_config.SelectboxColumn("categoria", options=listar_categorias()),
            "monto_cargo": "cargo",
            "monto_abono": "abono",
            "saldo": "saldo",
        },
        disabled=["fecha", "descripcion", "sucursal", "monto_cargo", "monto_abono", "saldo"],
        hide_index=True,
        use_container_width=True,
    )

    if st.button("Guardar en la base de datos", type="primary"):
        cuenta_id = get_or_create_cuenta(nombre_cuenta, banco=resultado["banco"], numero_cuenta=resultado["numero_cuenta"])
        nuevas, duplicadas = 0, 0
        with get_conn() as conn:
            for i, t in enumerate(resultado["transacciones"]):
                categoria = editado.iloc[i]["categoria"]
                # Si el usuario cambio la categoria sugerida por la regla automatica, se marca
                # como manual para que "Recategorizar transacciones existentes" no la pise despues.
                categoria_manual = int(categoria != categorizar(t["descripcion"]))
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO transacciones
                        (cuenta_id, fecha, descripcion, sucursal, monto_cargo, monto_abono, saldo,
                         categoria, categoria_manual, cartola_numero, archivo_origen, hash_dedupe)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cuenta_id,
                        t["fecha"].isoformat(),
                        t["descripcion"],
                        t["sucursal"],
                        t["monto_cargo"],
                        t["monto_abono"],
                        t["saldo"],
                        categoria,
                        categoria_manual,
                        resultado["cartola_numero"],
                        archivo.name,
                        t["hash_dedupe"],
                    ),
                )
                if cur.rowcount:
                    nuevas += 1
                else:
                    duplicadas += 1
        st.success(f"Listo: {nuevas} transacciones nuevas guardadas, {duplicadas} ya existian y se omitieron.")
