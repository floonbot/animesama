@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0.."

echo ============================================================
echo  AnimeSama - build autonome (tout-en-un)
echo ============================================================
echo.

echo [1/5] Detection de Python...
set "PY="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    python --version >nul 2>&1
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    echo ERREUR : Python introuvable. Installe Python 3.13+ ^(coche "Add Python to PATH"^).
    echo https://www.python.org/downloads/
    pause
    exit /b 1
)
set "PYVER="
for /f "delims=" %%V in ('%PY% -c "import sys; print(sys.version.split()[0])" 2^>nul') do set "PYVER=%%V"
rem Le tampon de build note deja cet interpreteur, mais apres coup : affiche ici,
rem il se compare de visu a celui sous lequel la suite de tests vient de passer.
rem `py -3` suit le Python par defaut de la machine, qui bouge a chaque nouvelle
rem version installee, sans que rien ne le signale.
%PY% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 13) else 1)"
if errorlevel 1 (
    echo ERREUR : Python !PYVER! est trop ancien. Le projet demande 3.13 ou plus
    echo          ^(requires-python dans pyproject.toml^). Un paquet construit avec
    echo          un interpreteur plus ancien planterait a l'execution, pas ici.
    pause
    exit /b 1
)
echo    OK : %PY% -^> Python !PYVER!
echo.

echo [2/5] Prerequis ^(deps + Chromium + binaires + outils de build^)...
set "PREREQS_OK=1"
%PY% -c "import PyInstaller, webview" >nul 2>&1
if errorlevel 1 set "PREREQS_OK="
for %%F in (N_m3u8DL-RE.exe yt-dlp.exe ffmpeg.exe) do if not exist "bin\%%F" set "PREREQS_OK="
if defined PREREQS_OK goto prereqs_done
echo    Installation ^(peut telecharger ~500 Mo au tout premier build^)...
set "ANIMESAMA_NOPAUSE=1"
call "%~dp0install.bat"
if errorlevel 1 (
    echo ERREUR : installation des prerequis echouee.
    pause
    exit /b 1
)
%PY% -m pip install --no-warn-script-location -r requirements/requirements-desktop.txt
if errorlevel 1 (
    echo ERREUR : pip install des dependances desktop ^(requirements-desktop.txt^) a echoue.
    pause
    exit /b 1
)
goto prereqs_verif
:prereqs_done
echo    Deja installes -^> on saute ^(gain de temps^).
:prereqs_verif
set "MISSING="
for %%F in (N_m3u8DL-RE.exe yt-dlp.exe ffmpeg.exe) do if not exist "bin\%%F" set "MISSING=1"
if defined MISSING (
    echo ERREUR : un binaire requis manque dans bin\ ^(lance packaging\install.bat d'abord^).
    pause
    exit /b 1
)
echo    OK
echo    (astuce : set ANIMESAMA_NO_INSTALLER=1 ^(saute l'installeur^) avant de lancer.
echo     ANIMESAMA_HEADLESS_ONLY=1 allege de ~460 Mo mais RETIRE le navigateur
echo     complet : build de TEST uniquement ^(sniff Playwright et connexion HS,
echo     seuls les hotes yt-dlp se telechargent^) - ne pas distribuer.)
echo.

echo [3/5] Bundle front ^(esbuild^)...
set "ESBUILD="
node --version >nul 2>&1
if not errorlevel 1 (
    rem Un depot fraichement clone n'a pas node_modules : il est ignore par git,
    rem et c'est correct. Sans ce rattrapage, « node build.mjs » s'arrete sur un
    rem ERR_MODULE_NOT_FOUND dont la trace Node de quinze lignes masque la seule
    rem action utile. Vecu sur le premier build de la version publique.
    if not exist "node_modules\esbuild" (
        echo    Dependances front absentes ^(depot fraichement clone^) : npm install...
        call npm install --no-audit --no-fund
        if errorlevel 1 (
            echo ERREUR : npm install a echoue - verifie ta connexion, puis relance.
            pause
            exit /b 1
        )
    )
    node build.mjs --dist
    if errorlevel 1 (
        echo ERREUR : le bundle front a echoue.
        pause
        exit /b 1
    )
    set "ESBUILD=node"
)
if not defined ESBUILD (
    if exist "node_modules\@esbuild\win32-x64\esbuild.exe" (
        if exist "web\static\dist" rmdir /s /q "web\static\dist"
        "node_modules\@esbuild\win32-x64\esbuild.exe" web/static/js/app.js --bundle --format=esm --splitting --minify --target=es2020 --outdir=web/static/dist "--chunk-names=chunks/[name]-[hash]" --metafile=web/static/dist/metafile.json
        if errorlevel 1 (
            echo ERREUR : le bundle front a echoue.
            pause
            exit /b 1
        )
        set "ESBUILD=binaire vendorise"
    )
)
if not defined ESBUILD (
    echo ERREUR : ni Node.js ni node_modules\@esbuild\win32-x64\esbuild.exe.
    echo          Installe Node.js ^(https://nodejs.org^) puis relance, ou lance "npm install".
    pause
    exit /b 1
)
if not exist "web\static\dist\app.js" (
    echo ERREUR : web\static\dist\app.js n'a pas ete produit.
    pause
    exit /b 1
)
echo    OK : web\static\dist\app.js ^(%ESBUILD%^)
echo    Tampon de build ^(horodatage + empreinte du front^)...
%PY% packaging\stamp_build.py
if errorlevel 1 (
    echo ERREUR : le tampon de build n'a pas pu etre ecrit. Sans lui, l'application
    echo          packagee ne sait pas dire de quand elle date : c'est precisement
    echo          ce qui rend un installe perime indetectable.
    pause
    exit /b 1
)
echo.

echo [4/5] Construction de l'application a la racine (remplace la precedente)...
echo    Arret des instances en cours ^(sinon l'ancien serveur repond a la place du neuf^)...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /r /c:":7843 .*LISTENING"') do (
    echo       serveur sur le port 7843 : PID %%P
    taskkill /f /pid %%P >nul 2>&1
)
taskkill /f /im AnimeSama.exe >nul 2>&1
if not errorlevel 1 echo       fenetres AnimeSama.exe fermees
timeout /t 2 /nobreak >nul 2>&1
netstat -ano | findstr /r /c:":7843 .*LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo ERREUR : le port 7843 est toujours occupe apres l'arret des instances.
    echo          Un autre programme le tient. Libere-le puis relance : sinon le
    echo          serveur teste ne serait pas celui qu'on vient de construire.
    pause
    exit /b 1
)
if exist AnimeSama.exe del /f /q AnimeSama.exe
if exist AnimeSama rmdir /s /q AnimeSama
rem PyInstaller ecrit par-dessus sans se plaindre : un rmdir en echec produirait un
rem melange d'anciens et de nouveaux fichiers, soit exactement le build perime qu'on
rem cherche a rendre impossible.
if exist AnimeSama (
    echo ERREUR : le dossier AnimeSama\ n'a pas pu etre supprime ^(application encore
    echo          ouverte, ou fichier verrouille par l'antivirus^).
    echo          Ferme AnimeSama.exe et relance : sans cela le build melangerait
    echo          d'anciens fichiers avec les neufs.
    pause
    exit /b 1
)
if exist dist      rmdir /s /q dist
if exist build     rmdir /s /q build
%PY% -m PyInstaller packaging\anime_sama.spec --noconfirm --clean --distpath "%CD%" --workpath build
if errorlevel 1 (
    echo ERREUR : pyinstaller a echoue.
    pause
    exit /b 1
)
if not exist "AnimeSama\AnimeSama.exe" (
    echo ERREUR : l'application n'a pas ete produite.
    pause
    exit /b 1
)
if exist build rmdir /s /q build
echo    OK : AnimeSama\AnimeSama.exe
echo.

echo [5/5] Installeur ^(Inno Setup, installe automatiquement si absent^)...
set "SETUP_OK="
set "APPVER="
for /f "delims=" %%V in ('%PY% -c "from engine.version import APP_VERSION; print(APP_VERSION)" 2^>nul') do set "APPVER=%%V"
if not defined APPVER (
    echo    ATTENTION : version illisible depuis engine\version.py, repli sur celle
    echo    codee dans installer.iss. Les deux peuvent diverger.
)
rem Le saut de l'installeur ne doit PAS sauter le garde-fou : un AnimeSama-Setup.exe
rem d'un build precedent, laisse a cote d'un dossier AnimeSama\ tout neuf, s'installe
rem sans rien dire et remet l'ancienne application en place.
if defined ANIMESAMA_NO_INSTALLER (
    echo    Saute ^(ANIMESAMA_NO_INSTALLER=1^) : seul le dossier AnimeSama\ est produit.
    goto garde_setup_perime
)
call "%~dp0ensure_inno.bat"
rem Bootstrapper WebView2 : installer.iss l'embarque (Source: l.67) et ne le lance
rem qu'en l'absence du runtime. Il est telecharge ici plutot que conserve dans le
rem depot — 1,7 Mo de binaire Microsoft dont les conditions d'installation
rem silencieuse n'ont pas de reponse officielle. L'installeur produit est
rem identique, l'utilisateur final ne voit aucune difference.
if not exist "%~dp0MicrosoftEdgeWebview2Setup.exe" (
    echo    Telechargement du bootstrapper WebView2...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $dest='%~dp0MicrosoftEdgeWebview2Setup.exe'; for($i=1;$i -le 3;$i++){ try { if($i -gt 1){ Write-Host ('   Nouvelle tentative ' + $i + '/3...') }; Invoke-WebRequest -Uri 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $dest -UseBasicParsing; if(Test-Path $dest){ break } } catch { Write-Host ('   Echec reseau : ' + $_.Exception.Message); if($i -lt 3){ Start-Sleep -Seconds 3 } } }"
)
rem Pas de repli silencieux : sans le fichier, ISCC s'arrete sur un Source:
rem introuvable. Mieux vaut un build qui echoue qu'un installeur ampute.
if not exist "%~dp0MicrosoftEdgeWebview2Setup.exe" (
    echo    ERREUR : bootstrapper WebView2 non telecharge - verifie ta connexion.
    echo             Sans lui, l'installeur ne peut pas etre construit.
)
set "ISCC="
for %%P in (
    "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
    "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
    "%ProgramFiles%\Inno Setup 6\ISCC.exe"
) do if exist "%%~P" set "ISCC=%%~P"
if not defined ISCC for /f "delims=" %%I in ('where ISCC.exe 2^>nul') do set "ISCC=%%I"
if defined ISCC (
    if defined APPVER (
        "!ISCC!" /DBundleDir="%CD%\AnimeSama" /DAppVersion="!APPVER!" packaging\installer.iss
    ) else (
        "!ISCC!" /DBundleDir="%CD%\AnimeSama" packaging\installer.iss
    )
    if errorlevel 1 (
        set "ISCC_ECHEC=1"
        echo    Installeur : ECHEC ISCC ^(le dossier AnimeSama\ reste utilisable^).
    ) else (
        set "SETUP_OK=1"
        echo    OK : AnimeSama-Setup.exe
    )
) else (
    echo    Inno Setup indisponible : installeur non genere.
    echo    Distribue directement le dossier AnimeSama\ zippe.
)
:garde_setup_perime
if not defined SETUP_OK if exist AnimeSama-Setup.exe (
    echo    ATTENTION : le AnimeSama-Setup.exe present vient d'un build PRECEDENT.
    if exist AnimeSama-Setup.PERIME.exe del /f /q AnimeSama-Setup.PERIME.exe
    ren AnimeSama-Setup.exe AnimeSama-Setup.PERIME.exe
    echo    Renomme en AnimeSama-Setup.PERIME.exe : ne l'installe pas, il est obsolete.
)
echo.

echo    Comparaison avec l'application deja installee...
%PY% packaging\verifier_installation.py
echo.

rem Un « tout est pret » apres une etape en echec est un mensonge : c'est ce qui a
rem laisse passer une erreur de syntaxe dans installer.iss, l'installeur n'etant
rem plus genere pendant deux builds sans que rien ne le dise clairement.
echo ============================================================
if defined ISCC_ECHEC (
    echo  TERMINE, MAIS L'INSTALLEUR A ECHOUE.
    echo   ISCC s'est arrete sur une erreur - remonte dans cette fenetre pour
    echo   la lire ^(elle donne le fichier et la ligne^). Le dossier AnimeSama\
    echo   est utilisable, l'installeur non.
) else (
    echo  TERMINE - tout est pret.
)
echo   Application : AnimeSama\            ^(a la racine ; zippe-la pour distribuer^)
if defined SETUP_OK echo   Installeur  : AnimeSama-Setup.exe   ^(double-clic sur la machine cible^)
if not defined SETUP_OK echo   Installeur  : NON genere - utilise le dossier AnimeSama\ ci-dessus.
echo.
echo  L'app embarque Chromium + binaires : AUCUNE installation ni reseau
echo  requis sur la machine de l'utilisateur final.
echo.
echo  Note : l'exe n'etant pas signe, SmartScreen peut avertir au 1er lancement.
echo  L'utilisateur clique "Informations complementaires" puis "Executer quand
echo  meme". Pour signer l'exe ^(certificat requis^), vois packaging\sign.bat.
echo ============================================================
echo.
pause
endlocal
