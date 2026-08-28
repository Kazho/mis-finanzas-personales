# Limitaciones actuales

Este documento lista qué cosas están pensadas específicamente para el caso de uso original (banco chileno Banco de Chile, tarjeta de crédito con Dólares Premio) y qué deberías revisar o ajustar si tu situación es distinta.

## Carga de datos

- **El parser de cartola solo entiende el formato de Banco de Chile** (tanto la cartola oficial como el PDF de "Movimientos al día"). Si usas otro banco, la carga de PDF no va a funcionar — tendrías que adaptar `src/parser_cartola.py` / `src/parser_movimientos.py` al formato de tu banco, o cargar tus movimientos de otra forma.
- **El informe de deuda CMF** se lee del PDF que entrega la Comisión para el Mercado Financiero (`src/parser_cmf.py`); si su formato cambia con el tiempo, el parser puede dejar de funcionar y necesitaría actualizarse.
- **La detección de duplicados** se basa en cuenta + fecha + descripción + montos + saldo de cada movimiento, no en el número de cartola — funciona bien para no duplicar movimientos al recargar el mismo período, pero depende de que esos campos vengan igual en cada carga.
- No hay forma de cargar cartolas automáticamente por correo o por conexión directa al banco — toda carga es manual, arrastrando el PDF a la página correspondiente.

## Categorización

- Las reglas de categorización que vienen precargadas (`CATEGORIAS_DEFAULT` en `src/categorias.py`) están pensadas para comercios y movimientos típicos en Chile — supermercados, farmacias, apps de delivery, etc. Si usas otros comercios o vives en otro país, tendrás que crear tus propias reglas desde la página "Categorías" (no hace falta tocar código).
- La categorización es por **palabra clave simple** (si el texto de la transacción contiene la palabra, sin distinguir mayúsculas) — no es un clasificador inteligente, así que palabras ambiguas pueden categorizar mal transacciones que no correspondían.
- El neteo de gasto por categoría (cargos menos abonos) asume que, si quieres que un reembolso descuente de un gasto, lo vas a categorizar tú mismo en la misma categoría del gasto original — no hay detección automática de qué abono corresponde a qué cargo.

## Ahorros e inversión

- Las tasas de interés, montos tope y "abono mensual vs diario" de cada cuenta se configuran **a mano** en "Registrar Ahorro" — la app no las descubre solas ni las actualiza si el banco/fintech cambia su tasa.
- Los saldos de cuentas sin cartola (Mach, Tenpo, Mercado Pago, etc.) se registran **a mano** cada vez que revisas la app — no hay actualización automática.
- No hay soporte todavía para **AFP** (fondos de pensión) ni **APV** (ahorro previsional voluntario): son inversiones de rentabilidad variable, no cuentas con tasa fija, y necesitarían su propio modelo de datos.
- Las proyecciones de ganancia (diaria o mensualmente compuesta) son estimaciones simples: usan un año de 365 días parejo, no consideran feriados bancarios, cambios de tasa futuros, ni retiros parciales dentro del período proyectado.
- El comparador de DAP asume tasa fija a todo el plazo (interés simple, como lo muestran los simuladores de los bancos) — no aplica a depósitos con tasa variable.

## Tarjeta de crédito / Dólares Premio

- Las tasas de acumulación de Dólares Premio (`TASAS_DOLARES_PREMIO` en `vistas/4_Dashboard.py`) son las de **Banco de Chile** para compras nacionales. Si tu tarjeta es de otro banco o tiene otro programa de recompensas, esos cálculos no van a ser correctos — habría que reemplazar esa tabla por la de tu banco.
- Solo se puede configurar **una tarjeta de crédito a la vez** (una sola fila de configuración guardada). Si tienes más de una tarjeta, tendrías que elegir cuál trackear o extender la app para soportar varias.
- El valor del dólar se obtiene de una API pública (mindicador.cl) una vez al día — no es editable a mano, así que si esa API falla o no aplica a tu caso, esa parte de la app queda sin datos hasta que vuelva a responder.

## General

- Es una app **de un solo usuario por instalación**: no hay login, perfiles múltiples ni separación de datos entre personas dentro de una misma base de datos. Si varias personas la usan, cada una necesita su propia instalación (su propia carpeta con su propio `data/finanzas.db`).
- El archivo `data/finanzas.db` **no está cifrado ni respaldado automáticamente** — si pierdes el archivo (o el computador), pierdes el historial. Conviene respaldarlo tú mismo de vez en cuando (copiar el archivo a otro lugar).
- No hay exportación a Excel/CSV todavía — los datos solo se ven dentro de la app.
- Probada solo en Windows; en Mac/Linux debería funcionar igual (es Python + Streamlit puro) pero no se ha verificado.
- El instalador de Windows (`installer/setup.iss`) no está firmado digitalmente (eso requiere un certificado de firma de código pago) — Windows SmartScreen va a mostrar una advertencia la primera vez que se ejecuta. El auto-actualizador depende de que el repositorio del proyecto sea público en GitHub (para no tener que guardar ninguna credencial dentro del `.exe`).
