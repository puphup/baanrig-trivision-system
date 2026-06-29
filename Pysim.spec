# PyInstaller build spec for Baanrig-Trivision (Windows single-file .exe).
# Build with:  pyinstaller --clean --noconfirm Pysim.spec
# Output:      dist\Baanrig-Trivision.exe
#
# The resulting .exe is fully self-contained — no Python, no internet, no pip
# install needed on the target Windows machine.

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# Pull in everything FastAPI / uvicorn / pymodbus need at runtime. uvicorn picks
# its http and websocket protocol modules dynamically, so collect_submodules
# guarantees they end up in the bundle even though static analysis can't see them.
hidden = (
    # Our own package — defensive; launcher.py already imports app.server, but
    # listing this guards against future modules being added that the launcher
    # doesn't import directly.
    collect_submodules("app")
    + collect_submodules("uvicorn")
    + collect_submodules("uvicorn.protocols")
    + collect_submodules("uvicorn.lifespan")
    + collect_submodules("uvicorn.loops")
    + collect_submodules("websockets")
    + collect_submodules("fastapi")
    + collect_submodules("starlette")
    + collect_submodules("pymodbus")
    + collect_submodules("pymodbus.client")
    + collect_submodules("serial")
    + collect_submodules("serial.tools")
    + [
        "anyio",
        "sniffio",
        "h11",
        "httptools",
        "wsproto",
        "click",
    ]
)

a = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("static", "static"),
        # Ship config.json as the built-in default (50-motor / 3-gateway setup).
        # The loader seeds from this when there's no config.json next to the exe;
        # Save & Apply then writes a persistent copy beside the exe.
        ("config.json", "."),
    ],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Reload-mode-only deps — we never use reload in the frozen build.
        "watchfiles",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="Baanrig-Trivision",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,           # UPX often triggers AV false positives on Windows.
    runtime_tmpdir=None,
    console=True,        # Keep console visible so users see logs / can Ctrl+C cleanly.
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
