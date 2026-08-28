"""Acceso a la base de datos local (SQLite) del proyecto."""
import os
import sqlite3
import sys
from pathlib import Path
from contextlib import contextmanager


def _data_dir() -> Path:
    """En la app empaquetada (PyInstaller) los datos van a una carpeta estable en
    %LOCALAPPDATA%, separada de donde se instale/reinstale el programa, para que
    actualizar o reinstalar la app nunca borre el historial financiero del usuario.
    En modo desarrollo (python app.py / run.bat) se mantiene la carpeta del repo."""
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
        return base / "MisFinanzasPersonales" / "data"
    return Path(__file__).resolve().parent.parent / "data"


DATA_DIR = _data_dir()
DB_PATH = DATA_DIR / "finanzas.db"

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
"""

MIGRACIONES = [
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


@contextmanager
def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        for tabla, columna, alter in MIGRACIONES:
            if not tabla.isidentifier():
                raise ValueError(f"Nombre de tabla invalido en MIGRACIONES: {tabla!r}")
            columnas = {r["name"] for r in conn.execute(f"PRAGMA table_info({tabla})").fetchall()}
            if columna not in columnas:
                conn.execute(alter)


def get_or_create_cuenta(nombre: str, banco: str = None, numero_cuenta: str = None) -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM cuentas WHERE nombre = ?", (nombre,)).fetchone()
        if row:
            return row["id"]
        cur = conn.execute(
            "INSERT INTO cuentas (nombre, banco, numero_cuenta) VALUES (?, ?, ?)",
            (nombre, banco, numero_cuenta),
        )
        return cur.lastrowid


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
