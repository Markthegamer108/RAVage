@echo off
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (
    start "" python rav_gui.pyw
) else (
    start "" "%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe" rav_gui.pyw
)
