import pdfplumber
import streamlit as st
import pandas as pd
from pdfminer.pdfdocument import PDFPasswordIncorrect
from pdfplumber.utils.exceptions import PdfminerException

from src.db import get_conn, get_or_create_cuenta, guardar_saldo_snapshot, init_db
from src.parser_cartola import parse_cartola
from src.parser_movimientos import parse_movimientos, es_movimientos
from src.parser_bancoestado import parse_cartola_bancoestado, es_bancoestado_cuentarut
from src.categorias import categorizar, listar_categorias, asegurar_reglas_default
from src.formato import clp

init_db()
asegurar_reglas_default()

st.title("Cargar Cartola / Movimientos")
st.caption(
    "Soporta la cartola oficial mensual de Banco de Chile ('Estado de Cuenta'), el PDF de 'Movimientos al "
    "[fecha]' que puedes descargar en cualquier momento desde tu banca en linea de Banco de Chile, y la "
    "cartola CuentaRUT de BancoEstado. Puedes cargar varios sin miedo a duplicar: si un movimiento ya lo "
    "cargaste, no se repite al cargar otro documento que lo incluya de nuevo."
)

archivo = st.file_uploader("Selecciona el PDF", type="pdf")

if archivo is not None:
    password_key = f"pdf_password_{archivo.name}"
    password = st.session_state.get(password_key, "")

    try:
        with pdfplumber.open(archivo, password=password) as pdf:
            texto_pagina1 = pdf.pages[0].extract_text() or ""
        archivo.seek(0)
    except PdfminerException as e:
        # pdfplumber envuelve el error real de pdfminer dentro de PdfminerException en vez de
        # dejarlo pasar directo, asi que hay que mirar la causa para saber si es de contraseña.
        if not isinstance(e.args[0] if e.args else None, PDFPasswordIncorrect):
            st.error(f"No se pudo leer el PDF. Detalle: {e}")
            st.stop()
        st.warning("Este PDF esta protegido con contraseña (comun en las cartolas CuentaRUT de BancoEstado).")
        password_input = st.text_input("Contraseña del PDF", type="password", key=f"pw_input_{archivo.name}")
        if st.button("Desbloquear"):
            st.session_state[password_key] = password_input
            st.rerun()
        st.stop()

    es_tipo_bancoestado = es_bancoestado_cuentarut(texto_pagina1)
    es_tipo_movimientos = es_movimientos(texto_pagina1) if not es_tipo_bancoestado else False

    try:
        if es_tipo_bancoestado:
            resultado = parse_cartola_bancoestado(archivo, password=password)
        elif es_tipo_movimientos:
            resultado = parse_movimientos(archivo)
        else:
            resultado = parse_cartola(archivo)
    except Exception as e:
        st.error(f"No se pudo leer el PDF. Detalle: {e}")
        st.stop()

    if not resultado["numero_cuenta"] or not resultado["transacciones"]:
        st.error("No se reconocio la estructura de este PDF como un documento soportado.")
        st.stop()

    nombre_cuenta = f"{resultado['banco']} - {resultado['numero_cuenta']}"
    tipo_documento = (
        "Movimientos al dia" if es_tipo_movimientos else "Cartola CuentaRUT" if es_tipo_bancoestado else "Cartola oficial"
    )

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Cuenta", nombre_cuenta)
    col2.metric("Tipo de documento", tipo_documento)
    if es_tipo_movimientos:
        col3.metric("Movimientos al", str(resultado["periodo_hasta"]))
    else:
        col3.metric("Periodo", f"{resultado['periodo_desde']} a {resultado['periodo_hasta']}")
    col4.metric("Saldo final", clp(resultado["saldo_final"]))

    if resultado["cuadratura_ok"] is None:
        st.info(
            "Este documento no trae saldo inicial explicito, asi que no se puede verificar la cuadratura — "
            "cada fila usa el saldo que trae el propio PDF."
        )
    elif resultado["cuadratura_ok"]:
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

        # Fuera del "with" anterior: guardar_saldo_snapshot abre su propia conexion, y hacerlo
        # mientras la conexion de arriba todavia tiene la transaccion abierta puede bloquear
        # SQLite (solo permite un escritor a la vez).
        if resultado["saldo_final"] is not None and resultado["saldo_disponible_fecha"] is not None:
            guardar_saldo_snapshot(
                cuenta_id,
                resultado["saldo_disponible_fecha"].isoformat(),
                resultado["saldo_disponible_hora"],
                resultado["saldo_final"],
            )
        st.success(f"Listo: {nuevas} transacciones nuevas guardadas, {duplicadas} ya existian y se omitieron.")
