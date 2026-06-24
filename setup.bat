@echo off
setlocal enabledelayedexpansion

:: DPMS Setup — menuconfig-style installer for Windows

title DPMS Setup
cd /d "%~dp0"

:menu
cls
echo ==============================
echo        DPMS Setup
echo ==============================
echo.
echo  1) Install DPMS (full)
echo  2) Install GUI (PyQt5)
echo  3) Set DPMS_ROOT
echo  4) Add default repositories
echo  5) Remove DPMS
echo  6) About
echo  7) Exit
echo.
set /p sel="Select [1-7]: "

if "%sel%"=="1" goto install
if "%sel%"=="2" goto install_gui
if "%sel%"=="3" goto set_root
if "%sel%"=="4" goto add_repos
if "%sel%"=="5" goto remove
if "%sel%"=="6" goto about
if "%sel%"=="7" goto eof
goto menu

:install
echo.
echo Installing DPMS...
python -m pip install --upgrade pip
python -m pip install -e .
echo.
echo Done. You can now run:
echo   dpms          - CLI
echo   dpms --tui    - Textual TUI
echo   dpms-tui      - Textual TUI (direct)
echo   dpms --gui    - Qt GUI (requires PyQt5)
pause
goto menu

:install_gui
echo.
echo Installing GUI dependencies...
python -m pip install PyQt5
echo Done.
pause
goto menu

:set_root
echo.
set /p dpms_root="Enter DPMS_ROOT path (install target directory): "
if defined dpms_root (
    setx DPMS_ROOT "!dpms_root!"
    echo DPMS_ROOT set to !dpms_root!
)
pause
goto menu

:add_repos
echo.
if exist "dpms\repo_list.json" (
    echo repo_list.json already exists.
) else (
    echo {> "dpms\repo_list.json"
    echo     "discovery-core": {>> "dpms\repo_list.json"
    echo         "url": "https://github.com/discoveryos/discovery-packages.git",>> "dpms\repo_list.json"
    echo         "version": "1.0",>> "dpms\repo_list.json"
    echo         "description": "Core Discovery OS packages",>> "dpms\repo_list.json"
    echo         "enabled": true>> "dpms\repo_list.json"
    echo     }>> "dpms\repo_list.json"
    echo }>> "dpms\repo_list.json"
    echo Default repository added.
)
pause
goto menu

:remove
echo.
echo Removing DPMS...
python -m pip uninstall dpms -y
echo Done.
pause
goto menu

:about
cls
echo ==============================
echo        About DPMS
echo ==============================
echo.
echo DPMS - Discovery Package Manager
echo Version 1.1.0
echo.
echo Cross-platform CLI, TUI ^& GUI package manager.
echo.
echo Authors: Archit ^& Kevin (THE Discovery Team)
echo License: MIT
echo.
pause
goto menu

:eof
endlocal
