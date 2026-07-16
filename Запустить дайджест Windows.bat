@echo off
setlocal

set "SCRIPT=%~dp0scripts\run_digest_windows.ps1"

if not exist "%SCRIPT%" (
  echo Windows launcher script was not found:
  echo %SCRIPT%
  echo.
  pause
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%"
exit /b %ERRORLEVEL%
