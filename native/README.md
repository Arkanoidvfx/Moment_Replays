# Moment Replays native plugin

This directory contains the C++ source and runtime resources for the Windows x64 OBS plugin. To install a binary, use the [release ZIP](https://github.com/Arkanoidvfx/Moment_Replays/releases/tag/v2.0.1).

## Build on Windows

Use Visual Studio 2022 with the C++ desktop tools, the Windows SDK, and CMake 3.24 or newer. Run the commands below from this directory.

1. Extract the [OBS Studio 30.0.0 source](https://github.com/obsproject/obs-studio/archive/refs/tags/30.0.0.zip) to `.deps/obs-studio-30.0.0`, so it contains `libobs/obs-module.h`.
2. Extract the [OBS Qt 6 x64 dependencies](https://github.com/obsproject/obs-deps/releases/download/2023-11-03/windows-deps-qt6-2023-11-03-x64.zip) to `.deps/qt6`, so it contains `lib/cmake/Qt6/Qt6Config.cmake`.
3. Generate import libraries from an installed 64-bit OBS and build the DLL.

```powershell
.\tools\make_implibs.ps1 -ObsBin "$env:ProgramFiles\obs-studio\bin\64bit" -Out .deps\implib
cmake -S . -B build -G "Visual Studio 17 2022" -A x64
cmake --build build --config RelWithDebInfo --target moment-replays
```

The result is `build/RelWithDebInfo/moment-replays.dll`. Run `.\tools\install.ps1` to install it with the data files. Restart OBS to load the plugin.

The plugin is distributed under the [repository license](../LICENSE). The bundled [nlohmann/json](https://github.com/nlohmann/json) header uses the MIT license. Flag artwork comes from [Flagpedia](https://flagpedia.net/download/api).
