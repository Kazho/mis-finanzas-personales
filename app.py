import datetime

import streamlit as st

from src.db import init_db
from src.categorias import asegurar_reglas_default
from src.theme import boton_modo, inject_css, colores
from src.actualizador import mostrar_aviso_actualizacion


def mostrar_inicio():
    c = colores()
    st.title("Mis Finanzas Personales")

    # Banner: mismo mensaje central que antes, con el estilo de tarjeta oscura destacada
    # del diseño "Lumina Finance" (hecho en Stitch) que le gusto al usuario.
    st.markdown(
        f'<div style="background:{c["hero_bg"]};border-radius:12px;padding:32px 36px;margin-bottom:24px">'
        f'<div style="font-size:32px;font-weight:600;color:{c["hero_text"]};margin-bottom:8px;letter-spacing:-0.02em">'
        "Tu plata, bajo control.</div>"
        f'<div style="font-size:16px;color:{c["hero_subtext"]};max-width:640px;line-height:1.6">'
        "Administra tus finanzas personales de forma simple y segura — tus datos se guardan en "
        f'<code>data/finanzas.db</code> en tu computador, nunca se suben a ningun servidor. La unica excepcion es '
        "el valor del dolar (Dashboard > Proyeccion), que se consulta a una API publica para no tener que "
        "ingresarlo a mano — esa consulta no envia ningun dato tuyo, solo pide el valor del dia.</div></div>",
        unsafe_allow_html=True,
    )

    # Accesos rapidos (replican la navegacion, pero mas visibles para quien recien llega)
    qc1, qc2 = st.columns(2)
    for col, icono, titulo, subtitulo, destino in (
        (qc1, "\U0001F4C8", "Ir al Dashboard", "Revisa tu resumen financiero mensual.", "vistas/4_Dashboard.py"),
        (qc2, "\U0001F3F7️", "Ver Categorias", "Gestiona y analiza tus gastos por tipo.", "vistas/5_Categorias.py"),
    ):
        with col:
            with st.container(border=True):
                cc1, cc2 = st.columns([1, 5])
                cc1.markdown(
                    f'<div style="width:44px;height:44px;border-radius:50%;background:{c["primary"]}1a;'
                    f'display:flex;align-items:center;justify-content:center;font-size:20px">{icono}</div>',
                    unsafe_allow_html=True,
                )
                with cc2:
                    st.markdown(f"**{titulo}**")
                    st.caption(subtitulo)
                if st.button("Ir →", key=f"quicklink_{destino}", use_container_width=True):
                    st.switch_page(destino)

    DATOS_FREAK = [
        "La Regla del 72: para saber en cuantos años se duplica tu dinero a una tasa fija, divide 72 por la tasa "
        "anual. A un 6% anual, tu plata se duplica en unos 12 años; a un 12% anual, en 6.",
        "Al interes compuesto se le atribuye (probablemente de forma apocrifa) la frase de que seria 'la octava "
        "maravilla del mundo' — funciona igual de fuerte en tu contra: pagar solo el minimo de una tarjeta de "
        "credito puede significar años pagando una deuda chica por como se acumula el interes rotativo mes a mes.",
        "El interes rotativo de una tarjeta de credito en Chile suele rondar 30-50% anual — mucho mas caro que "
        "cualquier ganancia de una cuenta de ahorro remunerada (que suele rondar 4-10% anual). Pagar el total "
        "facturado, no el minimo, es la decision financiera con mejor 'retorno' garantizado que existe.",
        "Una cuenta corriente comun no genera interes: la plata que dejas ahi quieta 'pierde' contra la inflacion "
        "cada mes. Cualquier cuenta remunerada, aunque sea con una tasa modesta, es mejor que dejarla sin generar nada.",
        "La palabra 'salario' viene del latin 'salarium', ligado a la sal que a veces se usaba para pagar a los "
        "soldados romanos — un producto tan valioso que funcionaba como moneda.",
        "El metodo 50/30/20 sugiere destinar 50% del ingreso a necesidades, 30% a gustos y 20% a ahorro/deuda — "
        "una regla simple para ordenar el presupuesto sin llevar cuentas al detalle.",
    ]

    st.write("")
    col_freak, col_recursos = st.columns([1, 2])
    with col_freak:
        with st.container(border=True):
            fh1, fh2 = st.columns([5, 1])
            fh1.markdown(f'<span style="color:{c["success"]}">\U0001F4A1</span> **DATO FREAK SOBRE PLATA**', unsafe_allow_html=True)
            if fh2.button("\U0001F504", key="rotar_dato_freak", help="Ver otro dato"):
                st.session_state.dato_freak_idx = st.session_state.get("dato_freak_idx", 0) + 1
            idx = st.session_state.get("dato_freak_idx", datetime.date.today().toordinal()) % len(DATOS_FREAK)
            st.caption(DATOS_FREAK[idx])
    with col_recursos:
        with st.container(border=True):
            st.markdown("**Recursos de aprendizaje**")
            for icono, titulo, subtitulo, url in (
                ("\U0001F4D6", "CMF Educa", "Portal oficial de educacion financiera de la CMF.", "https://www.cmfchile.cl/educa/621/w3-propertyvalue-45232.html"),
                ("\U0001F4B3", "SERNAC: Endeudamiento", "Guias del Servicio Nacional del Consumidor.", "https://www.sernac.cl/portal/607/w3-propertyvalue-21055.html"),
                ("✅", "Nueve tips para un endeudamiento responsable", "Consejos concretos sobre tarjetas de credito y creditos de consumo.", "https://www.sernac.cl/portal/607/w3-article-3612.html"),
            ):
                rc1, rc2 = st.columns([1, 8])
                rc1.markdown(f'<div style="font-size:22px;padding-top:4px">{icono}</div>', unsafe_allow_html=True)
                with rc2:
                    st.markdown(f"[**{titulo}**]({url})")
                    st.caption(subtitulo)

    with st.expander("Como funciona la deteccion de duplicados"):
        st.write(
            "Cada transaccion se identifica por cuenta + fecha + descripcion + montos + saldo, no por el "
            "numero de cartola, asi que puedes cargar el PDF de 'Movimientos al dia' para ver tu saldo antes "
            "de que salga la cartola oficial del mes, y despues cargar la cartola oficial sin que se dupliquen "
            "los movimientos que ya cargaste. Los informes CMF se identifican por su fecha de actualizacion."
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
boton_modo()
inject_css()
mostrar_aviso_actualizacion()
nav.run()
