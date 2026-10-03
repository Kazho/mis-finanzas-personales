"""Defensas contra archivos hostiles en la carga de cartolas.

Los documentos del banco son datos que vienen de afuera: un PDF o Excel "del banco" puede llegar por un correo
falso. Esta app corre en tu equipo, asi que el riesgo principal no es robar datos sino **dejarla inutilizable**
(consumir CPU y memoria hasta congelarla) o aprovechar una falla de las librerias que leen esos formatos.

Lo que se comprobo (ver tests/test_seguridad_archivos.py): un PDF valido de solo 7 KB, que se expande a 2 MB de
contenido, tarda ~30 s en leerse y usa ~490 MB de memoria; el costo crece de forma lineal, asi que uno de 30 KB
congelaria la app por minutos. Por eso hay tres capas, de la mas barata a la mas fuerte:

  1. `validar_archivo`: tamaño maximo y tipo REAL por su contenido (no solo por la extension).
  2. `inspeccionar_pdf`: rechaza de inmediato los PDF cuyo contenido comprimido se expande de forma absurda. Los PDF
     reales de bancos no pasan de ~400 KB expandidos; el tope es 4 MB por flujo. Esta capa NO basta sola: un PDF
     cifrado esconde su contenido hasta abrirlo, y se pueden encadenar filtros.
  3. `src/lectura_aislada.py`: la lectura corre en un proceso aparte con tiempo limite, y se mata si se pasa. Es la
     defensa que no depende de adivinar como se esconde el ataque.
"""
import os
import re
import zlib

MAX_BYTES = 25 * 1024 * 1024
MAX_PAGINAS_PDF = 200
MAX_FLUJO_EXPANDIDO = 4 * 1024 * 1024        # un flujo de contenido de pagina
MAX_IMAGEN_EXPANDIDA = 64 * 1024 * 1024      # las imagenes no se interpretan, solo se decodifican si se piden
MAX_TOTAL_EXPANDIDO = 16 * 1024 * 1024
MAX_LARGO_NOMBRE = 120

MAGIC_PDF = b"%PDF-"
MAGIC_OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class ArchivoNoPermitido(ValueError):
    """El archivo se rechaza antes de leerlo. El mensaje es seguro de mostrar al usuario."""


def tipo_por_contenido(contenido: bytes) -> str | None:
    """'pdf' o 'xls' segun los primeros bytes (la firma real del formato), o None."""
    if MAGIC_PDF in contenido[:1024]:  # algunos PDF traen basura corta antes de la firma
        return "pdf"
    if contenido.startswith(MAGIC_OLE2):
        return "xls"
    return None


def nombre_seguro(nombre: str | None) -> str:
    """Nombre de archivo apto para guardar y mostrar: sin carpetas, sin caracteres de control, de largo acotado."""
    base = os.path.basename((nombre or "").replace("\\", "/")) or "archivo"
    base = _CONTROL.sub("", base).strip() or "archivo"
    return base[:MAX_LARGO_NOMBRE]


def validar_archivo(nombre: str, contenido: bytes, permitidos: tuple[str, ...] = ("pdf", "xls")) -> str:
    """Comprueba tamaño, extension y firma. Devuelve el tipo ('pdf' | 'xls') o lanza ArchivoNoPermitido."""
    if not contenido:
        raise ArchivoNoPermitido("El archivo esta vacio.")
    if len(contenido) > MAX_BYTES:
        raise ArchivoNoPermitido(f"El archivo es demasiado grande (maximo {MAX_BYTES // (1024 * 1024)} MB).")
    ext = nombre.rsplit(".", 1)[-1].lower() if "." in nombre else ""
    if ext not in permitidos:
        raise ArchivoNoPermitido(f"Tipo de archivo no permitido. Se aceptan: {', '.join('.' + p for p in permitidos)}.")
    tipo = tipo_por_contenido(contenido)
    if tipo != ext:
        raise ArchivoNoPermitido("El contenido del archivo no corresponde a su extension; puede estar danado o no ser lo que dice ser.")
    return tipo


def inspeccionar_pdf(contenido: bytes) -> None:
    """Rechaza PDF con demasiadas paginas o con flujos comprimidos que se expanden de forma desproporcionada.

    Solo revisa flujos Flate sin cifrar (el caso comun); lo demas queda cubierto por el tiempo limite de la lectura
    aislada. Descomprime con tope de salida, asi que inspeccionar una bomba nunca consume mas que el tope."""
    paginas = len(re.findall(rb"/Type\s*/Page(?![A-Za-z])", contenido))
    if paginas > MAX_PAGINAS_PDF:
        raise ArchivoNoPermitido(f"El PDF tiene demasiadas paginas (maximo {MAX_PAGINAS_PDF}).")

    total = 0
    pos = 0
    while True:
        m = re.compile(rb"stream\r?\n").search(contenido, pos)
        if not m:
            break
        fin = contenido.find(b"endstream", m.end())
        if fin < 0:
            break
        pos = fin + 9
        encabezado = contenido[max(0, contenido.rfind(b"obj", 0, m.start())):m.start()]
        es_imagen = b"/Image" in encabezado
        tope = MAX_IMAGEN_EXPANDIDA if es_imagen else MAX_FLUJO_EXPANDIDO
        try:
            salida = zlib.decompressobj().decompress(contenido[m.end():fin], tope + 1)
        except zlib.error:
            continue  # no es Flate (u otro filtro): lo cubre el tiempo limite
        if len(salida) > tope:
            raise ArchivoNoPermitido("El PDF contiene datos comprimidos de tamaño anormal; se rechazo por seguridad.")
        if not es_imagen:
            total += len(salida)
            if total > MAX_TOTAL_EXPANDIDO:
                raise ArchivoNoPermitido("El PDF contiene demasiado contenido; se rechazo por seguridad.")
