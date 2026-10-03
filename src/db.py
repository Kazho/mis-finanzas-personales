"""Acceso a la base de datos local (SQLite) del proyecto.

La base vive cifrada en disco (`finanzas.db.enc`, ver src/boveda.py) y se trabaja sobre una copia
descifrada en memoria mientras la app esta desbloqueada. `get_conn()` es el unico punto de acceso:
entrega esa conexion y, al salir sin errores, confirma la transaccion y vuelve a cifrar y guardar el
archivo si hubo cambios -- el resto de la app no sabe que hay cifrado de por medio."""
import os
import sqlite3
import sys
from pathlib import Path
from contextlib import contextmanager

from src.boveda import Boveda


def _data_dir() -> Path:
    """En la app empaquetada (PyInstaller) los datos van a una carpeta estable en
    %LOCALAPPDATA%, separada de donde se instale/reinstale el programa, para que
    actualizar o reinstalar la app nunca borre el historial financiero del usuario.
    En modo desarrollo (python app.py / run.bat) se mantiene la carpeta del repo.
    MFP_DATA_DIR permite apuntar a otra carpeta (pruebas con una copia de los datos)."""
    if os.environ.get("MFP_DATA_DIR"):
        return Path(os.environ["MFP_DATA_DIR"])
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
        return base / "MisFinanzasPersonales" / "data"
    return Path(__file__).resolve().parent.parent / "data"


DATA_DIR = _data_dir()
DB_PATH = DATA_DIR / "finanzas.db"  # base SIN cifrar de versiones anteriores; solo se lee para migrarla
BOVEDA_PATH = DATA_DIR / "finanzas.db.enc"

boveda = Boveda(BOVEDA_PATH, DB_PATH)
_lock = boveda.lock
_profundidad = 0

SCHEMA = """
CREATE TABLE IF NOT EXISTS cuentas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT UNIQUE NOT NULL,
    banco TEXT,
    numero_cuenta TEXT
);

CREATE TABLE IF NOT EXISTS transacciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cuenta_id INTEGER NOT NULL REFERENCES cuentas(id),
    fecha TEXT NOT NULL,
    descripcion TEXT NOT NULL,
    sucursal TEXT,
    monto_cargo REAL NOT NULL DEFAULT 0,
    monto_abono REAL NOT NULL DEFAULT 0,
    saldo REAL,
    categoria TEXT,
    categoria_manual INTEGER NOT NULL DEFAULT 0,
    cartola_numero TEXT,
    archivo_origen TEXT,
    hash_dedupe TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS deuda_cmf_informes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_informe TEXT NOT NULL,
    fecha_actualizacion TEXT UNIQUE,
    deuda_total REAL,
    archivo_origen TEXT
);

CREATE TABLE IF NOT EXISTS deuda_cmf_detalle (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    informe_id INTEGER NOT NULL REFERENCES deuda_cmf_informes(id),
    tipo TEXT NOT NULL,
    institucion TEXT,
    tipo_credito TEXT,
    fecha_otorgamiento TEXT,
    total_credito REAL,
    vigente REAL,
    atraso_30_59 REAL,
    atraso_60_89 REAL,
    atraso_90_mas REAL
);

CREATE TABLE IF NOT EXISTS creditos_disponibles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    informe_id INTEGER NOT NULL REFERENCES deuda_cmf_informes(id),
    tipo TEXT NOT NULL,
    institucion TEXT,
    directos REAL,
    indirectos REAL
);

CREATE TABLE IF NOT EXISTS ahorros_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    cuenta TEXT NOT NULL,
    saldo REAL NOT NULL,
    rentabilidad_generada REAL,
    nota TEXT,
    UNIQUE(fecha, cuenta)
);

CREATE TABLE IF NOT EXISTS categoria_reglas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    palabra_clave TEXT UNIQUE NOT NULL,
    categoria TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ahorros_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cuenta TEXT UNIQUE NOT NULL,
    tasa_base REAL,
    monto_umbral REAL,
    tasa_premium REAL,
    costo_mensual REAL
);

CREATE TABLE IF NOT EXISTS metas_ahorro (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    monto_objetivo REAL NOT NULL,
    cuenta TEXT,
    fecha_objetivo TEXT,
    fecha_creacion TEXT NOT NULL,
    completada INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS saldo_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cuenta_id INTEGER NOT NULL REFERENCES cuentas(id),
    fecha TEXT NOT NULL,
    hora TEXT,
    saldo REAL NOT NULL,
    UNIQUE(cuenta_id, fecha, hora)
);

CREATE TABLE IF NOT EXISTS ahorro_cuenta_tipo (
    cuenta TEXT PRIMARY KEY,
    tipo TEXT NOT NULL DEFAULT 'ahorro'
);

CREATE TABLE IF NOT EXISTS tarjeta_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    tipo_tarjeta TEXT,
    dia_corte INTEGER,
    dia_pago INTEGER
);

CREATE TABLE IF NOT EXISTS categorias_extra (
    nombre TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS categoria_bucket (
    categoria TEXT PRIMARY KEY,
    bucket TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS compras_cuotas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    descripcion TEXT NOT NULL,
    valor_cuota REAL NOT NULL,
    total_cuotas INTEGER NOT NULL,
    mes_primera_cuota TEXT NOT NULL,
    fecha_registro TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tc_estados (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cuenta_id INTEGER NOT NULL REFERENCES cuentas(id),
    periodo_hasta TEXT NOT NULL,
    monto_facturado REAL,
    pago_minimo REAL,
    fecha_vencimiento TEXT,
    cupo_total REAL,
    cupo_utilizado REAL,
    cupo_disponible REAL,
    UNIQUE(cuenta_id, periodo_hasta)
);
"""

MIGRACIONES = [
    ("cuentas", "tipo", "ALTER TABLE cuentas ADD COLUMN tipo TEXT NOT NULL DEFAULT 'corriente'"),
    ("cuentas", "moneda", "ALTER TABLE cuentas ADD COLUMN moneda TEXT NOT NULL DEFAULT 'CLP'"),
    ("cuentas", "alias", "ALTER TABLE cuentas ADD COLUMN alias TEXT"),
    ("cuentas", "archivada", "ALTER TABLE cuentas ADD COLUMN archivada INTEGER NOT NULL DEFAULT 0"),
    # 'facturado' (ya esta en un estado de cuenta) o 'por_facturar' (compra o pago de tarjeta posterior al
    # ultimo corte, provisional hasta que llegue el estado de cuenta que la incluya).
    ("transacciones", "estado", "ALTER TABLE transacciones ADD COLUMN estado TEXT NOT NULL DEFAULT 'facturado'"),
    # De donde vino el dato ('archivo_pdf', 'archivo_xls', 'api'; 'archivo' en lo cargado antes de existir esta
    # columna) y su identificador en el banco, si lo trae. Con una API el `id_externo` es la forma segura de no
    # duplicar; sin el, se usa `hash_dedupe`.
    ("transacciones", "fuente", "ALTER TABLE transacciones ADD COLUMN fuente TEXT NOT NULL DEFAULT 'archivo'"),
    ("transacciones", "id_externo", "ALTER TABLE transacciones ADD COLUMN id_externo TEXT"),
    ("cuentas", "id_externo", "ALTER TABLE cuentas ADD COLUMN id_externo TEXT"),
    # Identificador global (UUID) que no depende de la base de cada dispositivo: es lo que permite sincronizar
    # PC y celular por eventos sin que choquen los ids autoincrementales de cada uno.
    ("transacciones", "uid", "ALTER TABLE transacciones ADD COLUMN uid TEXT"),
    ("cuentas", "uid", "ALTER TABLE cuentas ADD COLUMN uid TEXT"),
    ("ahorros_config", "costo_mensual", "ALTER TABLE ahorros_config ADD COLUMN costo_mensual REAL"),
    (
        "transacciones",
        "categoria_manual",
        "ALTER TABLE transacciones ADD COLUMN categoria_manual INTEGER NOT NULL DEFAULT 0",
    ),
    (
        "ahorros_config",
        "abono_mensual",
        "ALTER TABLE ahorros_config ADD COLUMN abono_mensual INTEGER NOT NULL DEFAULT 0",
    ),
]


# Se ejecuta DESPUES de las migraciones (las columnas ya existen). Los indices unicos parciales no se pueden
# declarar en un ALTER TABLE, y el trigger asigna `uid` a cualquier fila nueva que no lo traiga, venga de donde venga.
POST_MIGRACIONES = """
UPDATE transacciones SET uid = lower(hex(randomblob(16))) WHERE uid IS NULL;
UPDATE cuentas SET uid = lower(hex(randomblob(16))) WHERE uid IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_transacciones_uid ON transacciones(uid);
CREATE UNIQUE INDEX IF NOT EXISTS ux_cuentas_uid ON cuentas(uid);
CREATE UNIQUE INDEX IF NOT EXISTS ux_transacciones_id_externo ON transacciones(cuenta_id, id_externo) WHERE id_externo IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_cuentas_id_externo ON cuentas(id_externo) WHERE id_externo IS NOT NULL;
CREATE TRIGGER IF NOT EXISTS trg_transacciones_uid AFTER INSERT ON transacciones WHEN NEW.uid IS NULL
BEGIN UPDATE transacciones SET uid = lower(hex(randomblob(16))) WHERE id = NEW.id; END;
CREATE TRIGGER IF NOT EXISTS trg_cuentas_uid AFTER INSERT ON cuentas WHEN NEW.uid IS NULL
BEGIN UPDATE cuentas SET uid = lower(hex(randomblob(16))) WHERE id = NEW.id; END;
"""


@contextmanager
def get_conn():
    """Conexion a la base descifrada en memoria. Las llamadas anidadas comparten la transaccion: solo
    la mas externa confirma (o deshace, si hubo una excepcion) y guarda el archivo cifrado."""
    global _profundidad
    with _lock:
        conn = boveda.conn
        if conn is None:
            raise RuntimeError("La base de datos esta bloqueada: desbloquea la app primero.")
        _profundidad += 1
        cambios_antes = conn.total_changes
        try:
            yield conn
        except BaseException:
            if _profundidad == 1:
                conn.rollback()
            raise
        else:
            if _profundidad == 1:
                conn.commit()
                if conn.total_changes != cambios_antes:
                    boveda.guardar()
        finally:
            _profundidad -= 1


def aplicar_esquema(conn: sqlite3.Connection) -> None:
    """Crea las tablas que falten y aplica las migraciones pendientes sobre `conn`. Es idempotente: se puede
    llamar en cada arranque (y los tests la usan sobre bases en memoria)."""
    conn.executescript(SCHEMA)
    for tabla, columna, alter in MIGRACIONES:
        if not tabla.isidentifier():
            raise ValueError(f"Nombre de tabla invalido en MIGRACIONES: {tabla!r}")
        columnas = {r[1] for r in conn.execute(f"PRAGMA table_info({tabla})").fetchall()}  # r[1] = nombre
        if columna not in columnas:
            conn.execute(alter)
            if (tabla, columna) == ("cuentas", "tipo"):
                # Las cuentas ya cargadas antes de existir el tipo quedan como 'corriente'; la
                # CuentaRUT de BancoEstado es cuenta vista, y se corrige solo esta vez para no pisar
                # lo que el usuario edite despues.
                conn.execute("UPDATE cuentas SET tipo = 'vista' WHERE banco = 'BancoEstado'")
    conn.executescript(POST_MIGRACIONES)


def init_db():
    with get_conn() as conn:
        aplicar_esquema(conn)
    # CREATE/ALTER no cuentan en total_changes, asi que get_conn no detecta que hay que guardar.
    boveda.guardar()


def get_or_create_cuenta(nombre: str, banco: str = None, numero_cuenta: str = None,
                         tipo: str = "corriente", moneda: str = "CLP", id_externo: str = None) -> int:
    """Si la cuenta ya existe se devuelve tal cual: tipo y moneda solo se fijan al crearla, para no
    pisar lo que el usuario haya corregido a mano en la pagina Cuentas."""
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM cuentas WHERE nombre = ?", (nombre,)).fetchone()
        if row:
            return row["id"]
        cur = conn.execute(
            "INSERT INTO cuentas (nombre, banco, numero_cuenta, tipo, moneda, id_externo) VALUES (?, ?, ?, ?, ?, ?)",
            (nombre, banco, numero_cuenta, tipo, moneda, id_externo),
        )
        return cur.lastrowid


def buscar_banco_por_numero(numero_cuenta: str) -> str | None:
    """Banco de una cuenta ya creada con ese numero (ej. 'TC-1234'). Sirve para documentos que no dicen de
    que banco son: la primera vez se le pregunta al usuario y despues se reutiliza."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT banco FROM cuentas WHERE numero_cuenta = ? AND banco IS NOT NULL AND banco != '' LIMIT 1",
            (numero_cuenta,),
        ).fetchone()
    return row["banco"] if row else None


def reemplazar_provisionales(cuenta_id: int, hasta_fecha: str | None = None) -> int:
    """Borra los movimientos 'por facturar' de la cuenta: son provisionales y el documento que se esta
    cargando los reemplaza. Con `hasta_fecha` (corte de un estado de cuenta facturado) solo se borran los
    de esa fecha o anteriores, porque son los que el estado de cuenta ya incluye; sin ella (una consulta
    nueva de movimientos por facturar) se borran todos, porque la consulta nueva los lista completos."""
    with get_conn() as conn:
        if hasta_fecha:
            cur = conn.execute(
                "DELETE FROM transacciones WHERE cuenta_id = ? AND estado = 'por_facturar' AND fecha <= ?",
                (cuenta_id, hasta_fecha),
            )
        else:
            cur = conn.execute(
                "DELETE FROM transacciones WHERE cuenta_id = ? AND estado = 'por_facturar'", (cuenta_id,)
            )
        return cur.rowcount


def guardar_estado_tc(cuenta_id: int, estado: dict):
    """Datos de cabecera de un estado de cuenta de tarjeta (cupo, monto a pagar, vencimiento). Si se vuelve
    a cargar el mismo periodo se actualiza, pero un dato que el documento nuevo no trae (None) no pisa el que
    ya estaba: el estado facturado trae monto y vencimiento, y el de movimientos por facturar trae el cupo."""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO tc_estados (cuenta_id, periodo_hasta, monto_facturado, pago_minimo, fecha_vencimiento,
                                    cupo_total, cupo_utilizado, cupo_disponible)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cuenta_id, periodo_hasta) DO UPDATE SET
                monto_facturado = COALESCE(excluded.monto_facturado, monto_facturado),
                pago_minimo = COALESCE(excluded.pago_minimo, pago_minimo),
                fecha_vencimiento = COALESCE(excluded.fecha_vencimiento, fecha_vencimiento),
                cupo_total = COALESCE(excluded.cupo_total, cupo_total),
                cupo_utilizado = COALESCE(excluded.cupo_utilizado, cupo_utilizado),
                cupo_disponible = COALESCE(excluded.cupo_disponible, cupo_disponible)
            """,
            (
                cuenta_id, estado["periodo_hasta"].isoformat(), estado.get("monto_facturado"),
                estado.get("pago_minimo"),
                estado["fecha_vencimiento"].isoformat() if estado.get("fecha_vencimiento") else None,
                estado.get("cupo_total"), estado.get("cupo_utilizado"), estado.get("cupo_disponible"),
            ),
        )


def obtener_tipos_cuenta() -> dict[str, str]:
    """Devuelve {cuenta: 'ahorro'|'movimiento'} para las cuentas de ahorro que ya tienen tipo marcado.
    Las que no aparecen aqui se asumen 'ahorro' (plata quieta) por defecto."""
    with get_conn() as conn:
        rows = conn.execute("SELECT cuenta, tipo FROM ahorro_cuenta_tipo").fetchall()
    return {r["cuenta"]: r["tipo"] for r in rows}


def guardar_tipo_cuenta(cuenta: str, tipo: str):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO ahorro_cuenta_tipo (cuenta, tipo) VALUES (?, ?)
            ON CONFLICT(cuenta) DO UPDATE SET tipo = excluded.tipo
            """,
            (cuenta, tipo),
        )


def obtener_config_tarjeta() -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM tarjeta_config WHERE id = 1").fetchone()
    return dict(row) if row else None


def guardar_config_tarjeta(tipo_tarjeta: str, dia_corte: int, dia_pago: int):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO tarjeta_config (id, tipo_tarjeta, dia_corte, dia_pago) VALUES (1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                tipo_tarjeta = excluded.tipo_tarjeta,
                dia_corte = excluded.dia_corte,
                dia_pago = excluded.dia_pago
            """,
            (tipo_tarjeta, dia_corte, dia_pago),
        )


def guardar_saldo_snapshot(cuenta_id: int, fecha: str, hora: str | None, saldo: float):
    """Guarda el saldo real de la cuenta a una fecha/hora dada (ej. 'Saldo Disponible' de un PDF
    de movimientos, o el saldo final de una cartola), independiente de las transacciones — asi
    el Dashboard puede reflejar retenciones u otros efectos que no aparecen como movimientos."""
    # SQLite trata cada NULL como distinto en una restriccion UNIQUE (nunca choca consigo mismo),
    # asi que se usa "" en vez de None para que el ON CONFLICT funcione cuando no hay hora
    # (cartola oficial) y no se acumulen filas repetidas al volver a cargar el mismo documento.
    hora = hora or ""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO saldo_snapshot (cuenta_id, fecha, hora, saldo) VALUES (?, ?, ?, ?)
            ON CONFLICT(cuenta_id, fecha, hora) DO UPDATE SET saldo = excluded.saldo
            """,
            (cuenta_id, fecha, hora, saldo),
        )
