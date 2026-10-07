# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_data_files, collect_all

datas = []

def add_data(source, destination):
    if os.path.exists(source):
        datas.append((source, destination))

for folder in ('assets', 'views', 'controllers', 'utils', 'detection', 'models'):
    add_data(folder, folder)

for file_name in (
    'best.pt',
    'yolov8n.pt',
    'Optiflow_Dqn.pth',
    'smart_traffic_dqn.zip',
    'image_mapping.json',
    'accident_image_mapping.json',
    'settings.json',
):
    add_data(file_name, '.')

add_data('.env', '.')
add_data(os.path.join('..', '.env'), '.')
binaries = []
hiddenimports = [
    'utils.paths', 
    'customtkinter', 
    'ultralytics', 
    'torch', 
    'postgrest', 
    'supabase', 
    'realtime',
    'dotenv',
    'uvicorn',
    'fastapi'
]

tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
try:
    tmp_ret = collect_all('ultralytics')
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
except Exception:
    pass

a = Analysis(
    ['app.py'],
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
    name='SystemOptiflow',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SystemOptiflow_Release',
)
