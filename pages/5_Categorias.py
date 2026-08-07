import streamlit as st
import pandas as pd

from src.db import init_db
from src.categorias import (
    listar_reglas,
    agregar_regla,
    eliminar_regla,
    recategorizar_todas,
    listar_categorias,
    listar_transacciones_sin_categoria,
    actualizar_categoria_transaccion,
    SIN_CATEGORIA,
)
from src.formato import clp

st.set_page_config(page_title="Reglas de Categorizacion", page_icon="\U0001F3F7️", layout="wide")
init_db()

st.title("Reglas de Categorizacion")

st.subheader("Transacciones sin categorizar")
sin_categoria = listar_transacciones_sin_categoria()
if not sin_categoria:
    st.success("No tienes transacciones sin categorizar.")
else:
    st.caption(
        f"Tienes {len(sin_categoria)} transacciones sin categoria. Elige una categoria en la columna de la "
        "derecha y presiona 'Guardar categorias'. Si quieres que las futuras transacciones parecidas se "
        "categoricen solas, agrega ademas una regla mas abajo."
    )
    df_sin_cat = pd.DataFrame(sin_categoria)
    df_sin_cat["monto_cargo"] = df_sin_cat["monto_cargo"].apply(clp)
    df_sin_cat["monto_abono"] = df_sin_cat["monto_abono"].apply(clp)
    df_sin_cat["categoria"] = SIN_CATEGORIA

    editado_sin_cat = st.data_editor(
        df_sin_cat,
        hide_index=True,
        use_container_width=True,
        disabled=["id", "fecha", "descripcion", "sucursal", "monto_cargo", "monto_abono", "cuenta"],
        column_config={
            "id": None,
            "monto_cargo": "cargo",
            "monto_abono": "abono",
            "categoria": st.column_config.SelectboxColumn("categoria", options=listar_categorias()),
        },
        key="editor_sin_categoria",
    )

    if st.button("Guardar categorias", type="primary"):
        cambios = 0
        for _, fila in editado_sin_cat.iterrows():
            if fila["categoria"] != SIN_CATEGORIA:
                actualizar_categoria_transaccion(int(fila["id"]), fila["categoria"])
                cambios += 1
        if cambios:
            st.success(f"Se categorizaron {cambios} transacciones.")
            st.rerun()
        else:
            st.warning("No cambiaste ninguna categoria.")

st.divider()
st.subheader("Reglas de categorizacion automatica")
st.caption(
    "Cuando una transaccion contiene la palabra clave (busqueda simple, sin distinguir mayusculas), "
    "se le asigna la categoria indicada. Por ejemplo, si tus transferencias a la Cuenta RUT familiar "
    "siempre dicen 'TRASPASO A:Marianela Poblete', puedes crear la regla 'MARIANELA POBLETE' -> "
    "'Gastos familia' para que se categoricen solas la proxima vez."
)

# No se usa st.form: dentro de un form los widgets no se refrescan hasta enviar,
# asi que el campo de texto que aparece al elegir "+ Nueva categoria" no llegaba a mostrarse
# (mismo problema que hubo antes en Registrar_Ahorro). Se usa un "form_id" para limpiar
# los campos despues de guardar, igual que alla.
if "categoria_form_id" not in st.session_state:
    st.session_state.categoria_form_id = 0
fid = st.session_state.categoria_form_id

col1, col2 = st.columns(2)
palabra = col1.text_input("Palabra clave (parte del texto de la transaccion)", key=f"palabra_{fid}")
categoria = col2.selectbox("Categoria", listar_categorias()[:-1] + ["+ Nueva categoria"], key=f"categoria_sel_{fid}")
nueva_categoria = ""
if categoria == "+ Nueva categoria":
    nueva_categoria = st.text_input("Nombre de la nueva categoria", key=f"nueva_categoria_{fid}")

if st.button("Agregar regla", type="primary"):
    categoria_final = nueva_categoria.strip() if categoria == "+ Nueva categoria" else categoria
    if not palabra.strip() or not categoria_final:
        st.error("Debes indicar la palabra clave y la categoria.")
    else:
        agregar_regla(palabra, categoria_final)
        st.success(f"Regla guardada: '{palabra.strip().upper()}' -> {categoria_final}")
        st.session_state.categoria_form_id += 1
        st.rerun()

st.subheader("Reglas actuales")
reglas = listar_reglas()
if not reglas:
    st.info("Aun no hay reglas configuradas.")
else:
    df = pd.DataFrame(reglas)
    st.dataframe(df[["palabra_clave", "categoria"]], hide_index=True, use_container_width=True)

    with st.expander("Eliminar una regla"):
        opciones = {f"{r['palabra_clave']} -> {r['categoria']}": r["id"] for r in reglas}
        elegido = st.selectbox("Selecciona la regla a eliminar", list(opciones.keys()))
        if st.button("Eliminar regla", type="secondary"):
            eliminar_regla(opciones[elegido])
            st.success("Regla eliminada.")
            st.rerun()

st.divider()
st.subheader("Recategorizar transacciones ya guardadas")
st.caption(
    "Las reglas nuevas solo se aplican automaticamente a lo que cargues de aqui en adelante. "
    "Si quieres que tambien corrijan transacciones que ya importaste, usa este boton."
)
if st.button("Recategorizar todas las transacciones existentes"):
    cambios = recategorizar_todas()
    st.success(f"Listo: se actualizo la categoria de {cambios} transacciones.")
