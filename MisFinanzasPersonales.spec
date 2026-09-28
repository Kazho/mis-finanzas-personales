# -*- mode: python ; coding: utf-8 -*-
"""Build onedir: `pyinstaller MisFinanzasPersonales.spec --noconfirm`.

A diferencia de la version Streamlit anterior, launcher.py y todo lo que importa (paginas_nicegui/,
src/) se compilan normalmente -- NiceGUI arma las paginas con @ui.page() + imports de Python
normales, no lee archivos por ruta como hacia Streamlit con st.Page(), asi que ya no hace falta
declarar esas carpetas como datas planos ni excluirlas del analisis estatico.

pyinstaller-hooks-contrib trae hooks dedicados para nicegui (sus assets estaticos del frontend, ver
hook-nicegui.py) y uvicorn (sus implementaciones de protocolo/loop, que se cargan dinamicamente, ver
hook-uvicorn.py) -- se detectan solos durante el analisis porque el paquete esta instalado, no hace
falta declararlos a mano aca. Si al correr el .exe aparece ModuleNotFoundError/PackageNotFoundError de
algun paquete que falta, agregarlo a las listas de abajo.
"""
from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)

PAQUETES_TERCEROS = ("nicegui", "pandas", "plotly", "pdfplumber", "pyarrow", "requests")

datas = [("VERSION", ".")]
for paquete in PAQUETES_TERCEROS:
    datas += copy_metadata(paquete)
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
for paquete in ("nicegui", "pandas", "plotly", "pdfplumber"):
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
