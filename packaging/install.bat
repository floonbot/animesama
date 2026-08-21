@echo off
cd /d "%~dp0.."

set "PAUSE=pause"
if defined ANIMESAMA_NOPAUSE set "PAUSE=rem"

echo.
echo  Anime Downloader - Installation
echo  ================================
echo.

echo [1/8] Detection de Python...

set "PY="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto py_found
python --version >nul 2>&1
if not errorlevel 1 set "PY=python"

:py_found
if not defined PY (
    echo.
    echo ERREUR : Python non trouve.
    echo Telecharge Python sur https://www.python.org/downloads/
    echo IMPORTANT : coche "Add Python to PATH" pendant l installation.
    echo.
    %PAUSE%
    exit /b 1
)

for /f "delims=" %%v in ('%PY% --version 2^>^&1') do echo    %%v
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3,13) else 1)"
if errorlevel 1 echo    ATTENTION : Python 3.13+ requis ^(pyproject.toml^). L installation continue mais le code n est pas garanti.
echo    OK
echo.

echo [2/8] Mise a jour de pip + installation des dependances...
%PY% -m pip install --no-warn-script-location --upgrade pip
%PY% -m pip install --no-warn-script-location -r requirements/requirements.txt
if errorlevel 1 (
    echo.
    echo ERREUR lors de pip install.
    echo Verifie requirements/requirements.txt et ta connexion.
    %PAUSE%
    exit /b 1
)
%PY% -m pip install --no-warn-script-location -r requirements/requirements-desktop.txt
if errorlevel 1 (
    echo.
    echo ERREUR lors de l installation des dependances desktop ^(pywebview/pyinstaller^).
    echo Verifie requirements/requirements-desktop.txt et ta connexion.
    %PAUSE%
    exit /b 1
)
echo    Installation de Pillow ^(optionnel, jaquettes plus rapides^)...
%PY% -m pip install Pillow >nul 2>&1
if errorlevel 1 (echo    Pillow non installe ^(optionnel^)) else (echo    OK : Pillow)
echo    OK
echo.

echo [3/8] Installation de Playwright ^(Chromium^)...
echo    Cela peut prendre quelques minutes...
%PY% -m playwright install chromium
if errorlevel 1 (
    echo.
    echo ERREUR lors de playwright install.
    %PAUSE%
    exit /b 1
)
echo    OK
echo.

if not exist bin mkdir bin

echo [4/8] Verification de N_m3u8DL-RE ^(-^> bin\^)...
call :dl_github_exe "nilaoda/N_m3u8DL-RE" "*win-x64*.zip" "N_m3u8DL-RE.exe" "N_m3u8DL-RE"
echo.

echo [5/8] Verification de yt-dlp ^(-^> bin\^)...
call :dl_direct "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe" "yt-dlp.exe" "yt-dlp"
echo.

echo [6/8] Verification de ffmpeg ^(-^> bin\^)...
call :dl_github_exe "BtbN/FFmpeg-Builds" "*win64-gpl.zip" "ffmpeg.exe" "ffmpeg"
echo.

echo [7/8] Verification de aria2c ^(optionnel, -^> bin\^)...
call :dl_github_exe "aria2/aria2" "*win-64bit*.zip" "aria2c.exe" "aria2c"
echo.

echo [8/8] Configuration...
if not exist .env (
    echo PORT=7843> .env
    echo    .env cree
) else (
    echo    .env deja present
)
if not exist downloads mkdir downloads
if not exist data      mkdir data
if not exist scans     mkdir scans
echo    OK
echo.

echo  ================================
echo  Installation terminee !
echo.
set "REQ_MISSING="
echo  Outils REQUIS dans bin\ :
if exist bin\N_m3u8DL-RE.exe (echo    [x] N_m3u8DL-RE.exe) else (echo    [ ] N_m3u8DL-RE.exe  - MANQUANT& set "REQ_MISSING=1")
if exist bin\yt-dlp.exe       (echo    [x] yt-dlp.exe)       else (echo    [ ] yt-dlp.exe        - MANQUANT& set "REQ_MISSING=1")
if exist bin\ffmpeg.exe       (echo    [x] ffmpeg.exe)       else (echo    [ ] ffmpeg.exe        - MANQUANT& set "REQ_MISSING=1")
echo  Outil optionnel :
if exist bin\aria2c.exe       (echo    [x] aria2c.exe)       else (echo    [ ] aria2c.exe        - absent ^(optionnel^))
echo.
if defined REQ_MISSING (
    echo  ATTENTION : un outil REQUIS ci-dessus manque - souvent une coupure
    echo      reseau ou la limite GitHub. Relance packaging\install.bat pour reprendre :
    echo      les outils deja presents sont conserves. Sans ces outils, la
    echo      creation de l'application ^(AnimeSama.exe^) echouera.
    echo.
)
echo  Lance:  python desktop.py   ^(ou packaging\build_exe.bat pour creer AnimeSama.exe^)
echo  ================================
echo.

%PAUSE%
exit /b 0

:dl_direct
if exist "bin\%~2" (
    echo    OK deja present : bin\%~2
    goto :eof
)
echo    Telechargement de %~3...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $dest='bin\%~2'; for($i=1;$i -le 3;$i++){ try { if($i -gt 1){ Write-Host ('   Nouvelle tentative ' + $i + '/3...') }; Invoke-WebRequest -Uri '%~1' -OutFile $dest -UseBasicParsing; if(Test-Path $dest){ break } } catch { Write-Host ('   Echec reseau : ' + $_.Exception.Message); if($i -lt 3){ Start-Sleep -Seconds 3 } } }"
if exist "bin\%~2" (echo    OK : bin\%~2) else (echo    ECHEC : %~3 non telecharge - verifie ta connexion puis relance install.bat)
goto :eof

:dl_github_exe
if exist "bin\%~3" (
    echo    OK deja present : bin\%~3
    goto :eof
)
echo    Telechargement de %~4...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $dest=Join-Path (Get-Location) 'bin\%~3'; for($i=1;$i -le 3;$i++){ try { if($i -gt 1){ Write-Host ('   Nouvelle tentative ' + $i + '/3...') }; $r = Invoke-RestMethod -Uri 'https://api.github.com/repos/%~1/releases/latest' -Headers @{'User-Agent'='installer'} -UseBasicParsing; $a = $r.assets | Where-Object { $_.name -like '%~2' } | Select-Object -First 1; if (-not $a) { Write-Host '   Asset introuvable dans la derniere release'; break }; $zip = Join-Path $env:TEMP $a.name; Invoke-WebRequest -Uri $a.browser_download_url -OutFile $zip -UseBasicParsing; $ex = Join-Path $env:TEMP ('ex_' + [guid]::NewGuid().ToString('N')); Expand-Archive -Path $zip -DestinationPath $ex -Force; $f = Get-ChildItem -Path $ex -Recurse -Filter '%~3' | Select-Object -First 1; if ($f) { Copy-Item $f.FullName $dest -Force }; Remove-Item $zip -Force -ErrorAction SilentlyContinue; Remove-Item $ex -Recurse -Force -ErrorAction SilentlyContinue; if(Test-Path $dest){ break } } catch { $code=0; try { $code=[int]$_.Exception.Response.StatusCode } catch {}; if($code -eq 403){ Write-Host '   GitHub limite les telechargements anonymes (60 par heure et par IP).'; Write-Host '   Reessaie dans ~1h ou depuis un autre reseau, puis relance install.bat.'; break }; Write-Host ('   Echec reseau : ' + $_.Exception.Message); if($i -lt 3){ Start-Sleep -Seconds 3 } } }"
if exist "bin\%~3" (echo    OK : bin\%~3) else (echo    ECHEC : %~4 non telecharge - voir le message ci-dessus, puis relance install.bat)
goto :eof
