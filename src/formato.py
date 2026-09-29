"""Formato de montos en pesos chilenos (punto como separador de miles, sin decimales)."""


def clp(valor) -> str:
    if valor is None:
        return ""
    try:
        return f"${valor:,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return str(valor)


def usd(valor) -> str:
    """Monto en dolares con 2 decimales y formato chileno (punto de miles, coma decimal)."""
    if valor is None:
        return ""
    try:
        return f"US$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return str(valor)


def monto(valor, moneda: str = "CLP") -> str:
    return usd(valor) if moneda == "USD" else clp(valor)


def clp_md(valor) -> str:
    """Como clp(), pero para texto que se muestra con st.success/warning/info/markdown/error.

    Esos widgets renderizan markdown, y dos signos "$" en el mismo texto se interpretan como
    una formula LaTeX (con "%" adentro leido como comentario) en vez de como plata. Este
    escapa el "$" para que siempre se vea como texto plano.
    """
    return clp(valor).replace("$", "\\$")
