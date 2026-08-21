@echo off
setlocal
cd /d "%~dp0.."

if not exist "AnimeSama\AnimeSama.exe" (
    echo ERREUR : application absente. Lance d'abord packaging\build_exe.bat ^(ou BUILD.bat^).
    pause
    exit /b 1
)
for %%D in (
    "AnimeSama\_internal\bin\ffmpeg.exe"
    "AnimeSama\_internal\bin\yt-dlp.exe"
    "AnimeSama\_internal\bin\N_m3u8DL-RE.exe"
    "AnimeSama\_internal\ms-playwright"
) do if not exist "%%~D" (
    echo ERREUR : application incomplete ^(manque %%~D^). Relance packaging\build_exe.bat.
    pause
    exit /b 1
)

call "%~dp0ensure_inno.bat"
set "ISCC="
for %%P in (
    "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
    "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
    "%ProgramFiles%\Inno Setup 6\ISCC.exe"
    "%LocalAppData%\Programs\Inno Setup 5\ISCC.exe"
    "%ProgramFiles(x86)%\Inno Setup 5\ISCC.exe"
) do if exist "%%~P" set "ISCC=%%~P"
if not defined ISCC (
    for /f "delims=" %%I in ('where ISCC.exe 2^>nul') do set "ISCC=%%I"
)
if not defined ISCC (
    echo ERREUR : Inno Setup ^(ISCC.exe^) introuvable.
    echo Installe-le gratuitement : https://jrsoftware.org/isdl.php
    pause
    exit /b 1
)

set "PY="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    python --version >nul 2>&1
    if not errorlevel 1 set "PY=python"
)
set "APPVER="
if defined PY for /f "delims=" %%V in ('%PY% -c "from engine.version import APP_VERSION; print(APP_VERSION)" 2^>nul') do set "APPVER=%%V"

echo Compilation de l'installeur avec "%ISCC%" ...
if defined APPVER (
    "%ISCC%" /DBundleDir="%CD%\AnimeSama" /DAppVersion="%APPVER%" packaging\installer.iss
) else (
    "%ISCC%" /DBundleDir="%CD%\AnimeSama" packaging\installer.iss
)
if errorlevel 1 (
    echo ECHEC : ISCC a renvoye une erreur.
    pause
    exit /b 1
)

echo.
echo OK -^> AnimeSama-Setup.exe (installeur per-user, sans admin)
pause
endlocal
