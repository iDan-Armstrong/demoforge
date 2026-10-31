@echo off
rem demoforge control panel launcher - no PowerShell, no console window.
rem Right-click this file -> Send to -> Desktop (create shortcut) to pin it.
cd /d "%~dp0"
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "devtool\launcher.pyw"
) else (
    rem fallback: regular python (a console will appear)
    python "devtool\launcher.pyw"
)
