@REM /**
@REM * File name: run_carla_gui.bat
@REM * Brief: Carla Windows GUI 启动脚本
@REM * Function:
@REM *     设置本地运行路径并启动 Carla 图形界面
@REM * Author: 咪咕数创工程架构组
@REM *     MGSC AI Software Architecture group
@REM * Version: V2.5.10
@REM * Date: 2026/04/30
@REM */

@echo off
setlocal

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

set "PATH=%ROOT%\bin;C:\ProgramData\mingw64\mingw64\bin;C:\ProgramData\miniconda3;C:\ProgramData\miniconda3\Scripts;%PATH%"

python "%ROOT%\source\frontend\carla" %*
