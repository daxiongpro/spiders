@echo off
chcp 65001 >nul
REM ============================================================
REM  step2 - download all videos of one Douyin collection folder
REM
REM  Usage:
REM    double click                  -> pick a folder interactively
REM    step2_download_folder.bat --list
REM    step2_download_folder.bat --check --folder 搞钱
REM    step2_download_folder.bat --folder 搞钱·事业
REM
REM  Needs a previous step1 login (output\douyin\edge_profile).
REM  Already downloaded videos are skipped automatically - it is
REM  safe to run this again and again.
REM ============================================================
cd /d "%~dp0.."

set PY=C:\ProgramData\miniforge3\python.exe
if not exist "%PY%" set PY=python

"%PY%" -u "scripts\step2_download_folder.py" %*
set RC=%ERRORLEVEL%

echo.
echo ============================================================
if "%RC%"=="0" (
  echo  DONE - see output\downloads\ for the videos.
) else (
  echo  FINISHED WITH ERRORS - check the log above.
  echo  RC=1 some videos failed / not logged in
  echo  RC=2 collection name not matched
)
echo ============================================================
pause
