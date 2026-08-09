import streamlit as st

from src.db import init_db
from src.categorias import asegurar_reglas_default


def mostrar_inicio():
    st.title("Mis Finanzas Personales")
    st.markdown(
        """
Bienvenido. Esta app es 100% local: los datos se guardan en `data/finanzas.db`
en tu computador, nada se envia a internet.

Usa **Dashboard** para ver tus gastos, ahorros, proyecciones y deuda. Usa **Categorias**
para ajustar como se clasifican tus transacciones. Para cargar datos nuevos (cartola,
informe de deuda CMF, saldo de ahorros), usa el boton "Actualizar datos" que esta arriba
del Dashboard.
"""
    )

    with st.expander("Como funciona la deteccion de duplicados"):
        st.write(
            "Cada transaccion se identifica por cuenta + fecha + descripcion + montos + saldo, no por el "
            "numero de cartola, asi que puedes cargar el PDF de 'Movimientos al dia' para ver tu saldo antes "
            "de que salga la cartola oficial del mes, y despues cargar la cartola oficial sin que se dupliquen "
            "los movimientos que ya cargaste. Los informes CMF se identifican por su fecha de actualizacion."
        )

    st.divider()
    st.subheader("Dato freak sobre plata")
    st.info(
        "**La Regla del 72**: para saber en cuantos años se duplica tu dinero a una tasa fija, divide 72 por "
        "la tasa anual. A un 6% anual, tu plata se duplica en unos 12 años (72 / 6 = 12); a un 12% anual, en 6.\n\n"
        "Al interes compuesto se le atribuye (probablemente de forma apocrifa) la frase de que seria "
        "'la octava maravilla del mundo' — funciona igual de fuerte en tu contra: pagar solo el minimo de una "
        "tarjeta de credito puede significar años pagando una deuda chica por como se acumula el interes "
        "rotativo mes a mes."
    )

    st.subheader("Para aprender mas sobre manejo de plata y tarjetas de credito")
    st.markdown(
        """
- [CMF Educa](https://www.cmfchile.cl/educa/621/w3-propertyvalue-45232.html) — portal oficial de educacion financiera de la Comision para el Mercado Financiero.
- [SERNAC: Endeudamiento](https://www.sernac.cl/portal/607/w3-propertyvalue-21055.html) — guias del Servicio Nacional del Consumidor.
- [SERNAC: Nueve tips para un endeudamiento responsable](https://www.sernac.cl/portal/607/w3-article-3612.html) — consejos concretos sobre tarjetas de credito y creditos de consumo.
"""
    )

    st.divider()
    st.caption(
        "Idea y desarrollo: **Javier Ignacio Rivas Poblete**.\n\n"
        "© 2026 Javier Ignacio Rivas Poblete. Todos los derechos reservados. Aplicacion de uso personal; "
        "su uso, adaptacion o distribucion queda bajo la responsabilidad exclusiva de quien la utilice. "
        "Esto no constituye asesoria financiera profesional: las proyecciones y calculos son estimaciones "
        "simples basadas en los datos y tasas que tu mismo ingresas, no garantias de resultado."
    )


st.set_page_config(page_title="Mis Finanzas", page_icon="\U0001F4B0", layout="wide")

init_db()
asegurar_reglas_default()

pagina_inicio = st.Page(mostrar_inicio, title="Inicio", icon="\U0001F3E0", default=True)
pagina_dashboard = st.Page("vistas/4_Dashboard.py", title="Dashboard", icon="\U0001F4C8")
pagina_categorias = st.Page("vistas/5_Categorias.py", title="Categorias", icon="\U0001F3F7️")
pagina_cartola = st.Page("vistas/1_Cargar_Cartola.py", title="Cargar Cartola", icon="\U0001F4C4", visibility="hidden")
pagina_cmf = st.Page("vistas/2_Cargar_Deuda_CMF.py", title="Cargar Deuda CMF", icon="\U0001F4CA", visibility="hidden")
pagina_ahorro = st.Page("vistas/3_Registrar_Ahorro.py", title="Registrar Ahorro", icon="\U0001F4B5", visibility="hidden")

nav = st.navigation(
    [pagina_inicio, pagina_dashboard, pagina_categorias, pagina_cartola, pagina_cmf, pagina_ahorro]
)
nav.run()
