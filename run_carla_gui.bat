@echo off
setlocal

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

set "PATH=%ROOT%\bin;C:\ProgramData\mingw64\mingw64\bin;C:\ProgramData\miniconda3;C:\ProgramData\miniconda3\Scripts;%PATH%"

python "%ROOT%\source\frontend\carla" %*
