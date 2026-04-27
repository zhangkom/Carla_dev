# Carla Windows GUI Build

## Current status

- Built and verified on this machine as a Windows GUI development build.
- Main GUI starts successfully through `source/frontend/carla`.
- Build uses `HAVE_HYLIA=false` to avoid an Ableton Link / MinGW compatibility issue.
- `bridges-plugin` is not part of the current minimal GUI build because this toolchain is missing `libssp` for that target.

## Prerequisites used on this machine

- `MSYS2`: `C:\tools\msys64`
- `MinGW-w64 GCC`: `C:\ProgramData\mingw64\mingw64\bin`
- `Python`: `C:\ProgramData\miniconda3\python.exe`
- Python packages:
  - `PyQt5`
  - `cx_Freeze`

## Build

```powershell
powershell -ExecutionPolicy Bypass -File .\build_windows_gui.ps1
```

Skip clean rebuild:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_windows_gui.ps1 -SkipClean
```

## Run GUI

```bat
run_carla_gui.bat
```

Version / path check:

```bat
run_carla_gui.bat --version
```

## Important outputs

- Backend DLL:
  - `bin\libcarla_standalone2.dll`
- Utils DLL:
  - `bin\libcarla_utils.dll`
- Discovery tool:
  - `bin\carla-discovery-native.exe`
- LV2 UI bridges:
  - `bin\carla-bridge-lv2-gtk2.exe`
  - `bin\carla-bridge-lv2-gtk3.exe`
  - `bin\carla-bridge-lv2-windows.exe`
- Frontend resources:
  - `bin\resources\*`

## Known limitations

- `carlastyle.dll` is not built in the current environment because the C++ Qt5 development toolchain is not installed.
- To keep the GUI runnable, `source\frontend\carla_app.py` now falls back to Qt Fusion style when `carlastyle.dll` is absent.
- Plugin bridge executables from `source/bridges-plugin` are still blocked by `-lssp` in the current MinGW package.
