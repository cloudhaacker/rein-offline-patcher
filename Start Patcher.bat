@echo off
setlocal
title NieR Re[in]carnation Offline Patcher
cd /d "%~dp0"

set "PYVER=3.12.10"
set "PYZIP=python-%PYVER%-embed-amd64.zip"
set "PYURL=https://www.python.org/ftp/python/%PYVER%/%PYZIP%"
set "PYDIR=runtime\python"

if exist "%PYDIR%\python.exe" goto :run

echo First run: getting a portable copy of Python (about 11 MB).
echo It goes into this folder only. Nothing is installed on your PC.
echo.
if not exist "runtime\downloads" mkdir "runtime\downloads"
if not exist "runtime\downloads\%PYZIP%" (
  curl.exe -L --fail -o "runtime\downloads\%PYZIP%" "%PYURL%"
  if errorlevel 1 (
    del "runtime\downloads\%PYZIP%" >nul 2>nul
    echo.
    echo Download failed. Download this file yourself in a web browser:
    echo   %PYURL%
    echo Put it in the runtime\downloads folder, then start the patcher again.
    goto :fail
  )
)
if not exist "%PYDIR%" mkdir "%PYDIR%"
tar.exe -xf "runtime\downloads\%PYZIP%" -C "%PYDIR%"
if errorlevel 1 (
  echo Could not unpack %PYZIP%.
  goto :fail
)
rem Point portable Python at the bundled packages in runtime\libs.
> "%PYDIR%\python312._pth" (
  echo python312.zip
  echo .
  echo ..\libs
)

:run
"%PYDIR%\python.exe" -X utf8 "%~dp0app\patcher.py"
if errorlevel 1 goto :fail
exit /b 0

:fail
echo.
pause
exit /b 1
