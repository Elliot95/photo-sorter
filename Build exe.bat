@echo off
cd /d "%~dp0"
python -m pip install --upgrade -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name PhotoSorter --collect-all pillow_heif photo_sorter.pyw
echo.
echo Done - your app is in the "dist" folder.
pause
