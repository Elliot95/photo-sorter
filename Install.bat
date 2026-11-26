@echo off
echo Installing what Photo Sorter needs (one time only)...
python -m pip install --upgrade -r "%~dp0requirements.txt"
if errorlevel 1 (
  echo.
  echo Python doesn't seem to be installed.
  echo Get it free from the Microsoft Store: search "Python 3.13", install, then run this again.
) else (
  echo.
  echo All set! Now double-click "Photo Sorter.bat".
)
pause
