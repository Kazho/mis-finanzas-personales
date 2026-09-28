"""Reglas de Categorizacion -- version NiceGUI de vistas/5_Categorias.py (Streamlit).

Es la vista con mas tablas editables (4) de toda la app. Cada seccion es su propio @ui.refreshable;
`_refrescar_listas_categorias()` se llama despues de cualquier accion que cambie el universo de
categorias disponibles (crear/eliminar categoria, agregar/editar regla) porque varias secciones usan
`listar_categorias()` como opciones de su selector -- en Streamlit esto se resolvia solo porque
CUALQUIER cambio recargaba el script completo; aca hay que decirle explicitamente a cada seccion
afectada que se vuelva a pintar."""
import sqlite3

import pandas as pd
from nicegui import ui

from src.analisis_gastos import es_categoria_ahorro
from src.categorias import (
    BUCKETS,
    SIN_CATEGORIA,
    SIN_CLASIFICAR,
    actualizar_categoria_transaccion,
    actualizar_regla,
    agregar_categoria,
    agregar_regla,
    eliminar_categoria_extra,
    eliminar_regla,
    guardar_categoria_bucket,
    listar_categorias,
    listar_categorias_extra,
    listar_meses_transacciones,
    listar_reglas,
    listar_transacciones_por_mes,
    listar_transacciones_sin_categoria,
    obtener_categoria_buckets,
    recategorizar_todas,
)
from src.formato import clp
from src.ui_nicegui.components import banner, tarjeta, texto_muted
from src.ui_nicegui.editable_table import editable_table
from src.ui_nicegui.layout import layout

COLUMNAS_TRANSACCION_BASE = [
    {"campo": "fecha", "titulo": "Fecha", "tipo": "solo_lectura"},
    {"campo": "descripcion", "titulo": "Descripcion", "tipo": "solo_lectura"},
    {"campo": "sucursal", "titulo": "Sucursal", "tipo": "solo_lectura"},
    {"campo": "cuenta", "titulo": "Cuenta", "tipo": "solo_lectura"},
    {"campo": "monto_cargo", "titulo": "Cargo", "tipo": "solo_lectura"},
    {"campo": "monto_abono", "titulo": "Abono", "tipo": "solo_lectura"},
]


def _refrescar_listas_categorias():
    """Llamar despues de crear/eliminar una categoria o agregar/editar una regla -- varias
    secciones ofrecen `listar_categorias()` como opciones y necesitan volver a pintarse."""
    _seccion_sin_categorizar.refresh()
    _seccion_ajustar_mes.refresh()
    _seccion_eliminar_categoria_extra.refresh()
    _seccion_agregar_regla.refresh()
    _seccion_reglas_actuales.refresh()
    _seccion_bucket.refresh()


@ui.refreshable
def _seccion_sin_categorizar():
    sin_categoria = listar_transacciones_sin_categoria()
    if not sin_categoria:
        banner("success", "No tienes transacciones sin categorizar.")
        return

    texto_muted(
        f"Tienes {len(sin_categoria)} transacciones sin categoria. Elige una categoria en la columna de la "
        "derecha y presiona 'Guardar categorias'. Si quieres que las futuras transacciones parecidas se "
        "categoricen solas, agrega ademas una regla mas abajo."
    )
    filas = [
        {
            "id": t["id"], "fecha": t["fecha"], "descripcion": t["descripcion"], "sucursal": t["sucursal"] or "",
            "cuenta": t["cuenta"], "monto_cargo": clp(t["monto_cargo"]), "monto_abono": clp(t["monto_abono"]),
            "categoria": SIN_CATEGORIA,
        }
        for t in sin_categoria
    ]

    def _guardar(_originales, editados):
        cambios = 0
        for fila in editados:
            if fila["categoria"] != SIN_CATEGORIA:
                actualizar_categoria_transaccion(int(fila["id"]), fila["categoria"])
                cambios += 1
        if cambios:
            ui.notify(f"Se categorizaron {cambios} transacciones.", type="positive")
            _seccion_sin_categorizar.refresh()
            _seccion_ajustar_mes.refresh()
        else:
            ui.notify("No cambiaste ninguna categoria.", type="warning")

    editable_table(
        filas,
        [*COLUMNAS_TRANSACCION_BASE, {"campo": "categoria", "titulo": "Categoria", "tipo": "select", "opciones": listar_categorias()}],
        _guardar,
        texto_boton="Guardar categorias",
    )


@ui.refreshable
def _seccion_ajustar_mes():
    meses = listar_meses_transacciones()
    if not meses:
        ui.label("Aun no tienes transacciones cargadas.")
        return

    sel_mes = ui.select(meses, value=meses[0], label="Mes")
    contenedor = ui.column().classes("w-full gap-2")

    def _redibujar(mes_elegido: str):
        contenedor.clear()
        trans_mes = listar_transacciones_por_mes(mes_elegido)
        with contenedor:
            texto_muted(f"{len(trans_mes)} transacciones en {mes_elegido}. Cambia la categoria que corresponda y presiona 'Guardar ajustes'.")
            filas = [
                {
                    "id": t["id"], "fecha": t["fecha"], "descripcion": t["descripcion"], "sucursal": t["sucursal"] or "",
                    "cuenta": t["cuenta"], "monto_cargo": clp(t["monto_cargo"]), "monto_abono": clp(t["monto_abono"]),
                    "categoria": t["categoria"],
                }
                for t in trans_mes
            ]

            def _guardar(_originales, editados):
                cambios = 0
                for original, editado in zip(trans_mes, editados):
                    if editado["categoria"] != original["categoria"]:
                        actualizar_categoria_transaccion(int(editado["id"]), editado["categoria"])
                        cambios += 1
                if cambios:
                    ui.notify(f"Se ajusto la categoria de {cambios} transacciones.", type="positive")
                    _redibujar(mes_elegido)
                    _seccion_sin_categorizar.refresh()
                else:
                    ui.notify("No cambiaste ninguna categoria.", type="warning")

            editable_table(
                filas,
                [*COLUMNAS_TRANSACCION_BASE, {"campo": "categoria", "titulo": "Categoria", "tipo": "select", "opciones": listar_categorias()}],
                _guardar,
                texto_boton="Guardar ajustes",
            )

    sel_mes.on_value_change(lambda e: _redibujar(e.value))
    _redibujar(meses[0])


@ui.refreshable
def _seccion_crear_categoria():
    texto_muted(
        "Usa esto cuando quieras tener una categoria disponible para asignar a mano, sin que quede ligada a "
        "ninguna palabra clave (o sea, no categorizara nada automaticamente)."
    )
    with ui.row().classes("gap-3 items-end w-full"):
        nombre_input = ui.input("Nombre de la categoria").classes("flex-1")

        def _crear():
            if not (nombre_input.value or "").strip():
                ui.notify("Debes indicar un nombre.", type="negative")
                return
            agregar_categoria(nombre_input.value)
            ui.notify(f"Categoria '{nombre_input.value.strip()}' creada.", type="positive")
            _seccion_crear_categoria.refresh()
            _refrescar_listas_categorias()

        ui.button("Crear categoria", on_click=_crear).props("color=primary")


@ui.refreshable
def _seccion_eliminar_categoria_extra():
    categorias_extra = listar_categorias_extra()
    if not categorias_extra:
        return
    with ui.expansion("Eliminar una categoria sin regla"):
        texto_muted(
            "Solo se pueden eliminar aqui las categorias creadas de esta forma (sin regla). Las transacciones "
            "que ya la tengan asignada mantienen el texto, pero dejara de aparecer como opcion para asignar a nuevas."
        )
        sel = ui.select(categorias_extra, value=categorias_extra[0], label="Categoria a eliminar")

        def _eliminar():
            eliminar_categoria_extra(sel.value)
            ui.notify("Categoria eliminada.", type="positive")
            _seccion_eliminar_categoria_extra.refresh()
            _refrescar_listas_categorias()

        ui.button("Eliminar categoria", on_click=_eliminar).props("color=negative outline")


@ui.refreshable
def _seccion_agregar_regla():
    texto_muted(
        "Cuando una transaccion contiene la palabra clave (busqueda simple, sin distinguir mayusculas), se le "
        "asigna la categoria indicada. Por ejemplo, si tus transferencias a la Cuenta RUT familiar siempre dicen "
        "'TRASPASO A:Marianela Poblete', puedes crear la regla 'MARIANELA POBLETE' -> 'Gastos familia' para que "
        "se categoricen solas la proxima vez."
    )
    opciones_categoria = listar_categorias()[:-1] + ["+ Nueva categoria"]
    with ui.row().classes("gap-3 w-full"):
        palabra_input = ui.input("Palabra clave (parte del texto de la transaccion)").classes("flex-1")
        sel_categoria = ui.select(opciones_categoria, value=opciones_categoria[0], label="Categoria").classes("flex-1")
    nueva_categoria_input = ui.input("Nombre de la nueva categoria").classes("w-full")
    nueva_categoria_input.bind_visibility_from(sel_categoria, "value", backward=lambda v: v == "+ Nueva categoria")

    def _agregar():
        categoria_final = (nueva_categoria_input.value or "").strip() if sel_categoria.value == "+ Nueva categoria" else sel_categoria.value
        if not (palabra_input.value or "").strip() or not categoria_final:
            ui.notify("Debes indicar la palabra clave y la categoria.", type="negative")
            return
        agregar_regla(palabra_input.value, categoria_final)
        ui.notify(f"Regla guardada: '{palabra_input.value.strip().upper()}' -> {categoria_final}", type="positive")
        _seccion_agregar_regla.refresh()
        _refrescar_listas_categorias()

    ui.button("Agregar regla", on_click=_agregar).props("color=primary")


@ui.refreshable
def _seccion_reglas_actuales():
    reglas = listar_reglas()
    ui.label("Reglas actuales").classes("text-lg font-bold")
    if not reglas:
        ui.label("Aun no hay reglas configuradas.")
        return

    texto_muted("Puedes editar la palabra clave o la categoria directamente en la tabla y presionar 'Guardar cambios a las reglas'.")
    filas = [{"id": r["id"], "palabra_clave": r["palabra_clave"], "categoria": r["categoria"]} for r in reglas]

    def _guardar(_originales, editados):
        cambios, errores = 0, []
        for original, editado in zip(reglas, editados):
            nueva_palabra = str(editado["palabra_clave"]).strip().upper()
            nueva_categoria = str(editado["categoria"]).strip()
            if nueva_palabra != original["palabra_clave"] or nueva_categoria != original["categoria"]:
                try:
                    actualizar_regla(int(original["id"]), nueva_palabra, nueva_categoria)
                    cambios += 1
                except sqlite3.IntegrityError:
                    errores.append(original["palabra_clave"])
        if errores:
            banner("error", f"Ya existe otra regla con esa palabra clave, no se pudo guardar: {', '.join(errores)}")
        if cambios:
            ui.notify(f"Se actualizaron {cambios} reglas.", type="positive")
            _seccion_reglas_actuales.refresh()
            _refrescar_listas_categorias()
        elif not errores:
            ui.notify("No cambiaste ninguna regla.", type="warning")

    editable_table(
        filas,
        [
            {"campo": "palabra_clave", "titulo": "Palabra clave", "tipo": "texto"},
            {"campo": "categoria", "titulo": "Categoria", "tipo": "select", "opciones": listar_categorias()[:-1]},
        ],
        _guardar,
        texto_boton="Guardar cambios a las reglas",
    )

    with ui.expansion("Eliminar una regla"):
        opciones = {f"{r['palabra_clave']} -> {r['categoria']}": r["id"] for r in reglas}
        sel = ui.select(list(opciones.keys()), value=next(iter(opciones)), label="Selecciona la regla a eliminar")

        def _eliminar():
            eliminar_regla(opciones[sel.value])
            ui.notify("Regla eliminada.", type="positive")
            _seccion_reglas_actuales.refresh()
            _refrescar_listas_categorias()

        ui.button("Eliminar regla", on_click=_eliminar).props("color=negative outline")


@ui.refreshable
def _seccion_bucket():
    texto_muted(
        "Asigna cada categoria a Necesidad, Gusto o Ahorro para ver el grafico de la regla 50/30/20 en el "
        "Dashboard. Las categorias de ahorro/inversion se clasifican solas como Ahorro, no aparecen aqui. Las "
        "que dejes en 'Sin clasificar' no se cuentan en ese grafico."
    )
    buckets_actuales = obtener_categoria_buckets()
    categorias_para_clasificar = [c for c in listar_categorias() if c != SIN_CATEGORIA and not es_categoria_ahorro(c)]
    filas = [{"categoria": c, "balde": buckets_actuales.get(c, SIN_CLASIFICAR)} for c in categorias_para_clasificar]

    if not filas:
        ui.label("Aun no tienes categorias para clasificar.")
        return

    def _guardar(originales, editados):
        cambios = 0
        for original, editado in zip(originales, editados):
            if editado["balde"] != original["balde"]:
                guardar_categoria_bucket(original["categoria"], editado["balde"])
                cambios += 1
        if cambios:
            ui.notify(f"Se actualizo la clasificacion de {cambios} categorias.", type="positive")
            _seccion_bucket.refresh()
        else:
            ui.notify("No cambiaste ninguna clasificacion.", type="warning")

    editable_table(
        filas,
        [
            {"campo": "categoria", "titulo": "Categoria", "tipo": "solo_lectura"},
            {"campo": "balde", "titulo": "Balde", "tipo": "select", "opciones": [SIN_CLASIFICAR, *BUCKETS]},
        ],
        _guardar,
        texto_boton="Guardar clasificacion",
    )


def _seccion_recategorizar():
    texto_muted(
        "Las reglas nuevas solo se aplican automaticamente a lo que cargues de aqui en adelante. Si quieres que "
        "tambien corrijan transacciones que ya importaste, usa este boton."
    )

    def _recategorizar():
        cambios = recategorizar_todas()
        ui.notify(f"Listo: se actualizo la categoria de {cambios} transacciones.", type="positive")
        _seccion_sin_categorizar.refresh()
        _seccion_ajustar_mes.refresh()

    ui.button("Recategorizar todas las transacciones existentes", on_click=_recategorizar).props("color=primary")


@ui.page("/categorias")
def pagina_categorias():
    with layout("/categorias"):
        ui.label("Reglas de Categorizacion").classes("text-2xl font-bold")

        with tarjeta("Transacciones sin categorizar"):
            _seccion_sin_categorizar()

        with tarjeta("Ajustar la categoria de una transaccion ya categorizada"):
            _seccion_ajustar_mes()

        with tarjeta("Crear una categoria nueva (sin regla)"):
            _seccion_crear_categoria()
        _seccion_eliminar_categoria_extra()

        with tarjeta("Reglas de categorizacion automatica"):
            _seccion_agregar_regla()
        with tarjeta():
            _seccion_reglas_actuales()

        with tarjeta("Clasificar categorias (regla 50/30/20)"):
            _seccion_bucket()

        with tarjeta("Recategorizar transacciones ya guardadas"):
            _seccion_recategorizar()
