@echo off
setlocal

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

if "%MUSIC_SERVICE_CONFIG%"=="" set "MUSIC_SERVICE_CONFIG=%ROOT%\config\plugins.windows.example.json"
set "PATH=%ROOT%\bin;C:\ProgramData\mingw64\mingw64\bin;C:\ProgramData\miniconda3;C:\ProgramData\miniconda3\Scripts;%PATH%"

python -m uvicorn music_service.main:app --host 0.0.0.0 --port 8000

