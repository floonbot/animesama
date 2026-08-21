@echo off
setlocal
cd /d "%~dp0.."

rem Signe Authenticode l'exe (ou un fichier passe en argument).
rem   sign.bat                      -> signe AnimeSama\AnimeSama.exe
rem   sign.bat AnimeSama-Setup.exe
rem Selection du certificat (par ordre de priorite) :
rem   set SIGN_PFX=chemin.pfx & set SIGN_PFX_PASS=motdepasse   (certificat fichier)
rem   set SIGN_THUMBPRINT=empreinte_sha1                        (certificat du magasin)
rem   sinon /a : meilleur certificat du magasin courant.

set "TARGET=%~1"
if "%TARGET%"=="" set "TARGET=AnimeSama\AnimeSama.exe"
if not exist "%TARGET%" (
    echo ERREUR : cible introuvable : %TARGET%
    pause
    exit /b 1
)

set "ST="
for %%I in (signtool.exe) do if not defined ST set "ST=%%~$PATH:I"
if not defined ST (
    for /f "delims=" %%I in ('where /r "%ProgramFiles(x86)%\Windows Kits\10\bin" signtool.exe 2^>nul') do set "ST=%%I"
)
if not defined ST (
    echo ERREUR : signtool.exe introuvable. Installe le Windows SDK.
    pause
    exit /b 1
)

set "TS=http://timestamp.digicert.com"
echo Signature de "%TARGET%" avec "%ST%"

if defined SIGN_PFX (
    "%ST%" sign /fd SHA256 /tr %TS% /td SHA256 /f "%SIGN_PFX%" /p "%SIGN_PFX_PASS%" "%TARGET%"
) else if defined SIGN_THUMBPRINT (
    "%ST%" sign /fd SHA256 /tr %TS% /td SHA256 /sha1 %SIGN_THUMBPRINT% "%TARGET%"
) else (
    "%ST%" sign /fd SHA256 /tr %TS% /td SHA256 /a "%TARGET%"
)
if errorlevel 1 (
    echo ECHEC : signature impossible ^(certificat absent ?^).
    pause
    exit /b 1
)

"%ST%" verify /pa "%TARGET%"
echo.
echo OK : "%TARGET%" signe et horodate.
pause
endlocal
