"""Formato de montos en pesos chilenos (punto como separador de miles, sin decimales)."""


def clp(valor) -> str:
    if valor is None:
        return ""
    try:
        return f"${valor:,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return str(valor)
