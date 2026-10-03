"""Interfaz del CONECTOR: el servicio de suscripcion que consulta las APIs de movimientos de los bancos.

Todavia no existe: este modulo fija el contrato para que el cliente (escritorio o celular) y el servicio se
construyan contra la misma interfaz, y para que lo que llegue del servicio pase por el mismo camino que un
archivo (`LoteImportacion` -> `ingesta.guardar_lote`). Ver docs/arquitectura-nube.md §5 y §12.

Modelo: los datos del usuario viven en su dispositivo (cifrados). El conector es el participante regulado
(PSBI, Ley Fintec / NCG 514 de la CMF) que habla con los bancos; entrega los movimientos al dispositivo y no es
el lugar donde se guardan. Reglas que esta interfaz deja escritas:

  * El usuario es quien otorga, ve y revoca cada consentimiento (con su finalidad, alcance y plazo), y el
    estado del consentimiento viaja con el dato: `Consentimiento`.
  * Se pide solo el alcance necesario (`AlcanceDatos`): para esta app, historial de transacciones y posiciones.
    Nunca se pide ni se guarda la clave bancaria del usuario.
  * Los tokens y credenciales del conector se guardan SOLO dentro de la boveda cifrada del dispositivo, nunca
    en logs ni en archivos planos; `Consentimiento` y `OrigenLote` no llevan secretos a proposito.
  * Revocado el consentimiento, `sincronizar` debe dejar de traer datos de ese banco.
"""
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Protocol

from src.fuentes.contrato import LoteImportacion
from src.ingesta import ResultadoIngesta, guardar_lote


class AlcanceDatos(str, Enum):
    """Conjuntos de informacion del SFA que esta app puede pedir (NCG 514, Tabla 3). Se pide el minimo."""
    HISTORIAL_TRANSACCIONES = "historia_uso_transacciones"
    POSICIONES_HISTORICAS = "posiciones_financieras_historicas"
    PRODUCTOS_VIGENTES = "productos_vigentes"


class EstadoConsentimiento(str, Enum):
    VIGENTE = "vigente"
    SUSPENDIDO = "suspendido"
    CADUCADO = "caducado"
    REVOCADO = "revocado"


@dataclass(frozen=True)
class Consentimiento:
    """Lo que el panel de control debe mostrar de cada consentimiento (NCG 514, seccion III.D.2)."""
    id: str
    institucion: str                       # banco al que se consulta
    finalidad: str
    alcance: tuple[AlcanceDatos, ...]
    otorgado_en: datetime                  # fecha y hora (puede haber varios el mismo dia)
    vence_en: datetime | None
    estado: EstadoConsentimiento


class ConectorNoDisponible(RuntimeError):
    """El servicio de conexion con bancos no esta contratado, configurado o disponible."""


class ClienteConector(Protocol):
    def consentimientos(self) -> list[Consentimiento]: ...

    def iniciar_consentimiento(self, institucion: str, finalidad: str, alcance: tuple[AlcanceDatos, ...],
                               vigencia_dias: int) -> str:
        """Devuelve la URL a la que se envia al usuario para autenticarse en su banco y autorizar."""
        ...

    def revocar(self, consentimiento_id: str) -> None: ...

    def sincronizar(self, desde: date | None = None) -> Iterable[LoteImportacion]:
        """Lotes de movimientos nuevos o actualizados desde `desde`, ya traducidos al contrato de ingesta."""
        ...


class ConectorNoConfigurado:
    """Implementacion por defecto mientras no haya servicio: todo falla con un mensaje claro."""

    def _no(self):
        raise ConectorNoDisponible("La conexion automatica con bancos aun no esta disponible; carga tus archivos.")

    def consentimientos(self) -> list[Consentimiento]:
        return []

    def iniciar_consentimiento(self, *args, **kwargs) -> str:
        self._no()

    def revocar(self, consentimiento_id: str) -> None:
        self._no()

    def sincronizar(self, desde: date | None = None) -> Iterable[LoteImportacion]:
        self._no()


def sincronizar_y_guardar(cliente: ClienteConector, desde: date | None = None) -> list[ResultadoIngesta]:
    """Trae los lotes del conector y los guarda por el mismo camino que un archivo. Un lote invalido se rechaza
    entero y no impide guardar los demas; el error se propaga al final para que no pase en silencio."""
    resultados, errores = [], []
    for lote in cliente.sincronizar(desde):
        try:
            resultados.append(guardar_lote(lote))
        except ValueError as e:
            errores.append(str(e))
    if errores:
        raise ValueError(f"{len(errores)} lote(s) rechazado(s): " + " | ".join(errores))
    return resultados
