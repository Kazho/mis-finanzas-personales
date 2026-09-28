"""Tabla editable generica para NiceGUI -- reemplazo del patron mas repetido de la version Streamlit
(st.data_editor + comparar fila a fila contra el DataFrame original + st.rerun al guardar), usado en
~8 lugares distintos (Categorias x5, Registrar Ahorro x2, Dashboard x1, Cargar Cartola x1).

Se construye sobre ui.aggrid (AG Grid), que trae edicion de celdas nativa. La pieza clave es
`get_client_data()`, que lee de vuelta lo que el usuario edito en el grid (AG Grid no sincroniza los
cambios al `rowData` de Python solo; hay que pedirlo explicitamente al guardar).

Nota de implementacion: esta primera version se valida de verdad recien en las vistas que la usan
(Cargar Cartola, Registrar Ahorro, Categorias -- fases siguientes del plan de migracion), que son las
que ejercitan cada tipo de columna con datos e interacciones reales. Si algun tipo de celda necesita
ajuste al usarlo, se corrige aca (un solo lugar) en vez de en cada vista.
"""
import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from nicegui import ui

TipoColumna = str  # "texto" | "numero" | "select" | "checkbox" | "solo_lectura"

MAX_FILAS_AUTO_ALTO = 12
ALTO_TABLA_LARGA = "480px"


def editable_table(
    filas: list[dict[str, Any]],
    columnas: list[dict[str, Any]],
    on_guardar: Callable[[list[dict], list[dict]], Any],
    *,
    texto_boton: str = "Guardar",
) -> ui.aggrid:
    """Pinta una tabla editable y un boton de guardar.

    `columnas`: lista de specs por columna, cada una un dict con:
      - "campo": nombre de la columna en las filas (obligatorio)
      - "titulo": encabezado visible (por defecto, el campo)
      - "tipo": "texto" (por defecto) | "numero" | "select" | "checkbox" | "solo_lectura"
      - "opciones": lista de valores validos, solo para tipo "select"
      - "ancho": peso relativo de la columna (flex de AG Grid, por defecto 1)

    `on_guardar(originales, editados)` se llama al presionar el boton (puede ser sync o async) con
    dos listas de dicts: las filas como estaban antes de mostrarse, y las filas ya editadas por el
    usuario -- quien llama decide que comparar/guardar, esta funcion no toca la base de datos.
    """
    originales = [dict(f) for f in filas]

    col_defs: list[dict[str, Any]] = []
    for c in columnas:
        campo = c["campo"]
        d: dict[str, Any] = {"field": campo, "headerName": c.get("titulo", campo), "flex": c.get("ancho", 1)}
        tipo: TipoColumna = c.get("tipo", "texto")
        if tipo == "solo_lectura":
            d["editable"] = False
        elif tipo == "numero":
            d["editable"] = True
            d["type"] = "numericColumn"
        elif tipo == "checkbox":
            d["editable"] = True
            d["cellDataType"] = "boolean"
        elif tipo == "select":
            d["editable"] = True
            d["cellEditor"] = "agSelectCellEditor"
            d["cellEditorParams"] = {"values": c.get("opciones", [])}
        else:
            d["editable"] = True
        col_defs.append(d)

    # ui.aggrid trae un alto fijo por defecto: con domLayout "autoHeight" las filas se desbordaban
    # del contenedor. Tablas cortas crecen a su contenido; las largas scrollean dentro de un alto fijo.
    auto_alto = len(filas) <= MAX_FILAS_AUTO_ALTO
    grid = ui.aggrid(
        {
            "columnDefs": col_defs,
            # Columnas proporcionales al ancho disponible (en vez de 200px fijos, que forzaban scroll
            # horizontal); en pantallas angostas minWidth evita aplastar el texto (ahi si scrollea).
            "defaultColDef": {"minWidth": 110, "resizable": True},
            "rowData": filas,
            "stopEditingWhenCellsLoseFocus": True,
            "domLayout": "autoHeight" if auto_alto else "normal",
            "suppressCellFocus": False,
        }
    ).classes("w-full").style("height:auto" if auto_alto else f"height:{ALTO_TABLA_LARGA}")

    async def _guardar() -> None:
        editados = await grid.get_client_data()
        resultado = on_guardar(originales, editados)
        if inspect.isawaitable(resultado):
            await resultado

    ui.button(texto_boton, on_click=_guardar).props("color=primary").classes("mt-2")
    return grid
