# -*- mode: python ; coding: utf-8 -*-
#
# Build de un solo archivo. Si en alguna máquina falla al cargar las DLLs
# nativas (típico en equipos con antivirus corporativo que interfiere con la
# extracción a %TEMP%), usar LaBestia-carpeta.spec, que no extrae
# nada porque deja las DLLs sueltas en una carpeta.

import os
import sys

from PyInstaller.utils.hooks import collect_all

# El recurso de versión del .exe sale de actualizador.VERSION. De ahí lee cada
# PC qué versión hay publicada en la carpeta de actualizaciones.
sys.path.insert(0, SPECPATH)
import actualizador

os.makedirs(os.path.join(SPECPATH, 'build'), exist_ok=True)
_version_info = os.path.join(SPECPATH, 'build', 'version_info.txt')
with open(_version_info, 'w', encoding='utf-8') as f:
    f.write(actualizador.texto_version_info())

# Recolección explícita en vez de confiar sólo en los hooks: numpy y OpenCV
# traen DLLs propias (OpenBLAS, runtime de VC) que si faltan se manifiestan
# recién al importar, ya en la máquina del usuario.
_np_datas, _np_bins, _np_hidden = collect_all('numpy')
_cv_datas, _cv_bins, _cv_hidden = collect_all('cv2')


a = Analysis(
    ['scanner_app.py'],
    pathex=[],
    binaries=_np_bins + _cv_bins,
    datas=_np_datas + _cv_datas,
    hiddenimports=_np_hidden + _cv_hidden + ['win32com.client', 'pythoncom', 'pywintypes', 'fast_io'],
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
    a.binaries,
    a.datas,
    [],
    name='LaBestia',
    version=_version_info,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
