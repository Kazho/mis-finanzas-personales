"""Lee documentos del banco en un PROCESO APARTE con tiempo limite.

Es la defensa fuerte contra archivos hostiles (ver `src/seguridad_archivos.py`): si un PDF o Excel hace que la
lectura se cuelgue o gaste memoria sin control, el proceso hijo se mata al pasar `TIMEOUT_S` y la app principal
sigue funcionando. Ademas, una falla o explotacion de las librerias que leen esos formatos queda dentro del hijo y
no toca la bobeda ni la base de datos de la app principal.

Protocolo (el hijo es esta misma app ejecutada con otro punto de entrada):
  * El padre escribe en la entrada del hijo una linea JSON con la peticion, un salto de linea y los bytes del archivo.
  * El hijo escribe UNA linea JSON con la respuesta: `{"ok": true, ...}` o `{"ok": false, "codigo": ..., "mensaje": ...}`.
  * Se usa JSON y no pickle a proposito: si el hijo fuera comprometido por un archivo malicioso, el padre no debe
    ejecutar nada que venga de el. Las fechas viajan como {"__fecha__": "AAAA-MM-DD"}.
  * El hijo no recibe credenciales ni acceso a la base; solo el archivo y, si el usuario la dio, la clave del PDF.
  * Lo que el hijo escribe por stderr (avisos internos de las librerias) se descarta: no se muestra al usuario.
"""
import json
import os
import subprocess
import sys
from datetime import date, datetime, time
from pathlib import Path

from src.lectura_documentos import (
    ContrasenaRequerida,
    FormatoNoReconocido,
    leer_documento,
    leer_informe_cmf,
)
from src.seguridad_archivos import ArchivoNoPermitido, validar_archivo

TIMEOUT_S = 30
MAX_SALIDA = 20 * 1024 * 1024
MENSAJE_GENERICO = "No se pudo leer el archivo: puede estar danado o no ser un documento valido."


class LecturaFallida(RuntimeError):
    """La lectura aislada fallo (tiempo excedido, cierre inesperado o error interno). El mensaje es seguro de mostrar."""


# ----------------------------------------------------------------------------------------------------------
# Codificacion JSON (sin pickle)
# ----------------------------------------------------------------------------------------------------------

def _a_json(o):
    if isinstance(o, datetime):
        return {"__fechahora__": o.isoformat()}
    if isinstance(o, date):
        return {"__fecha__": o.isoformat()}
    if isinstance(o, time):
        return {"__hora__": o.isoformat()}
    if hasattr(o, "item"):  # escalares de numpy
        return o.item()
    raise TypeError(f"No se puede serializar {type(o).__name__}")


def _desde_json(d):
    if len(d) == 1:
        (clave, valor), = d.items()
        if clave == "__fecha__":
            return date.fromisoformat(valor)
        if clave == "__fechahora__":
            return datetime.fromisoformat(valor)
        if clave == "__hora__":
            return time.fromisoformat(valor)
    return d


def codificar(obj) -> bytes:
    return json.dumps(obj, default=_a_json).encode("utf-8")


def decodificar(datos: bytes):
    return json.loads(datos.decode("utf-8"), object_hook=_desde_json)


# ----------------------------------------------------------------------------------------------------------
# Lado del padre (la app)
# ----------------------------------------------------------------------------------------------------------

def _raiz() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def _comando() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--lector-aislado"]  # launcher.py atiende este argumento antes que nada
    return [sys.executable, "-m", "src.lectura_aislada"]


def ejecutar_hijo(cmd: list[str], entrada: bytes, timeout: float = TIMEOUT_S, cwd: Path | None = None) -> bytes:
    """Corre `cmd` con `entrada`, y devuelve lo que escribio. Si pasa `timeout` lo mata. Lanza LecturaFallida."""
    try:
        p = subprocess.run(
            cmd, input=entrada, capture_output=True, timeout=timeout, cwd=cwd or _raiz(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        )
    except subprocess.TimeoutExpired as e:
        raise LecturaFallida(
            f"La lectura del archivo tardo mas de {int(timeout)} segundos y se cancelo por seguridad. "
            "Si es un documento real del banco, avisa: no deberia pasar."
        ) from e
    except OSError as e:
        raise LecturaFallida("No se pudo iniciar el lector de archivos.") from e
    if p.returncode != 0:
        raise LecturaFallida("El lector de archivos se cerro de forma inesperada (el archivo puede estar danado o ser malicioso).")
    if len(p.stdout) > MAX_SALIDA:
        raise LecturaFallida("El resultado de la lectura es anormalmente grande; se descarto.")
    return p.stdout


def _llamar(peticion: dict, contenido: bytes) -> dict:
    salida = ejecutar_hijo(_comando(), codificar(peticion) + b"\n" + contenido, timeout=TIMEOUT_S)
    try:
        resp = decodificar(salida.strip().splitlines()[-1])
    except (ValueError, IndexError) as e:
        raise LecturaFallida(MENSAJE_GENERICO) from e
    if resp.get("ok"):
        return resp
    codigo, mensaje = resp.get("codigo"), resp.get("mensaje") or MENSAJE_GENERICO
    if codigo == "contrasena":
        raise ContrasenaRequerida()
    if codigo == "archivo":
        raise ArchivoNoPermitido(mensaje)
    if codigo == "formato":
        raise FormatoNoReconocido(mensaje)
    raise LecturaFallida(mensaje)


def leer_documento_aislado(nombre: str, contenido: bytes, password: str = "") -> tuple[dict, str, str]:
    """Como `lectura_documentos.leer_documento`, pero en un proceso aparte con tiempo limite."""
    validar_archivo(nombre, contenido, ("pdf", "xls"))  # barato: evita lanzar un proceso para algo obviamente malo
    resp = _llamar({"modo": "cartola", "nombre": nombre, "password": password}, contenido)
    return resp["resultado"], resp["tipo_documento"], resp["clase"]


def leer_informe_cmf_aislado(nombre: str, contenido: bytes) -> dict:
    validar_archivo(nombre, contenido, ("pdf",))
    return _llamar({"modo": "cmf", "nombre": nombre}, contenido)["resultado"]


# ----------------------------------------------------------------------------------------------------------
# Lado del hijo
# ----------------------------------------------------------------------------------------------------------

def _atender(peticion: dict, contenido: bytes) -> dict:
    if peticion.get("modo") == "cmf":
        return {"ok": True, "resultado": leer_informe_cmf(peticion["nombre"], contenido)}
    resultado, tipo_documento, clase = leer_documento(peticion["nombre"], contenido, peticion.get("password") or "")
    return {"ok": True, "resultado": resultado, "tipo_documento": tipo_documento, "clase": clase}


def main() -> None:
    """Punto de entrada del hijo: `py -m src.lectura_aislada`, o `launcher.py --lector-aislado` en el .exe."""
    entrada = os.fdopen(0, "rb").read()
    cabecera, _, contenido = entrada.partition(b"\n")
    try:
        respuesta = _atender(decodificar(cabecera), contenido)
    except ContrasenaRequerida:
        respuesta = {"ok": False, "codigo": "contrasena", "mensaje": ""}
    except ArchivoNoPermitido as e:
        respuesta = {"ok": False, "codigo": "archivo", "mensaje": str(e)[:300]}
    except FormatoNoReconocido as e:
        respuesta = {"ok": False, "codigo": "formato", "mensaje": str(e)[:300]}
    except ValueError as e:
        # Los parsers de la app lanzan ValueError con mensajes pensados para el usuario (ej. "No se encontro la
        # fecha de facturacion"); se conservan, acotados.
        respuesta = {"ok": False, "codigo": "interno", "mensaje": str(e)[:300] or MENSAJE_GENERICO}
    except BaseException:  # noqa: BLE001 - nada de lo que falle adentro debe filtrarse al usuario
        respuesta = {"ok": False, "codigo": "interno", "mensaje": MENSAJE_GENERICO}
    salida = os.fdopen(1, "wb")
    salida.write(codificar(respuesta) + b"\n")
    salida.flush()


if __name__ == "__main__":
    main()
