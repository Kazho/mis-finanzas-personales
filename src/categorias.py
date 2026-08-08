"""Categorizacion automatica de transacciones por palabra clave."""
from src.db import get_conn

CATEGORIAS_DEFAULT = [
    ("MERCADOPAGO", "Comida y almacen"),
    ("PAYSCAN", "Comida y almacen"),
    ("BOTILLERIA", "Comida y almacen"),
    ("SUPERMERCADO", "Comida y almacen"),
    ("JUMBO", "Comida y almacen"),
    ("LIDER", "Comida y almacen"),
    ("SANTA ISABEL", "Comida y almacen"),
    ("UNIMARC", "Comida y almacen"),
    ("KFC", "Restaurantes y delivery"),
    ("SUMUP", "Restaurantes y delivery"),
    ("RAPPI", "Restaurantes y delivery"),
    ("UBER EATS", "Restaurantes y delivery"),
    ("PEDIDOSYA", "Restaurantes y delivery"),
    ("RESTAURANT", "Restaurantes y delivery"),
    ("CASA DEL CHEF", "Restaurantes y delivery"),
    ("UBER TRIP", "Transporte"),
    ("UBER *TRIP", "Transporte"),
    ("CABIFY", "Transporte"),
    ("METRO", "Transporte"),
    ("PARKING", "Transporte"),
    ("PARQUE ARAUCO", "Estacionamiento"),
    ("SHELL", "Combustible"),
    ("COPEC", "Combustible"),
    ("PETROBRAS", "Combustible"),
    ("ARAMCO", "Combustible"),
    ("FARMACIA", "Salud"),
    ("CRUZ VERDE", "Salud"),
    ("SALCOBRAND", "Salud"),
    ("AHUMADA", "Salud"),
    ("ISAPRE", "Salud"),
    ("SPOTIFY", "Suscripciones"),
    ("NETFLIX", "Suscripciones"),
    ("YOUTUBE", "Suscripciones"),
    ("HBO", "Suscripciones"),
    ("DISNEY", "Suscripciones"),
    ("AMAZON PRIME", "Suscripciones"),
    ("FALABELLA", "Retail y compras"),
    ("PARIS", "Retail y compras"),
    ("RIPLEY", "Retail y compras"),
    ("ALTO LAS CONDES", "Retail y compras"),
    ("MALL", "Retail y compras"),
    ("SERVIPAG", "Servicios basicos"),
    ("CGE", "Servicios basicos"),
    ("AGUAS", "Servicios basicos"),
    ("LUZ", "Servicios basicos"),
    ("GAS", "Servicios basicos"),
    ("ENTEL", "Servicios basicos"),
    ("MOVISTAR", "Servicios basicos"),
    ("WOM", "Servicios basicos"),
    ("VTR", "Servicios basicos"),
    ("PAGO TARJETA DE CREDITO", "Pago tarjeta de credito"),
    ("PAGO LINEA DE CRED", "Pago linea de credito"),
    ("CARGO POR PAGO TC", "Pago tarjeta de credito"),
    ("TARJETA CMR", "Pago tarjeta de credito"),
    ("SEGURO", "Seguros"),
    ("TRASPASO A", "Transferencia enviada"),
    ("TRASPASO DE", "Transferencia recibida"),
    ("PAGO:DE SUELDOS", "Ingreso"),
    ("SUELDO", "Ingreso"),
    ("COMISION", "Comisiones bancarias"),
]

SIN_CATEGORIA = "Sin categoria"


def _cargar_reglas() -> list[tuple[str, str]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT palabra_clave, categoria FROM categoria_reglas ORDER BY LENGTH(palabra_clave) DESC"
        ).fetchall()
    return [(r["palabra_clave"], r["categoria"]) for r in rows]


def asegurar_reglas_default():
    with get_conn() as conn:
        for palabra, categoria in CATEGORIAS_DEFAULT:
            conn.execute(
                "INSERT OR IGNORE INTO categoria_reglas (palabra_clave, categoria) VALUES (?, ?)",
                (palabra, categoria),
            )


def categorizar(descripcion: str) -> str:
    texto = descripcion.upper()
    for palabra, categoria in _cargar_reglas():
        if palabra in texto:
            return categoria
    return SIN_CATEGORIA


def listar_categorias() -> list[str]:
    categorias = {c for _, c in CATEGORIAS_DEFAULT}
    with get_conn() as conn:
        categorias |= {
            r["categoria"] for r in conn.execute("SELECT DISTINCT categoria FROM categoria_reglas").fetchall()
        }
    resultado = sorted(categorias)
    resultado.append(SIN_CATEGORIA)
    return resultado


def listar_reglas() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, palabra_clave, categoria FROM categoria_reglas ORDER BY categoria, palabra_clave"
        ).fetchall()
    return [dict(r) for r in rows]


def agregar_regla(palabra_clave: str, categoria: str):
    palabra_clave = palabra_clave.strip().upper()
    categoria = categoria.strip()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO categoria_reglas (palabra_clave, categoria) VALUES (?, ?)
            ON CONFLICT(palabra_clave) DO UPDATE SET categoria = excluded.categoria
            """,
            (palabra_clave, categoria),
        )


def eliminar_regla(regla_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM categoria_reglas WHERE id = ?", (regla_id,))


def listar_transacciones_sin_categoria() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT t.id, t.fecha, t.descripcion, t.sucursal, t.monto_cargo, t.monto_abono, c.nombre AS cuenta
            FROM transacciones t JOIN cuentas c ON c.id = t.cuenta_id
            WHERE t.categoria = ?
            ORDER BY t.fecha DESC
            """,
            (SIN_CATEGORIA,),
        ).fetchall()
    return [dict(r) for r in rows]


def actualizar_categoria_transaccion(transaccion_id: int, categoria: str):
    """Asigna una categoria a mano. Queda marcada como manual para que 'recategorizar_todas'
    (o volver a categorizar automaticamente) nunca la pise sin que el usuario lo pida."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE transacciones SET categoria = ?, categoria_manual = 1 WHERE id = ?",
            (categoria, transaccion_id),
        )


def recategorizar_todas() -> int:
    """Vuelve a aplicar las reglas de categorizacion a las transacciones categorizadas automaticamente.

    Util cuando se agrega o edita una regla y se quiere que tambien afecte a movimientos
    importados anteriormente. Las transacciones que el usuario categorizo a mano (marcadas
    como categoria_manual) se dejan intactas, para no perder ese trabajo.
    """
    with get_conn() as conn:
        filas = conn.execute("SELECT id, descripcion FROM transacciones WHERE categoria_manual = 0").fetchall()
        cambios = 0
        for f in filas:
            nueva_categoria = categorizar(f["descripcion"])
            cur = conn.execute(
                "UPDATE transacciones SET categoria = ? WHERE id = ? AND categoria IS NOT ?",
                (nueva_categoria, f["id"], nueva_categoria),
            )
            cambios += cur.rowcount
    return cambios
