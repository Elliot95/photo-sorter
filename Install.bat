@echo off
echo Installing what Photo Sorter needs (one time only)...
where python >nul 2>nul
if errorlevel 1 goto nopython
python -m pip install --upgrade -r "%~dp0requirements.txt"
if errorlevel 1 goto nopython
echo.
echo All set! Now double-click "Photo Sorter.bat".
pause
exit /b

:nopython
echo.
echo Python isn't installed yet. Opening the download page for you...
echo   https://www.python.org/downloads/
echo.
echo Click "Download Python", run it, and TICK "Add python.exe to PATH".
echo Then run this Install.bat again.
start "" https://www.python.org/downloads/
pause
