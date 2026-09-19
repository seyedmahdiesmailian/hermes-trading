@echo off
REM Build script for Forwarder Telegram executable

echo ========================================
echo Building Forwarder Telegram Executable
echo ========================================
echo.

REM Check if pyinstaller is installed
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo PyInstaller not found. Installing...
    pip install pyinstaller
    echo.
)

REM Build the executable
echo Building executable...
pyinstaller forwarder.spec

if exist dist\forwarder-telegram.exe (
    echo.
    echo ========================================
    echo BUILD SUCCESSFUL!
    echo ========================================
    echo.
    echo Executable location: dist\forwarder-telegram.exe
    echo Size: 
    dir dist\forwarder-telegram.exe | find "forwarder-telegram.exe"
    echo.
    echo NEXT STEPS:
    echo 1. Copy dist\forwarder-telegram.exe to your deployment folder
    echo 2. Create config.json in the same folder
    echo 3. Run the executable
    echo.
    echo See README-EXE.md for detailed instructions
    echo ========================================
) else (
    echo.
    echo BUILD FAILED!
    echo Check the output above for errors.
)

pause
