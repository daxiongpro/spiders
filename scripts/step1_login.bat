@echo off
chcp 65001 >nul
REM ============================================================
REM  step1 login - double click this file to log in to Douyin
REM  A browser window will open. Scan the QR code with Douyin App.
REM  Login state is stored in output\douyin\edge_profile (scan once).
REM ============================================================
cd /d "%~dp0.."

set PY=C:\ProgramData\miniforge3\python.exe
if not exist "%PY%" set PY=python

"%PY%" -u "scripts\step1_login.py" %*
set RC=%ERRORLEVEL%

echo.
echo ============================================================
if "%RC%"=="0" (
  echo  OK - login saved.
) else (
  echo  NOT logged in. Run again and finish the QR scan.
)
echo ============================================================
pause
