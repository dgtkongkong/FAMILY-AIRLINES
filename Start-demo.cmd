@echo off
setlocal
cd /d "%~dp0"
set "CAPTAIN_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%CAPTAIN_PY%" goto bundled
where py >nul 2>nul
if not errorlevel 1 goto standard
echo Please install Python 3.10 or later from python.org.
pause
exit /b 1
:bundled
"%CAPTAIN_PY%" server.py --demo --port 8766
goto done
:standard
py -3 server.py --demo --port 8766
:done
pause
