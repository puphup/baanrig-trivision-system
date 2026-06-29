@echo off
REM ============================================================
REM  Build Baanrig-Trivision.exe for offline Windows distribution
REM ============================================================
REM  Prerequisites on the BUILD machine (one time only):
REM    - Windows 10/11
REM    - Python 3.11 or newer  (https://www.python.org/downloads/)
REM    - Internet connection (to pip-install the deps once)
REM
REM  The resulting dist\Baanrig-Trivision.exe needs NEITHER Python NOR
REM  internet on the target machine — copy it over and double-click.

setlocal
cd /d "%~dp0"

echo.
echo [1/4] Creating venv if missing...
if not exist venv\Scripts\python.exe (
    python -m venv venv || (
        echo ERROR: could not create venv. Is Python on PATH?
        pause
        exit /b 1
    )
)

echo.
echo [2/4] Installing dependencies into venv...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip >NUL
python -m pip install -r requirements.txt
python -m pip install pyinstaller

echo.
echo [3/4] Cleaning previous build artifacts...
if exist build  rmdir /s /q build
if exist dist   rmdir /s /q dist

echo.
echo [4/4] Building exe (this takes a minute)...
pyinstaller --clean --noconfirm Pysim.spec
if errorlevel 1 (
    echo.
    echo BUILD FAILED. See errors above.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Done!  Output: dist\Baanrig-Trivision.exe
echo.
echo  Distribute by copying these two files to the target PC:
echo    dist\Baanrig-Trivision.exe
echo    config.json   (optional — exe auto-creates defaults if missing)
echo ============================================================
echo.
pause
endlocal
