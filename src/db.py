"""Acceso a la base de datos local (SQLite) del proyecto."""
import sqlite3
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "finanzas.db"

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
"""

MIGRACIONES = [
    ("ahorros_config", "costo_mensual", "ALTER TABLE ahorros_config ADD COLUMN costo_mensual REAL"),
    (
        "transacciones",
        "categoria_manual",
        "ALTER TABLE transacciones ADD COLUMN categoria_manual INTEGER NOT NULL DEFAULT 0",
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
