@echo off
rem MomentumAssets: double-click this to open it.
rem It needs Python 3.9 or newer, with tkinter (python.org's includes it). If there's none,
rem it offers to install Python's own install manager, then a Python, and carries on.
setlocal
cd /d "%~dp0"
title MomentumAssets

call :have_python
if errorlevel 1 (
  call :get_python
  if errorlevel 1 goto :end
  call :have_python
  if errorlevel 1 (
    echo.
    echo Python still isn't working. Restart the PC, then double-click Momentum Assets.bat again.
    goto :pause_end
  )
)

call :have_tk
if errorlevel 1 (
  echo This Python has no tkinter, so the window can't open. Running in this window instead.
  echo.
  call py -3 momentum_assets.py build --pause
  goto :end
)

rem The window, with no console behind it. This black window closes now.
start "" pyw -3 momentum_assets.py
goto :end


:have_python
rem 0 if "py" runs a Python 3.9 or newer. Python's install manager would otherwise install
rem one by itself here, unseen, or ask about it: no automatic install, and no keyboard (<nul),
rem so a question fails at once rather than waiting where nobody can see it.
setlocal
set "PYTHON_MANAGER_AUTOMATIC_INSTALL=false"
call py -3 -c "import sys; sys.exit(sys.version_info < (3, 9))" <nul >nul 2>nul
endlocal & exit /b %errorlevel%

:have_tk
setlocal
set "PYTHON_MANAGER_AUTOMATIC_INSTALL=false"
call py -3 -c "import tkinter" <nul >nul 2>nul
endlocal & exit /b %errorlevel%

:get_python
echo MomentumAssets needs Python, which is free, and it isn't on this PC yet.
echo.
set "answer="
set /p "answer=Install it now? It takes a minute or two. Type Y and press Enter (or N): "
if /i not "%answer%"=="Y" (
  echo.
  echo No problem. Get Python from https://www.python.org/downloads/ and double-click this again.
  goto :pause_fail
)
rem Python's install manager may be here already, with no Python yet.
where py >nul 2>nul
if not errorlevel 1 goto :install_python
where winget >nul 2>nul
if errorlevel 1 goto :python_org
echo.
echo Installing the Python install manager from the Microsoft Store ...
call winget install --id 9NQ7512CXL7T --source msstore --accept-source-agreements --accept-package-agreements
if errorlevel 1 goto :python_org
rem The install manager's commands live in WindowsApps; make sure this window can see them.
set "PATH=%PATH%;%LOCALAPPDATA%\Microsoft\WindowsApps"
:install_python
echo.
echo Installing Python ...
call py install 3 -y
if errorlevel 1 goto :python_org
exit /b 0

:python_org
echo.
echo That didn't work here, so the Python download page is opening in your browser.
echo Install Python from it (the big yellow button), then double-click Momentum Assets.bat again.
start "" https://www.python.org/downloads/
goto :pause_fail

:pause_fail
echo.
pause
exit /b 1

:pause_end
echo.
pause
:end
endlocal
