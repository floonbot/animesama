@echo off
setlocal enabledelayedexpansion

call :trouver_iscc
if defined ISCC goto deja_la

echo    Inno Setup absent : installation automatique ^(~7 Mo, sans admin^)...

where winget >nul 2>&1
if errorlevel 1 goto par_telechargement

winget install --id JRSoftware.InnoSetup --exact --scope user --accept-package-agreements --accept-source-agreements --disable-interactivity
call :trouver_iscc
if defined ISCC goto installe

:par_telechargement
echo    winget indisponible ou en echec : telechargement direct depuis jrsoftware.org...
set "ISTMP=%TEMP%\innosetup-latest.exe"
if exist "!ISTMP!" del /f /q "!ISTMP!" >nul 2>&1
curl -L --fail --silent --show-error -o "!ISTMP!" https://jrsoftware.org/download.php/is.exe
if errorlevel 1 goto echec
"!ISTMP!" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER
del /f /q "!ISTMP!" >nul 2>&1
call :trouver_iscc
if defined ISCC goto installe

:echec
echo    ECHEC : Inno Setup n'a pas pu etre installe automatiquement.
echo    Installe-le a la main : https://jrsoftware.org/isdl.php
endlocal
exit /b 1

:deja_la
echo    Inno Setup : "!ISCC!"
endlocal
exit /b 0

:installe
echo    Inno Setup installe : "!ISCC!"
endlocal
exit /b 0

:trouver_iscc
set "ISCC="
for %%P in (
    "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
    "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
    "%ProgramFiles%\Inno Setup 6\ISCC.exe"
    "%LocalAppData%\Programs\Inno Setup 5\ISCC.exe"
    "%ProgramFiles(x86)%\Inno Setup 5\ISCC.exe"
) do if exist "%%~P" set "ISCC=%%~P"
if not defined ISCC for /f "delims=" %%I in ('where ISCC.exe 2^>nul') do set "ISCC=%%I"
exit /b 0
