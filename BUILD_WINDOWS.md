# Building the Windows .exe (offline-friendly)

The target Windows PC does **not** need Python, pip, or an internet connection.
It just needs the single `Baanrig-Trivision.exe` that you build below.

## On the build machine (one-time setup)

You need a Windows PC (or Windows VM) with internet for the *build* step only.
Cross-compiling from macOS/Linux is not supported by PyInstaller — the .exe must
be produced on Windows.

1. Install Python 3.11 or newer from https://www.python.org/downloads/
   (tick **"Add python.exe to PATH"** during install).
2. Copy this whole folder to the Windows machine.
3. Double-click **`build_windows.bat`**.

The script will:

1. Create a local virtual environment (`venv\`).
2. Install `fastapi`, `uvicorn`, `pymodbus`, `pyserial`, and `pyinstaller`.
3. Run PyInstaller against `Pysim.spec`.

When it finishes you'll have:

```
dist\Baanrig-Trivision.exe       (~50-80 MB single file)
```

## Deploying to the offline target PC

Copy these to any folder on the target PC:

- `Baanrig-Trivision.exe`  — the app
- `config.json`            — *optional*; if missing, the app starts with built-in
                              defaults (simulation mode, motors 1 & 2). Edits from
                              the Connection tab in the UI are saved back here, so
                              you can just let the app create it on first save.

Double-click the .exe. You'll see:

- A console window with uvicorn logs (close it to stop the server).
- Your default browser opening to `http://127.0.0.1:8000/`.

That's it — no installer, no admin rights, no internet.

## What gets bundled

Everything needed for offline operation:

- Python interpreter
- FastAPI, uvicorn, websockets, pymodbus, pyserial
- The `static/` folder (HTML + inline CSS + JS — no CDN dependencies)
- The `app/` package (server, sequencer, motor sim, register definitions)

## Tweaks

- **Hide the console window**: in `Pysim.spec`, set `console=False`. You lose log
  visibility — only do this once everything is known-working.
- **Custom icon**: in `Pysim.spec`, change `icon=None` to `icon="myicon.ico"`.
- **Different port**: edit `config.json` after first run, or before deployment.

## Antivirus note

PyInstaller-built .exes occasionally trip Windows SmartScreen or AV heuristics
because they unpack code at runtime. If that happens:

- Right-click → Properties → Unblock (if a "downloaded from internet" badge).
- Or have a Windows admin add an exclusion for the file.
- Code-signing the .exe (paid certificate) eliminates this for good.
