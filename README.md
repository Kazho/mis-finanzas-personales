# Mis Finanzas Personales

Aplicación de finanzas personales con tus datos cifrados, hecha con [NiceGUI](https://nicegui.io). No requiere servidor ni conexión a internet, salvo dos excepciones de solo lectura: la consulta pública del valor del dólar y de la UF a mindicador.cl (para Dólares Premio, y para mostrar tus ahorros y proyecciones en UF y descontando inflación) y, si usas el instalador de Windows, el chequeo de versión nueva contra GitHub Releases. Todos tus datos se guardan **cifrados con AES-256** en un archivo de tu propio computador — `data/finanzas.db.enc` corriendo desde el código fuente, o `%LOCALAPPDATA%\MisFinanzasPersonales\data\finanzas.db.enc` con el instalador. La clave sale de tu contraseña (derivada con scrypt) y los datos solo se descifran en memoria mientras la app está desbloqueada. Si olvidas la contraseña, entras con el código de recuperación que se muestra una sola vez al activar el cifrado; sin ninguno de los dos, nadie puede leer los datos (ni tú). Si venías de una versión anterior sin cifrado, la app cifra tu base existente la primera vez que la abres.

Cada persona que quiera usarla debe instalarla y correrla en su propio computador — no es un servicio compartido. Cada instalación parte con una base de datos vacía y tú vas cargando tu propia información.

## Instalación

### Opción 1: instalador para Windows (recomendada si no eres programador)

1. Descarga el instalador (`MisFinanzasPersonales-Setup-X.Y.Z.exe`) desde la
   [página de Releases](https://github.com/Kazho/mis-finanzas-personales/releases) del proyecto.
2. Ejecútalo y sigue el asistente (Siguiente → Siguiente → Finalizar) — no necesita permisos de
   administrador ni tener Python instalado.
3. Se crea un acceso directo en el Escritorio y en el Menú Inicio. Al abrirla, la app se ejecuta
   en tu navegador igual que la versión de código fuente.
4. La app avisa sola cuando hay una versión nueva disponible, con un botón para actualizar sin
   tener que descargar nada a mano.

Windows puede mostrar una advertencia de SmartScreen la primera vez (el instalador no está firmado
digitalmente) — click en "Más información" → "Ejecutar de todas formas".

### Opción 2: desde el código fuente (para desarrollo o si prefieres no usar el instalador)

1. Instala [Python 3.11 o superior](https://www.python.org/downloads/) si no lo tienes.
2. Descarga o clona este repositorio.
3. Abre una terminal en la carpeta del proyecto e instala las dependencias:

   ```
   pip install -r requirements.txt
   ```

4. Ejecuta la app:

   ```
   py launcher.py
   ```

   En Windows también puedes usar el acceso directo `run.bat`.

5. Se abrirá en tu navegador en `http://localhost:8765`. La primera vez te pide crear una contraseña y te muestra tu código de recuperación (guárdalo); después crea el archivo cifrado `data/finanzas.db.enc`. Cada día que desbloqueas la app se guarda un respaldo (también cifrado) en `data/respaldos/`, conservando los últimos 7.

## Qué puedes hacer con la app

- **Cargar cartolas** de Banco de Chile o CuentaRUT de BancoEstado (PDF) y clasificar tus movimientos automáticamente por categoría, con detección de duplicados si vuelves a cargar el mismo período.
- **Cargar informes de deuda CMF** (PDF) para hacer seguimiento a tu deuda vigente en el sistema financiero.
- **Registrar ahorros** de cuentas que no entregan cartola (Mach, Tenpo, Mercado Pago, etc.), configurar su tasa de interés anual y ver una proyección de cuánto generarías dejando la plata donde está, o repartiéndola distinto entre tus cuentas.
- **Dashboard** con gasto por categoría, comparación mes a mes, alertas de gasto inusual, metas de ahorro, evolución de tu deuda y tu saldo, detección automática de gastos recurrentes y suscripciones (con aviso si suben de precio), proyecciones en UF y en términos reales (descontando inflación), seguimiento de compras en cuotas, y una sección de "Dólares Premio" para tarjetas de crédito con recompensas.
- **Categorías** completamente editables: reglas de categorización automática por palabra clave, categorías propias sin regla asociada, y ajuste manual de la categoría de cualquier transacción ya cargada.
- Modo claro y oscuro, intercambiables desde el boton en la parte superior.

Antes de usarla en serio, revisa [LIMITACIONES.md](LIMITACIONES.md) — hay varias cosas pensadas específicamente para el caso de uso original que quizás debas ajustar a tu banco, tarjeta o AFP.

## Estructura del proyecto

```
launcher.py             Punto de entrada (modo desarrollo y .exe empaquetado, sin consola visible)
paginas_nicegui/        Una pagina de NiceGUI por archivo (@ui.page)
src/                    Logica de negocio (parsers, categorizacion, proyeccion, base de datos)
src/ui_nicegui/         Tema, componentes y helpers de la capa visual (NiceGUI)
data/finanzas.db.enc    Base de datos cifrada (se crea sola, no se sube a git)
data/respaldos/         Respaldos diarios cifrados (últimos 7)
VERSION                 Version actual, fuente unica de verdad para el instalador y el updater
assets/app.ico          Icono de la app
installer/setup.iss     Script de Inno Setup para armar el instalador de Windows
.github/workflows/      CI que arma el instalador al crear un tag vX.Y.Z y lo deja en un release borrador
installer/firmar_release.py  Firma y publica cada release con tu clave privada (fuera de GitHub)
requirements-dev.txt    Dependencias (version exacta) solo para empaquetar el .exe
```

## Publicar una versión nueva (mantenedor)

Las actualizaciones automáticas solo se instalan si vienen firmadas con tu clave privada, que nunca se sube a GitHub:

1. **Una sola vez:** `py installer/firmar_release.py generar-clave` — pide una frase de paso, guarda la clave privada cifrada en `~/.mis-finanzas-firma/` y escribe la clave pública en `src/actualizador_core.py` (haz commit de ese cambio). Respalda la clave privada y su frase fuera de este PC.
2. Actualiza `VERSION`, haz commit y `git tag vX.Y.Z && git push origin vX.Y.Z`. El CI arma el instalador y lo deja en un release **borrador** (invisible para las apps instaladas).
3. `py installer/firmar_release.py firmar vX.Y.Z` — descarga el instalador del borrador, lo firma, sube la firma y publica el release.

## Aviso

Esto no es asesoría financiera profesional. Las proyecciones y cálculos son estimaciones simples basadas en los datos y tasas que tú mismo ingresas, no garantías de resultado.
