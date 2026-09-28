"""Boveda cifrada: la base de datos completa vive cifrada en disco y solo se descifra en memoria
mientras la app esta desbloqueada.

Diseño (cifrado por sobres, el mismo patron que usan gestores de claves como 1Password/Bitwarden):
- Una clave de datos aleatoria de 256 bits (DEK) cifra la base de datos con AES-256-GCM.
- La DEK nunca se guarda en claro: se guarda envuelta (cifrada) dos veces, una con una clave derivada
  de la contraseña del usuario y otra con una derivada de un codigo de recuperacion que se muestra una
  sola vez. Cambiar la contraseña solo re-envuelve la DEK, no re-cifra los datos.
- Las claves se derivan con scrypt (resistente a fuerza bruta por GPU), con sal aleatoria por clave.
- La cabecera (parametros, sales, DEKs envueltas) va autenticada como "datos adicionales" del cifrado
  de la base: si alguien la altera, el descifrado falla en vez de producir datos corruptos.

Formato del archivo (`finanzas.db.enc`):
    b"MFP1" | largo de la cabecera (4 bytes, big-endian) | cabecera JSON | nonce (12) | datos cifrados

Este mismo archivo es lo que se puede respaldar o sincronizar a la nube tal cual: sin la contraseña o
el codigo de recuperacion es ilegible, incluso para quien lo almacene (cifrado de extremo a extremo).

Si se pierden AMBOS (contraseña y codigo de recuperacion), los datos no se pueden recuperar -- es la
contracara inevitable de que nadie mas pueda leerlos.
"""
import base64
import datetime
import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import struct
import threading
import time
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"MFP1"
VERSION = 1
# scrypt N=2^15, r=8, p=1: ~32 MB de memoria y ~0,1-0,3 s por intento en un PC normal -- imperceptible
# al desbloquear, pero caro para quien pruebe millones de contraseñas.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**15, 8, 1
LARGO_MIN_CONTRASENA = 10
RESPALDOS_A_MANTENER = 7
# Tras varios intentos fallidos seguidos, cada intento nuevo espera cada vez mas (tope 30 s) para frenar
# a quien pruebe contraseñas contra la app en ejecucion. No protege contra ataques al archivo copiado
# (para eso esta scrypt), pero evita que la pantalla de desbloqueo sirva de atajo.
INTENTOS_SIN_ESPERA = 5
ESPERA_MAXIMA_S = 30


class ContrasenaIncorrecta(Exception):
    pass


class ArchivoDanado(Exception):
    pass


def _b64(datos: bytes) -> str:
    return base64.b64encode(datos).decode("ascii")


def _unb64(texto: str) -> bytes:
    return base64.b64decode(texto)


def _derivar(secreto: str, sal: bytes, n: int = SCRYPT_N, r: int = SCRYPT_R, p: int = SCRYPT_P) -> bytes:
    return hashlib.scrypt(secreto.encode("utf-8"), salt=sal, n=n, r=r, p=p, maxmem=128 * 1024 * 1024, dklen=32)


def _normalizar_codigo(codigo: str) -> str:
    """El codigo de recuperacion se acepta con o sin guiones/espacios y en cualquier mayuscula."""
    return "".join(c for c in codigo.upper() if c.isalnum())


def generar_codigo_recuperacion() -> str:
    """24 caracteres base32 (120 bits de entropia), en grupos de 4 para copiarlo a mano sin errores."""
    crudo = base64.b32encode(secrets.token_bytes(15)).decode("ascii")
    return "-".join(crudo[i:i + 4] for i in range(0, len(crudo), 4))


def _envolver(dek: bytes, secreto: str) -> dict:
    sal = secrets.token_bytes(16)
    nonce = secrets.token_bytes(12)
    envuelta = AESGCM(_derivar(secreto, sal)).encrypt(nonce, dek, b"envoltura-dek")
    return {"sal": _b64(sal), "nonce": _b64(nonce), "dek": _b64(envuelta)}


def _desenvolver(sobre: dict, secreto: str, kdf: dict) -> bytes:
    clave = _derivar(secreto, _unb64(sobre["sal"]), kdf["n"], kdf["r"], kdf["p"])
    try:
        return AESGCM(clave).decrypt(_unb64(sobre["nonce"]), _unb64(sobre["dek"]), b"envoltura-dek")
    except InvalidTag as e:
        raise ContrasenaIncorrecta() from e


def _leer(ruta: Path) -> tuple[dict, bytes, bytes, bytes]:
    """Devuelve (cabecera, bytes de cabecera, nonce, datos cifrados)."""
    datos = ruta.read_bytes()
    if datos[:4] != MAGIC:
        raise ArchivoDanado("El archivo no es una boveda de Mis Finanzas Personales.")
    (largo,) = struct.unpack(">I", datos[4:8])
    bytes_cabecera = datos[8:8 + largo]
    cabecera = json.loads(bytes_cabecera)
    resto = datos[8 + largo:]
    return cabecera, bytes_cabecera, resto[:12], resto[12:]


def _escribir(ruta: Path, cabecera: dict, dek: bytes, contenido: bytes) -> None:
    """Escritura atomica: se escribe a un archivo temporal y se reemplaza de una vez, para que un
    corte de luz a mitad de camino nunca deje la boveda a medio escribir."""
    bytes_cabecera = json.dumps(cabecera, separators=(",", ":")).encode("utf-8")
    nonce = secrets.token_bytes(12)
    cifrado = AESGCM(dek).encrypt(nonce, contenido, bytes_cabecera)
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    with open(tmp, "wb") as f:
        f.write(MAGIC + struct.pack(">I", len(bytes_cabecera)) + bytes_cabecera + nonce + cifrado)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, ruta)


def _serializar(conn: sqlite3.Connection) -> bytes:
    return conn.serialize()


def _conexion_desde(contenido: bytes | None) -> sqlite3.Connection:
    # check_same_thread=False: NiceGUI puede atender acciones desde distintos hilos; el acceso se
    # serializa con un lock en src/db.py.
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    if contenido:
        conn.deserialize(contenido)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


class Boveda:
    """Estado de la boveda para este proceso. Una sola instancia (`boveda`) por app."""

    def __init__(self, ruta: Path, ruta_sin_cifrar: Path):
        self.ruta = ruta
        self.ruta_sin_cifrar = ruta_sin_cifrar
        self.ruta_respaldo_sin_cifrar = ruta_sin_cifrar.with_name(ruta_sin_cifrar.name + ".respaldo-sin-cifrar")
        self.dir_respaldos = ruta.parent / "respaldos"
        self._cabecera: dict | None = None
        self._dek: bytes | None = None
        self.conn: sqlite3.Connection | None = None
        # Un solo lock para todo acceso a la conexion y al archivo: src/db.py lo toma en get_conn(), y
        # aca en guardar/bloquear/cambiar, para que bloquear o re-cifrar nunca ocurra a mitad de una
        # escritura de otro hilo.
        self.lock = threading.RLock()
        self._fallos = 0

    def _esperar_si_hay_fallos(self) -> None:
        if self._fallos >= INTENTOS_SIN_ESPERA:
            time.sleep(min(2 ** (self._fallos - INTENTOS_SIN_ESPERA), ESPERA_MAXIMA_S))

    def _desenvolver_contando(self, sobre: dict, secreto: str, kdf: dict) -> bytes:
        self._esperar_si_hay_fallos()
        try:
            dek = _desenvolver(sobre, secreto, kdf)
        except ContrasenaIncorrecta:
            self._fallos += 1
            raise
        self._fallos = 0
        return dek

    # --- estado ---------------------------------------------------------------------------------
    def existe(self) -> bool:
        return self.ruta.exists()

    def hay_base_sin_cifrar(self) -> bool:
        return self.ruta_sin_cifrar.exists()

    def copias_sin_cifrar(self) -> list[Path]:
        """Copias legibles de los datos que quedaron de antes del cifrado. La base original solo cuenta
        si la boveda ya existe (si no, todavia es la base activa pendiente de migrar)."""
        copias = [self.ruta_respaldo_sin_cifrar]
        if self.existe():
            copias.append(self.ruta_sin_cifrar)
        return [p for p in copias if p.exists()]

    def hay_respaldo_sin_cifrar(self) -> bool:
        return bool(self.copias_sin_cifrar())

    def desbloqueada(self) -> bool:
        return self.conn is not None

    # --- ciclo de vida --------------------------------------------------------------------------
    def crear(self, contrasena: str) -> str:
        """Crea la boveda (migrando la base sin cifrar si existe) y devuelve el codigo de recuperacion,
        que hay que mostrarle al usuario UNA vez: no se guarda en ningun lado."""
        if self.existe():
            raise RuntimeError("La boveda ya existe.")
        validar_contrasena(contrasena)
        codigo = generar_codigo_recuperacion()
        dek = secrets.token_bytes(32)
        cabecera = {
            "version": VERSION,
            "kdf": {"algoritmo": "scrypt", "n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P},
            "contrasena": _envolver(dek, contrasena),
            "recuperacion": _envolver(dek, _normalizar_codigo(codigo)),
        }

        if self.hay_base_sin_cifrar():
            origen = sqlite3.connect(self.ruta_sin_cifrar)
            conn = _conexion_desde(None)
            origen.backup(conn)
            origen.close()
        else:
            conn = _conexion_desde(None)

        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        _escribir(self.ruta, cabecera, dek, _serializar(conn))
        # Se verifica que la boveda recien escrita se pueda leer antes de tocar el original.
        self._abrir_con_dek(dek)
        conn.close()
        if self.hay_base_sin_cifrar():
            # No se borra: queda como respaldo hasta que el usuario confirme que todo esta bien y lo
            # elimine desde la app (ver eliminar_respaldo_sin_cifrar). Si Windows no deja renombrarlo
            # (otro programa lo tiene abierto), se deja donde esta: copias_sin_cifrar() lo detecta igual.
            try:
                os.replace(self.ruta_sin_cifrar, self.ruta_respaldo_sin_cifrar)
            except OSError:
                pass
        return codigo

    def desbloquear(self, contrasena: str) -> None:
        """Si ya esta desbloqueada (otro navegador), solo verifica la contraseña: re-abrir la base
        reemplazaria la conexion que otras paginas estan usando."""
        if self.desbloqueada():
            self._desenvolver_contando(self._cabecera["contrasena"], contrasena, self._cabecera["kdf"])
            return
        cabecera, _, _, _ = _leer(self.ruta)
        dek = self._desenvolver_contando(cabecera["contrasena"], contrasena, cabecera["kdf"])
        with self.lock:
            self._abrir_con_dek(dek)
        self.respaldar()

    def recuperar(self, codigo: str, nueva_contrasena: str) -> None:
        """Desbloquea con el codigo de recuperacion y fija una contraseña nueva."""
        validar_contrasena(nueva_contrasena)
        cabecera, _, _, _ = _leer(self.ruta)
        dek = self._desenvolver_contando(cabecera["recuperacion"], _normalizar_codigo(codigo), cabecera["kdf"])
        with self.lock:
            if not self.desbloqueada():
                self._abrir_con_dek(dek)
            self._cabecera["contrasena"] = _envolver(dek, nueva_contrasena)
            self.guardar()

    def cambiar_contrasena(self, actual: str, nueva: str) -> None:
        validar_contrasena(nueva)
        # Verificacion (con su posible espera por fallos) fuera del lock, para no congelar la app.
        self._desenvolver_contando(self._cabecera["contrasena"], actual, self._cabecera["kdf"])
        with self.lock:
            self._cabecera["contrasena"] = _envolver(self._dek, nueva)
            self.guardar()

    def bloquear(self) -> None:
        with self.lock:
            if self.conn is not None:
                self.guardar()
                self.conn.close()
            self.conn = None
            self._dek = None
            self._cabecera = None

    def _abrir_con_dek(self, dek: bytes) -> None:
        cabecera, bytes_cabecera, nonce, cifrado = _leer(self.ruta)
        try:
            contenido = AESGCM(dek).decrypt(nonce, cifrado, bytes_cabecera)
        except InvalidTag as e:
            raise ArchivoDanado("La boveda esta dañada o fue modificada.") from e
        self.conn = _conexion_desde(contenido)
        self._cabecera = cabecera
        self._dek = dek

    # --- persistencia ---------------------------------------------------------------------------
    def guardar(self) -> None:
        with self.lock:
            if self.conn is None:
                raise RuntimeError("La boveda esta bloqueada.")
            _escribir(self.ruta, self._cabecera, self._dek, _serializar(self.conn))

    def respaldar(self) -> Path | None:
        """Un respaldo por dia (el archivo ya cifrado, tal cual), manteniendo los ultimos 7. Como van
        cifrados, esta carpeta se puede sincronizar a OneDrive/Google Drive sin exponer nada."""
        if not self.existe():
            return None
        self.dir_respaldos.mkdir(parents=True, exist_ok=True)
        destino = self.dir_respaldos / f"finanzas-{datetime.date.today().isoformat()}.db.enc"
        if not destino.exists():
            shutil.copy2(self.ruta, destino)
        respaldos = sorted(self.dir_respaldos.glob("finanzas-*.db.enc"))
        for viejo in respaldos[:-RESPALDOS_A_MANTENER]:
            viejo.unlink()
        return destino

    def eliminar_respaldo_sin_cifrar(self) -> None:
        """Borra la copia SIN cifrar que quedo de la migracion. Se sobrescribe con ceros antes de
        borrarla para que no quede legible en el disco (con la salvedad de SSDs, ver LIMITACIONES)."""
        for ruta in self.copias_sin_cifrar():
            largo = ruta.stat().st_size
            with open(ruta, "r+b") as f:
                f.write(b"\0" * largo)
                f.flush()
                os.fsync(f.fileno())
            ruta.unlink()


def validar_contrasena(contrasena: str) -> None:
    if len(contrasena or "") < LARGO_MIN_CONTRASENA:
        raise ValueError(f"La contraseña debe tener al menos {LARGO_MIN_CONTRASENA} caracteres.")
