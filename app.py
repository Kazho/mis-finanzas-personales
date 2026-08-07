import streamlit as st

from src.db import init_db
from src.categorias import asegurar_reglas_default

st.set_page_config(page_title="Mis Finanzas", page_icon="\U0001F4B0", layout="wide")

init_db()
asegurar_reglas_default()

st.title("Mis Finanzas Personales")
st.markdown(
    """
Bienvenido. Esta app es 100% local: los datos se guardan en `data/finanzas.db`
en tu computador, nada se envia a internet.

Usa el menu de la izquierda para:

- **Cargar Cartola**: subir el PDF de tu cartola de cuenta corriente para registrar tus gastos e ingresos.
- **Cargar Deuda CMF**: subir el informe de deudas de la CMF para llevar un historial de tu endeudamiento.
- **Registrar Ahorro**: anotar manualmente el saldo de tus cuentas de ahorro/inversion (Tenpo, Mach, etc).
- **Dashboard**: ver graficos de en que gastas tu dinero, como evolucionan tus ahorros y tu deuda.
"""
)

with st.expander("Como funciona la deteccion de duplicados"):
    st.write(
        "Cada transaccion de cartola se identifica por cuenta + cartola + fecha + descripcion + monto, "
        "asi que puedes volver a subir el mismo PDF sin generar filas repetidas. "
        "Los informes CMF se identifican por RUT + fecha del informe."
    )
