# aorus-fan-control.spec — PyInstaller spec for the AORUS 15G Fan Control GUI
#
# Run from the repository root:
#   pyinstaller --clean --noconfirm packaging/aorus-fan-control.spec
#
# Output: dist/aorus-fan-control/
#   ├── aorus-fan-control        ← ELF launcher (console=False, no terminal)
#   └── _internal/
#       ├── p37ec-aorus15g       ← bundled EC binary
#       ├── set-fan-mode.sh      ← bundled fan-mode wrapper
#       └── ...                  ← PySide6, matplotlib, numpy, etc.

block_cipher = None

a = Analysis(
    # Entry point — imports app_logger, ec_controller, fan_curves, settings_dialog
    ['../gui/main.py'],
    # Add gui/ to sys.path so relative imports inside the GUI package resolve
    pathex=['../gui'],
    # Non-Python executables to bundle (PyInstaller preserves their execute bit)
    binaries=[
        ('../p37ec-aorus15g', '.'),   # placed at _internal/p37ec-aorus15g
    ],
    # Non-Python data files (shell script; execute bit set at runtime by ec_controller)
    datas=[
        ('../set-fan-mode.sh', '.'),  # placed at _internal/set-fan-mode.sh
    ],
    # Backends that PyInstaller's matplotlib hook might miss
    hiddenimports=[
        'matplotlib.backends.backend_qtagg',
        'matplotlib.backends.backend_qt5agg',
        'PySide6.QtSvg',
        'PySide6.QtOpenGL',
        'PySide6.QtOpenGLWidgets',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Trim unused heavy packages from the bundle
    excludes=['tkinter', 'PyQt5', 'PyQt6'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='aorus-fan-control',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,              # ← suppresses the terminal window on launch
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='aorus-fan-control',   # → dist/aorus-fan-control/
)
