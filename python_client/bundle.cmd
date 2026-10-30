@echo off
setlocal

if not exist venv\Scripts\activate.bat (
    echo ERROR: venv not found at venv\
    exit /b 1
)

call venv\Scripts\activate.bat

python -m pip install --upgrade pip setuptools wheel build
if errorlevel 1 exit /b 1

python -m build
if errorlevel 1 exit /b 1

echo Press any key to exit...
pause >nul

endlocal
