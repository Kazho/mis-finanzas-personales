# Limitaciones actuales

Este documento lista qué cosas están pensadas específicamente para el caso de uso original (banco chileno Banco de Chile, tarjeta de crédito con Dólares Premio) y qué deberías revisar o ajustar si tu situación es distinta.

## Carga de datos

- **El parser de cartola entiende Banco de Chile** (cartola oficial y el PDF de "Movimientos al día") **y la cartola CuentaRUT de BancoEstado** (incluye soporte para el PDF protegido con contraseña que usa BancoEstado). Si usas otro banco, u otro tipo de cuenta de BancoEstado, la carga de PDF no va a funcionar — tendrías que adaptar `src/parser_cartola.py` / `src/parser_movimientos.py` / `src/parser_bancoestado.py` al formato de tu documento, o cargar tus movimientos de otra forma.
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
- La inflación esperada parte en la variación de la UF de los últimos 12 meses (mindicador.cl); si la API no responde se usa 3% (meta del Banco Central). Se puede cambiar a mano en la pestaña Proyección, pero no se guarda entre sesiones.
- El comparador de DAP asume tasa fija a todo el plazo (interés simple, como lo muestran los simuladores de los bancos) — no aplica a depósitos con tasa variable.

## Tarjeta de crédito / Dólares Premio

- Las tasas de acumulación de Dólares Premio (`TASAS_DOLARES_PREMIO` en `paginas_nicegui/dashboard.py`) son las de **Banco de Chile** para compras nacionales. Si tu tarjeta es de otro banco o tiene otro programa de recompensas, esos cálculos no van a ser correctos — habría que reemplazar esa tabla por la de tu banco.
- Solo se puede configurar **una tarjeta de crédito a la vez** (una sola fila de configuración guardada). Si tienes más de una tarjeta, tendrías que elegir cuál trackear o extender la app para soportar varias.
- Las **compras en cuotas** se registran a mano (la app no lee el estado de cuenta de la tarjeta) y asumen cuotas fijas sin interés adicional, una por mes.
- La **detección de gastos recurrentes** busca cobros del mismo comercio, ~1 vez al mes y por un monto parecido, durante al menos 3 meses; cobros anuales, semestrales o de monto muy variable no se detectan.
- El valor del dólar se obtiene de una API pública (mindicador.cl) una vez al día — no es editable a mano, así que si esa API falla o no aplica a tu caso, esa parte de la app queda sin datos hasta que vuelva a responder.

## General

- Es una app **de un solo usuario por instalación**: no hay login, perfiles múltiples ni separación de datos entre personas dentro de una misma base de datos. Si varias personas la usan, cada una necesita su propia instalación (su propia carpeta con su propio `data/finanzas.db.enc`).
- Los datos están **cifrados** (`data/finanzas.db.enc`), pero:
  - Si pierdes **la contraseña y el código de recuperación**, los datos no se pueden recuperar — es la contracara de que nadie más pueda leerlos.
  - Mientras la app está **desbloqueada**, los datos viven descifrados en la memoria del proceso. El acceso queda atado al navegador donde ingresaste la contraseña (cookie de sesión); otro navegador o programa debe ingresarla de nuevo. Aun así, un malware con control de tu usuario de Windows podría leer la memoria o tu navegador: el cifrado protege el archivo en disco, no un PC ya comprometido. La app se bloquea sola tras **5 minutos sin actividad** (mouse, teclado, scroll) en ninguna pestaña, avisando 1 minuto antes; igual conviene usar el candado al terminar.
  - El **auto-actualizador** solo instala versiones firmadas con la clave Ed25519 del autor (ver `installer/firmar_release.py`), que no pasa por GitHub. Mientras la clave no se haya generado, la app avisa de las versiones nuevas pero pide descargarlas a mano. Las versiones instaladas **antes** de este cambio no verifican firmas, así que la protección aplica desde la primera versión firmada que se instale. El instalador en sí sigue sin firma de código de Windows (SmartScreen seguirá advirtiendo): eso requiere un certificado pagado.
  - Los respaldos automáticos (`data/respaldos/`, últimos 7 días) quedan en el **mismo disco**: sirven ante un archivo dañado, no ante perder el computador. Como están cifrados, puedes copiarlos a OneDrive/Google Drive sin exponer nada.
  - Al migrar desde una versión sin cifrado queda una copia **sin cifrar** hasta que la eliminas desde el aviso de la app. Se sobrescribe con ceros antes de borrarla, pero en discos SSD eso no garantiza que el contenido original desaparezca físicamente del disco.
- No hay exportación a Excel/CSV todavía — los datos solo se ven dentro de la app.
- Probada solo en Windows; en Mac/Linux debería funcionar igual (es Python + NiceGUI puro) pero no se ha verificado.
- El instalador de Windows (`installer/setup.iss`) no está firmado digitalmente (eso requiere un certificado de firma de código pago) — Windows SmartScreen va a mostrar una advertencia la primera vez que se ejecuta. El auto-actualizador depende de que el repositorio del proyecto sea público en GitHub (para no tener que guardar ninguna credencial dentro del `.exe`).
