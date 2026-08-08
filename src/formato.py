"""Formato de montos en pesos chilenos (punto como separador de miles, sin decimales)."""


def clp(valor) -> str:
    if valor is None:
        return ""
    try:
        return f"${valor:,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return str(valor)


def clp_md(valor) -> str:
    """Como clp(), pero para texto que se muestra con st.success/warning/info/markdown/error.

    Esos widgets renderizan markdown, y dos signos "$" en el mismo texto se interpretan como
    una formula LaTeX (con "%" adentro leido como comentario) en vez de como plata. Este
    escapa el "$" para que siempre se vea como texto plano.
    """
    return clp(valor).replace("$", "\\$")
