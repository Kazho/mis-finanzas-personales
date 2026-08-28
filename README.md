# Mis Finanzas Personales

Aplicación de finanzas personales 100% local, hecha con [Streamlit](https://streamlit.io). No requiere servidor ni conexión a internet, salvo una única excepción: la consulta pública y de solo lectura del valor del dólar (para calcular Dólares Premio en tarjetas de crédito). Todos tus datos se guardan en un archivo SQLite en tu propio computador (`data/finanzas.db`) y nunca se suben a ningún servidor.

Cada persona que quiera usarla debe instalarla y correrla en su propio computador — no es un servicio compartido. Cada instalación parte con una base de datos vacía y tú vas cargando tu propia información.

## Instalación

1. Instala [Python 3.11 o superior](https://www.python.org/downloads/) si no lo tienes.
2. Descarga o clona este repositorio.
3. Abre una terminal en la carpeta del proyecto e instala las dependencias:

   ```
   pip install -r requirements.txt
   ```

4. Ejecuta la app:

   ```
   streamlit run app.py
   ```

   En Windows también puedes usar el acceso directo `run.bat`.

5. Se abrirá en tu navegador en `http://localhost:8501`. La primera vez, la app crea automáticamente el archivo `data/finanzas.db` vacío.

## Qué puedes hacer con la app

- **Cargar cartolas** de Banco de Chile (PDF) y clasificar tus movimientos automáticamente por categoría, con detección de duplicados si vuelves a cargar el mismo período.
- **Cargar informes de deuda CMF** (PDF) para hacer seguimiento a tu deuda vigente en el sistema financiero.
- **Registrar ahorros** de cuentas que no entregan cartola (Mach, Tenpo, Mercado Pago, etc.), configurar su tasa de interés anual y ver una proyección de cuánto generarías dejando la plata donde está, o repartiéndola distinto entre tus cuentas.
- **Dashboard** con gasto por categoría, comparación mes a mes, alertas de gasto inusual, metas de ahorro, evolución de tu deuda y tu saldo, y una sección de "Dólares Premio" para tarjetas de crédito con recompensas.
- **Categorías** completamente editables: reglas de categorización automática por palabra clave, categorías propias sin regla asociada, y ajuste manual de la categoría de cualquier transacción ya cargada.
- Modo claro y oscuro, intercambiables desde la barra lateral.

Antes de usarla en serio, revisa [LIMITACIONES.md](LIMITACIONES.md) — hay varias cosas pensadas específicamente para el caso de uso original que quizás debas ajustar a tu banco, tarjeta o AFP.

## Estructura del proyecto

```
app.py                  Punto de entrada, navegación y pagina de Inicio
vistas/                 Una pagina de Streamlit por archivo
src/                    Logica de negocio (parsers, categorizacion, proyeccion, base de datos)
data/finanzas.db        Base de datos SQLite local (se crea sola, no se sube a git)
.streamlit/config.toml  Tema visual por defecto
```

## Aviso

Esto no es asesoría financiera profesional. Las proyecciones y cálculos son estimaciones simples basadas en los datos y tasas que tú mismo ingresas, no garantías de resultado.
