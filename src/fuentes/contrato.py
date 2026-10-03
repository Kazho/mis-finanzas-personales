"""Contrato de ingesta: la forma UNICA en que cualquier fuente de datos entrega movimientos a la app.

Hoy las fuentes son archivos del banco (PDF, Excel), leidos por los parsers de `src/parser_*.py`. Manana
seran las APIs de movimientos de los bancos (Sistema de Finanzas Abiertas, via el conector del servicio). El
resto de la app (cuentas, panorama, conciliacion, dashboard) no debe saber de donde vino un dato: toda fuente
produce un `LoteImportacion` y `src/ingesta.guardar_lote` lo guarda. Cambiar de PDF a API es escribir un
adaptador nuevo, no tocar la base ni las pantallas.

Reglas de diseño que este contrato hace cumplir (los datos financieros son sensibles y una API es una
frontera de confianza: lo que llega de afuera se valida, no se asume):

  * `LoteImportacion.validar()` rechaza el lote completo si algun dato es inconsistente (montos negativos o
    cargo y abono a la vez, moneda o tipo desconocidos, fechas que no son fechas). Mejor no guardar nada que
    guardar un lote a medias.
  * Cada lote declara su `origen` (tipo y nombre) y cada movimiento puede traer `id_externo`: el identificador
    del banco. Con id externo la carga es idempotente aunque el banco cambie la glosa; sin el se usa
    `hash_dedupe`, que es mas fragil.
  * Los montos se guardan hoy como `float` en pesos (o dolares con 2 decimales). Antes de abrir la app a un
    flujo automatico conviene pasarlos a enteros en la unidad minima: ver docs/arquitectura-nube.md §12.
"""
import math
import re
from dataclasses import dataclass, field
from datetime import date, time, timedelta

from src.cuentas import MONEDAS, TIPOS

# Limites de cordura: lo que llega de afuera no se asume sano. Una fecha absurda (ano 9999) rompe los calculos por mes
# del Dashboard para siempre, y un monto infinito o gigantesco falsea todos los totales.
MAX_MONTO = 1e11              # cien mil millones de pesos
FECHA_MINIMA = date(1990, 1, 1)
DIAS_FUTURO_PERMITIDOS = 400  # cuotas y vencimientos pueden quedar un tiempo adelante
MAX_LARGO_TEXTO = 500
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_NUMERO_CUENTA = re.compile(r"^[\w\-./* ]{1,40}$")

FUENTE_PDF = "archivo_pdf"
FUENTE_XLS = "archivo_xls"
FUENTE_API = "api"
FUENTES = (FUENTE_PDF, FUENTE_XLS, FUENTE_API)

ESTADO_FACTURADO = "facturado"      # ya esta en un estado de cuenta / contabilizado en el banco
ESTADO_POR_FACTURAR = "por_facturar"  # pendiente: provisional hasta que el banco lo contabilice
ESTADOS = (ESTADO_FACTURADO, ESTADO_POR_FACTURAR)

REEMPLAZA_TODOS = "todos"            # el lote trae TODO lo pendiente: reemplaza los provisionales de la cuenta
REEMPLAZA_HASTA_CORTE = "hasta_corte"  # el lote es un estado de cuenta: reemplaza lo pendiente hasta su corte
REEMPLAZOS = (REEMPLAZA_TODOS, REEMPLAZA_HASTA_CORTE, None)


@dataclass(frozen=True)
class OrigenLote:
    """De donde viene el lote. Nunca lleva credenciales ni tokens: es solo una etiqueta para auditar."""
    tipo: str      # FUENTE_PDF | FUENTE_XLS | FUENTE_API
    nombre: str    # nombre del archivo, o del conector/proveedor para una API


@dataclass(frozen=True)
class CuentaFuente:
    numero: str                 # numero visible (ej. "TC-1234"); no es secreto
    tipo: str                   # clave de src.cuentas.TIPOS
    banco: str | None = None    # None si el documento no lo dice (se pregunta al usuario)
    moneda: str = "CLP"
    sufijo_nombre: str = ""     # distingue cuentas del mismo numero en otra moneda, ej. " (USD)"
    id_externo: str | None = None  # identificador de la cuenta en el banco/conector

    def nombre(self, banco: str | None = None) -> str:
        return f"{banco or self.banco or 'Banco sin indicar'} - {self.numero}{self.sufijo_nombre}"


@dataclass
class MovimientoFuente:
    fecha: date
    descripcion: str
    monto_cargo: float = 0.0
    monto_abono: float = 0.0
    saldo: float | None = None
    sucursal: str = ""
    estado: str = ESTADO_FACTURADO
    id_externo: str | None = None   # identificador del movimiento en el banco, si lo trae
    hash_dedupe: str | None = None  # huella para fuentes sin id externo (archivos)


@dataclass(frozen=True)
class SaldoFuente:
    fecha: date
    saldo: float
    hora: time | None = None


@dataclass
class LoteImportacion:
    origen: OrigenLote
    cuenta: CuentaFuente
    movimientos: list[MovimientoFuente]
    periodo_desde: date | None = None
    periodo_hasta: date | None = None
    cartola_numero: str | None = None
    saldo_inicial: float | None = None
    saldo_final: float | None = None
    cuadratura_ok: bool | None = None
    etiqueta_saldo: str = "Saldo final"
    estado_tc: dict | None = None            # cupo, monto facturado, vencimiento (ver db.guardar_estado_tc)
    saldo_snapshot: SaldoFuente | None = None
    reemplaza_provisionales: str | None = None
    advertencias: list[str] = field(default_factory=list)

    def validar(self) -> None:
        """Lanza ValueError con TODOS los problemas encontrados, o no hace nada si el lote es consistente."""
        problemas = []
        if self.origen.tipo not in FUENTES:
            problemas.append(f"origen desconocido: {self.origen.tipo!r}")
        if self.cuenta.tipo not in TIPOS:
            problemas.append(f"tipo de cuenta desconocido: {self.cuenta.tipo!r}")
        if self.cuenta.moneda not in MONEDAS:
            problemas.append(f"moneda desconocida: {self.cuenta.moneda!r}")
        if not self.cuenta.numero or not _NUMERO_CUENTA.match(self.cuenta.numero):
            problemas.append("el numero de cuenta falta o tiene caracteres no permitidos")
        for etiqueta, texto in (("banco", self.cuenta.banco), ("sufijo de cuenta", self.cuenta.sufijo_nombre),
                                ("nombre del origen", self.origen.nombre)):
            if texto and (len(texto) > 120 or _CONTROL.search(texto)):
                problemas.append(f"{etiqueta} demasiado largo o con caracteres de control")
        if self.reemplaza_provisionales not in REEMPLAZOS:
            problemas.append(f"regla de reemplazo desconocida: {self.reemplaza_provisionales!r}")
        if self.reemplaza_provisionales == REEMPLAZA_HASTA_CORTE and self.periodo_hasta is None:
            problemas.append("reemplazar hasta el corte requiere periodo_hasta")
        hoy = date.today()
        vistos_externos = set()
        for i, m in enumerate(self.movimientos, start=1):
            donde = f"movimiento {i} ({m.descripcion!r})"
            if not isinstance(m.fecha, date):
                problemas.append(f"{donde}: la fecha no es una fecha")
            elif not (FECHA_MINIMA <= m.fecha <= hoy + timedelta(days=DIAS_FUTURO_PERMITIDOS)):
                problemas.append(f"{donde}: la fecha {m.fecha} esta fuera del rango razonable")
            if not isinstance(m.descripcion, str):
                problemas.append(f"{donde}: la descripcion no es texto")
            if not all(isinstance(v, (int, float)) and math.isfinite(v) and abs(v) <= MAX_MONTO for v in (m.monto_cargo, m.monto_abono)):
                problemas.append(f"{donde}: monto no numerico, infinito o fuera de rango")
                continue
            if m.saldo is not None and not (isinstance(m.saldo, (int, float)) and math.isfinite(m.saldo) and abs(m.saldo) <= MAX_MONTO):
                problemas.append(f"{donde}: saldo no numerico, infinito o fuera de rango")
            if isinstance(m.descripcion, str) and (len(m.descripcion) > MAX_LARGO_TEXTO or _CONTROL.search(m.descripcion)):
                problemas.append(f"{donde}: descripcion demasiado larga o con caracteres de control")
            if m.monto_cargo < 0 or m.monto_abono < 0:
                problemas.append(f"{donde}: los montos no pueden ser negativos (el signo lo da cargo/abono)")
            if m.monto_cargo and m.monto_abono:
                problemas.append(f"{donde}: no puede ser cargo y abono a la vez")
            if m.estado not in ESTADOS:
                problemas.append(f"{donde}: estado desconocido {m.estado!r}")
            if m.id_externo is not None:
                if m.id_externo in vistos_externos:
                    problemas.append(f"{donde}: id_externo repetido en el mismo lote")
                vistos_externos.add(m.id_externo)
            elif not m.hash_dedupe:
                problemas.append(f"{donde}: sin id_externo ni hash_dedupe, no se podria evitar duplicarlo")
        if problemas:
            raise ValueError("Lote invalido: " + "; ".join(problemas))
