"""Base SQLite en memoria para pruebas, con el esquema real, sustituyendo `get_conn` de la app."""
import sqlite3
from contextlib import contextmanager
from unittest import mock

from src import db, ingesta


@contextmanager
def bd_en_memoria():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.aplicar_esquema(conn)

    @contextmanager
    def _get_conn():
        yield conn

    with mock.patch.object(db, "get_conn", _get_conn), mock.patch.object(ingesta, "get_conn", _get_conn):
        yield conn
    conn.close()
