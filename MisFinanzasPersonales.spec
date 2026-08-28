# -*- mode: python ; coding: utf-8 -*-
"""Build onedir: `pyinstaller MisFinanzasPersonales.spec --noconfirm`.

launcher.py es el unico modulo que PyInstaller analiza/compila de verdad. app.py, vistas/ y
src/ viajan como archivos de datos planos (no compilados) porque Streamlit lee y ejecuta
vistas/*.py directo del disco por su ruta de archivo (st.Page("vistas/....py", ...)), no via
el sistema de imports — si PyInstaller los "congela" dentro del bundle en vez de dejarlos como
archivos reales, Streamlit no los encuentra.

Los paquetes de terceros que SI importa ese codigo (pandas, plotly, pdfplumber, requests) no
los ve el analisis estatico de PyInstaller porque nunca se importan directamente desde
launcher.py, asi que hay que declararlos a mano como hiddenimports/datas. Si al correr el
.exe aparece ModuleNotFoundError o PackageNotFoundError de algun paquete que falta aqui,
agregarlo a las listas de abajo (streamlit en particular hace lookups de version via
importlib.metadata en tiempo de ejecucion, de ahi el copy_metadata).
"""
from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)

PAQUETES_TERCEROS = ("streamlit", "pandas", "plotly", "pdfplumber", "pyarrow", "click", "requests")

datas = [
    ("app.py", "."),
    ("vistas", "vistas"),
    ("src", "src"),
    (".streamlit", ".streamlit"),
    ("VERSION", "."),
]
for paquete in PAQUETES_TERCEROS:
    datas += copy_metadata(paquete)
datas += collect_data_files("streamlit")
datas += collect_data_files("plotly")
datas += collect_data_files("pypdfium2")

binaries = collect_dynamic_libs("pypdfium2")

def _submodulos_sin_tests(paquete):
    # pandas/plotly incluyen su propia suite de tests como submodulos normales -- sin este
    # filtro, collect_submodules() los arrastra todos al build (varios cientos de MB extra
    # que nunca se usan en runtime).
    return [
        m for m in collect_submodules(paquete) if not any(p in ("tests", "test") for p in m.split("."))
    ]


hiddenimports = ["requests", "pypdfium2"]
for paquete in ("streamlit", "pandas", "plotly", "pdfplumber"):
    hiddenimports += _submodulos_sin_tests(paquete)

a = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MisFinanzasPersonales",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/app.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MisFinanzasPersonales",
)
