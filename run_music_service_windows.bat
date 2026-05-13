@REM /**
@REM * File name: run_music_service_windows.bat
@REM * Brief: MGSC DAW Windows 服务启动脚本
@REM * Function:
@REM *     在 Windows 本地环境启动云端 DAW FastAPI 服务
@REM * Author: 软件工程架构组
@REM *     MGSC AI Software Architecture group
@REM * Version: V2.5.10
@REM * Date: 2026/04/30
@REM */

@echo off
setlocal

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

if "%MUSIC_SERVICE_CONFIG%"=="" set "MUSIC_SERVICE_CONFIG=%ROOT%\config\plugins.windows.example.json"
set "PATH=%ROOT%\bin;C:\ProgramData\mingw64\mingw64\bin;C:\ProgramData\miniconda3;C:\ProgramData\miniconda3\Scripts;%PATH%"

python -m uvicorn music_service.main:app --host 0.0.0.0 --port 8000

