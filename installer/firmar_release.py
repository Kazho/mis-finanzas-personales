"""Firma de releases con una clave privada que NUNCA se sube a GitHub.

El workflow de CI (.github/workflows/release.yml) publica cada release como BORRADOR: los usuarios no
lo ven hasta que el autor lo firma y lo publica desde su propio PC con este script. Asi, aunque alguien
tomara control de la cuenta de GitHub, no podria distribuir un instalador que las apps instaladas
acepten (ver src/actualizador_core.py).

Uso (requiere `gh` con sesion iniciada):

    py installer/firmar_release.py generar-clave          # una sola vez
    py installer/firmar_release.py firmar v1.2.3          # por cada release
    py installer/firmar_release.py verificar instalador.exe instalador.exe.sig 1.2.3

La clave privada queda cifrada con una frase de paso en ~/.mis-finanzas-firma/. RESPALDALA (por ejemplo
en un pendrive guardado o en tu gestor de contraseñas): si se pierde, las apps instaladas no aceptaran
actualizaciones firmadas con una clave nueva, y tendras que pedir a los usuarios reinstalar a mano.
"""
import argparse
import base64
import getpass
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from src.actualizador_core import _sha256_archivo, firma_valida, mensaje_a_firmar  # noqa: E402

RUTA_CLAVE_DEFAULT = Path.home() / ".mis-finanzas-firma" / "release_ed25519.pem"
ARCHIVO_CON_CLAVE_PUBLICA = RAIZ / "src" / "actualizador_core.py"
LARGO_MIN_FRASE = 12


def _pedir_frase(confirmar: bool) -> bytes:
    frase = getpass.getpass("Frase de paso de la clave de firma: ")
    if confirmar:
        if len(frase) < LARGO_MIN_FRASE:
            sys.exit(f"La frase debe tener al menos {LARGO_MIN_FRASE} caracteres.")
        if frase != getpass.getpass("Repite la frase: "):
            sys.exit("Las frases no coinciden.")
    return frase.encode("utf-8")


def _gh(*args: str) -> None:
    subprocess.run(["gh", *args], check=True, cwd=RAIZ)


def generar_clave(ruta: Path) -> None:
    if ruta.exists():
        sys.exit(f"Ya existe una clave en {ruta}. No se sobrescribe (perderias la capacidad de firmar "
                 "para las apps ya instaladas).")
    privada = Ed25519PrivateKey.generate()
    pem = privada.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(_pedir_frase(confirmar=True)),
    )
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(pem)
    publica_b64 = base64.b64encode(privada.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()

    codigo = ARCHIVO_CON_CLAVE_PUBLICA.read_text(encoding="utf-8")
    nuevo, n = re.subn(r'^CLAVE_PUBLICA_RELEASES: str \| None = .*$',
                       f'CLAVE_PUBLICA_RELEASES: str | None = "{publica_b64}"', codigo, flags=re.M)
    if n != 1:
        sys.exit(f"No encontre la linea CLAVE_PUBLICA_RELEASES en {ARCHIVO_CON_CLAVE_PUBLICA}; clave publica: {publica_b64}")
    ARCHIVO_CON_CLAVE_PUBLICA.write_text(nuevo, encoding="utf-8")
    print(f"Clave privada (cifrada) guardada en: {ruta}")
    print(f"Clave publica escrita en {ARCHIVO_CON_CLAVE_PUBLICA.relative_to(RAIZ)}: {publica_b64}")
    print("\nIMPORTANTE: respalda la clave privada y su frase en un lugar seguro FUERA de este PC y de GitHub.")
    print("La proteccion aplica desde la primera version que incluya esta clave publica: publicala firmada.")


def _cargar_privada(ruta: Path) -> Ed25519PrivateKey:
    if not ruta.exists():
        sys.exit(f"No hay clave en {ruta}. Genera una con: py installer/firmar_release.py generar-clave")
    return serialization.load_pem_private_key(ruta.read_bytes(), password=_pedir_frase(confirmar=False))


def firmar(tag: str, ruta_clave: Path, publicar: bool) -> None:
    version = tag.lstrip("v")
    privada = _cargar_privada(ruta_clave)
    with tempfile.TemporaryDirectory() as tmp:
        _gh("release", "download", tag, "--pattern", "*.exe", "--dir", tmp)
        instaladores = list(Path(tmp).glob("*.exe"))
        if len(instaladores) != 1:
            sys.exit(f"Esperaba 1 instalador en el release {tag}, encontre {len(instaladores)}.")
        instalador = instaladores[0]
        sha = _sha256_archivo(instalador)
        firma_b64 = base64.b64encode(privada.sign(mensaje_a_firmar(version, sha))).decode()
        publica_b64 = base64.b64encode(privada.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
        if not firma_valida(instalador, firma_b64, version, publica_b64):
            sys.exit("La firma recien creada no se pudo verificar; no se sube nada.")
        ruta_firma = instalador.with_name(instalador.name + ".sig")
        ruta_firma.write_text(firma_b64, encoding="ascii")
        _gh("release", "upload", tag, str(ruta_firma), "--clobber")
        print(f"Firmado {instalador.name} (sha256 {sha}).")
    if publicar:
        _gh("release", "edit", tag, "--draft=false")
        print(f"Release {tag} publicado: las apps instaladas ya pueden actualizarse.")


def verificar(instalador: Path, firma: Path, version: str) -> None:
    ok = firma_valida(instalador, firma.read_text(encoding="ascii"), version)
    print("Firma VALIDA" if ok else "Firma INVALIDA (o no hay clave publica configurada)")
    sys.exit(0 if ok else 1)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="comando", required=True)
    g = sub.add_parser("generar-clave", help="crea el par de claves (una sola vez)")
    g.add_argument("--clave", type=Path, default=RUTA_CLAVE_DEFAULT)
    f = sub.add_parser("firmar", help="firma el instalador de un release borrador y lo publica")
    f.add_argument("tag")
    f.add_argument("--clave", type=Path, default=RUTA_CLAVE_DEFAULT)
    f.add_argument("--no-publicar", action="store_true", help="sube la firma pero deja el release como borrador")
    v = sub.add_parser("verificar", help="verifica un instalador descargado")
    v.add_argument("instalador", type=Path)
    v.add_argument("firma", type=Path)
    v.add_argument("version")
    a = p.parse_args()
    if a.comando == "generar-clave":
        generar_clave(a.clave)
    elif a.comando == "firmar":
        firmar(a.tag, a.clave, publicar=not a.no_publicar)
    else:
        verificar(a.instalador, a.firma, a.version)


if __name__ == "__main__":
    main()
