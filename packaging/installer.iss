; Installeur Inno Setup pour Anime-Sama (bundle one-folder PyInstaller).
; Compilation : ISCC.exe packaging\installer.iss  (ou via packaging\build_installer.bat)
; Installe en PER-USER (pas d'admin) car l'app ecrit data/ downloads/ scans/ a cote de l'exe :
; un dossier sous Program Files serait en lecture seule pour l'utilisateur.
;
; AppId est fige a dessein : toute reinstallation est une mise a jour sur place, et
; {app}\data (reglages, identifiants, historique, base SQLite) survit. C'est le
; comportement voulu ; il est annonce sur la page recapitulative et l'utilisateur ne
; peut effacer ces donnees qu'a la desinstallation, en le demandant explicitement.
;
; AppVersion est injectee par build_exe.bat depuis engine/version.py ; la valeur
; ci-dessous n'est qu'un repli pour une compilation manuelle.

#define AppName "Anime-Sama"
#ifndef AppVersion
  #define AppVersion "2.0.0"
#endif
#define AppExe "AnimeSama.exe"
#ifndef BundleDir
  #define BundleDir ExtractFileDir(RemoveBackslash(SourcePath)) + "\AnimeSama"
#endif

[Setup]
AppId={{A1B2C3D4-E5F6-4A7B-8C9D-0E1F2A3B4C5D}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Anime-Sama
DefaultDirName={localappdata}\Programs\AnimeSama
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..
OutputBaseFilename=AnimeSama-Setup
Compression=lzma2/normal
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
; Chemin relatif au .iss, tous deux dans packaging\. UninstallDisplayIcon pointe
; l'exe, qui porte deja l'icone depuis anime_sama.spec.
SetupIconFile=animesama.ico
UninstallDisplayIcon={app}\{#AppExe}

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer un raccourci sur le Bureau"; GroupDescription: "Raccourcis :"
Name: "startupicon"; Description: "Lancer Anime-Sama au démarrage de Windows"; GroupDescription: "Démarrage :"; Flags: unchecked

; Inno n'efface jamais un fichier absent du nouveau paquet : sans ce nettoyage, une
; installation accumulait indefiniment les vestiges des versions precedentes (une
; page diag.html supprimee depuis, un dossier js/ qui n'est plus livre, un .pyd
; compile pour l'ancienne version de Python a cote du neuf). _internal appartient
; entierement a l'installeur ; data/ downloads/ scans/ sont a cote, pas dedans.
[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
; Excludes data\ : lancer l'application depuis AnimeSama\ y cree une session
; (cookies.enc), des reglages et l'historique. Sans exclusion, l'installeur les
; embarque — il distribue la session de celui qui a construit, et l'installation
; ecrase les donnees de celui qui installe, ce que la fusion de [Code] evite par
; ailleurs.
Source: "{#BundleDir}\*"; DestDir: "{app}"; Excludes: "\data\*,\data"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Désinstaller {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
; Raccourci et non cle Run : Inno le retire tout seul a la desinstallation,
; alors qu'une valeur de registre survivrait et ferait echouer un lancement
; au demarrage suivant, sur un exe qui n'existe plus.
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: startupicon

[Run]
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "Installation du composant d'affichage Microsoft Edge WebView2..."; Check: WebView2Missing; Flags: waituntilterminated
Filename: "{app}\{#AppExe}"; Description: "Lancer {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
var
  DownloadPage: TInputDirWizardPage;

function ReglagesExistants(): String;
begin
  Result := AddBackslash(WizardDirValue) + 'data\user_settings.json';
end;

function EstMiseAJour(): Boolean;
begin
  Result := FileExists(ReglagesExistants());
end;

function WebView2Installed(): Boolean;
var
  pv: String;
begin
  Result :=
    (RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', pv) and (pv <> '') and (pv <> '0.0.0.0')) or
    (RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', pv) and (pv <> '') and (pv <> '0.0.0.0')) or
    (RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', pv) and (pv <> '') and (pv <> '0.0.0.0'));
end;

function WebView2Missing(): Boolean;
begin
  Result := not WebView2Installed();
end;

procedure InitializeWizard;
begin
  { Deux champs sur une seule page : user_settings.json porte downloads_dir ET
    scans_dir, mais l'installeur n'en demandait qu'un — le second restait au
    defaut sans que personne ne l'ait choisi. }
  DownloadPage := CreateInputDirPage(wpSelectDir,
    'Dossiers de telechargement',
    'Ou veux-tu enregistrer ce que tu telecharges ?',
    'Ces deux dossiers peuvent etre changes plus tard dans les reglages.'
    + #13#10 + 'Laisse tel quel si tu ne sais pas.',
    False, '');
  DownloadPage.Add('Animes (videos) :');
  DownloadPage.Add('Scans (manga, .cbz) :');
  DownloadPage.Values[0] := ExpandConstant('{userdocs}\AnimeSama');
  DownloadPage.Values[1] := ExpandConstant('{userdocs}\AnimeSama\scans');
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  { Une mise a jour ne redemande pas le dossier : le reglage vit dans
    user_settings.json, que l'application est seule a ecrire desormais. }
  if PageID = DownloadPage.ID then
    Result := EstMiseAJour();
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo,
  MemoTypeInfo, MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := MemoDirInfo + NewLine + NewLine;
  if EstMiseAJour() then
  begin
    Result := Result + 'Donnees existantes :' + NewLine;
    Result := Result + Space + 'CONSERVEES — reglages, identifiants, historique' + NewLine;
    Result := Result + Space + 'et bibliotheque sont laisses intacts.' + NewLine;
    Result := Result + Space + '(Leur suppression n''est proposee qu''a la desinstallation.)' + NewLine + NewLine;
  end
  else
  begin
    Result := Result + 'Dossiers de telechargement :' + NewLine;
    Result := Result + Space + 'Animes : ' + DownloadPage.Values[0] + NewLine;
    Result := Result + Space + 'Scans  : ' + DownloadPage.Values[1] + NewLine + NewLine;
  end;
  if MemoTasksInfo <> '' then
    Result := Result + MemoTasksInfo + NewLine;
end;

function JsonEscape(const S: String): String;
var
  i: Integer;
  c: Char;
begin
  Result := '';
  for i := 1 to Length(S) do
  begin
    c := S[i];
    if c = '\' then Result := Result + '\\'
    else if c = '"' then Result := Result + '\"'
    else Result := Result + c;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  DlDir: String;
  ScanDir: String;
  DataDir: String;
  Cible: String;
  Json: String;
begin
  if CurStep <> ssPostInstall then
    exit;

  DataDir := ExpandConstant('{app}\data');
  Cible := DataDir + '\user_settings.json';

  { Ce fichier porte aussi qualite, thread_count, scans_dir, notifications,
    son_notif, confirm_suppr, skip_existants et langue_defaut. L'ecrire en
    ecrasement avec le seul downloads_dir detruisait tout le reste a chaque
    reinstallation : on n'y touche donc que s'il n'existe pas. }
  if FileExists(Cible) then
    exit;

  DlDir := DownloadPage.Values[0];
  ScanDir := DownloadPage.Values[1];
  if DlDir = '' then
    exit;

  ForceDirectories(DlDir);
  if ScanDir <> '' then
    ForceDirectories(ScanDir);
  ForceDirectories(DataDir);

  Json := '{' + #13#10 + '  "downloads_dir": "' + JsonEscape(DlDir) + '"';
  if ScanDir <> '' then
    Json := Json + ',' + #13#10 + '  "scans_dir": "' + JsonEscape(ScanDir) + '"';
  Json := Json + #13#10 + '}' + #13#10;
  SaveStringToFile(Cible, Json, False);
end;

// Lecteur JSON minimal : user_settings.json est ecrit par l'application et par
// cet installeur, jamais a la main, donc une seule paire "cle": "valeur" par
// ligne. On ne cherche pas a parser du JSON quelconque — juste a retrouver un
// chemin pour l'afficher et, si l'utilisateur le demande, le supprimer. En cas
// de doute la fonction rend une chaine vide, et l'appelant n'offre pas l'option.
function LireValeurJson(const Fichier, Cle: String): String;
var
  Brut: AnsiString;
  S: String;
  i, j: Integer;
begin
  Result := '';
  if not FileExists(Fichier) then
    exit;
  if not LoadStringFromFile(Fichier, Brut) then
    exit;
  S := String(Brut);
  i := Pos('"' + Cle + '"', S);
  if i = 0 then
    exit;
  S := Copy(S, i + Length(Cle) + 2, Length(S));
  i := Pos(':', S);
  if i = 0 then
    exit;
  S := Copy(S, i + 1, Length(S));
  i := Pos('"', S);
  if i = 0 then
    exit;
  S := Copy(S, i + 1, Length(S));
  j := 1;
  while j <= Length(S) do
  begin
    if (S[j] = '\') and (j < Length(S)) then
    begin
      Result := Result + S[j + 1];
      j := j + 2;
    end
    else if S[j] = '"' then
      break
    else
    begin
      Result := Result + S[j];
      j := j + 1;
    end;
  end;
end;

function AjouterCase(F: TSetupForm; const Texte: String; Y: Integer): TNewCheckBox;
begin
  Result := TNewCheckBox.Create(F);
  Result.Parent := F;
  Result.Left := ScaleX(16);
  Result.Top := ScaleY(Y);
  Result.Width := F.ClientWidth - ScaleX(32);
  Result.Height := ScaleY(17);
  Result.Checked := False;
  Result.Caption := Texte;
end;

function AjouterTexte(F: TSetupForm; const Texte: String; Y: Integer): TNewStaticText;
begin
  Result := TNewStaticText.Create(F);
  Result.Parent := F;
  Result.Left := ScaleX(34);
  Result.Top := ScaleY(Y);
  Result.Width := F.ClientWidth - ScaleX(50);
  Result.AutoSize := False;
  Result.Height := ScaleY(28);
  Result.WordWrap := True;
  Result.Caption := Texte;
end;

// Trois cases independantes plutot qu'un seul Oui/Non. Les trois suppressions
// n'ont ni la meme portee ni la meme gravite : les reglages se refont en une
// minute, le trousseau oblige a se reconnecter, les videos peuvent representer
// des centaines de gigaoctets sur un partage reseau. Les melanger dans une seule
// question obligeait a tout garder ou tout perdre.
function DemanderOptions(const DataDir, DlDir, ScanDir: String;
  var SupprData, SupprTrousseau, SupprMedias: Boolean): Boolean;
var
  F: TSetupForm;
  CbData, CbTrousseau, CbMedias: TNewCheckBox;
  BtnOk, BtnAnnuler: TNewButton;
  Chemins: String;
  Y: Integer;
begin
  SupprData := False;
  SupprTrousseau := False;
  SupprMedias := False;

  F := CreateCustomForm(ScaleX(470), ScaleY(330), False, True);
  try
    F.Caption := 'Anime-Sama — que faut-il supprimer ?';

    Y := 12;
    AjouterTexte(F, 'Tout est conserve par defaut. Coche uniquement ce que tu veux '
      + 'effacer — chaque case est independante.', Y).Left := ScaleX(16);
    Y := Y + 34;

    CbData := AjouterCase(F, 'Reglages, historique et index de la bibliotheque', Y);
    Y := Y + 20;
    AjouterTexte(F, DataDir + #13#10
      + 'Une reinstallation repartirait de zero.', Y);
    Y := Y + 40;

    CbTrousseau := AjouterCase(F, 'Identifiants enregistres dans le trousseau Windows', Y);
    Y := Y + 20;
    AjouterTexte(F, 'Pseudo, mot de passe et cle de chiffrement de la session.' + #13#10
      + 'Ils survivent a la desinstallation tant que cette case reste vide.', Y);
    Y := Y + 40;

    Chemins := '';
    if DlDir <> '' then
      Chemins := DlDir;
    if ScanDir <> '' then
    begin
      if Chemins <> '' then
        Chemins := Chemins + #13#10;
      Chemins := Chemins + ScanDir;
    end;

    CbMedias := nil;
    if Chemins <> '' then
    begin
      CbMedias := AjouterCase(F, 'Videos et scans telecharges  —  IRREVERSIBLE', Y);
      CbMedias.Font.Style := [fsBold];
      Y := Y + 20;
      AjouterTexte(F, Chemins, Y);
      Y := Y + 40;
    end;

    BtnOk := TNewButton.Create(F);
    BtnOk.Parent := F;
    BtnOk.Width := ScaleX(110);
    BtnOk.Height := ScaleY(25);
    BtnOk.Left := F.ClientWidth - ScaleX(232);
    BtnOk.Top := F.ClientHeight - ScaleY(37);
    BtnOk.Caption := 'Desinstaller';
    BtnOk.ModalResult := mrOk;
    BtnOk.Default := True;

    BtnAnnuler := TNewButton.Create(F);
    BtnAnnuler.Parent := F;
    BtnAnnuler.Width := ScaleX(110);
    BtnAnnuler.Height := ScaleY(25);
    BtnAnnuler.Left := F.ClientWidth - ScaleX(116);
    BtnAnnuler.Top := BtnOk.Top;
    BtnAnnuler.Caption := 'Annuler';
    BtnAnnuler.ModalResult := mrCancel;
    BtnAnnuler.Cancel := True;

    Result := F.ShowModal = mrOk;
    if not Result then
      exit;

    SupprData := CbData.Checked;
    SupprTrousseau := CbTrousseau.Checked;
    if CbMedias <> nil then
      SupprMedias := CbMedias.Checked;
  finally
    F.Free;
  end;

  // Seconde confirmation pour le seul choix qu'on ne peut pas defaire. Les deux
  // autres se rattrapent : on se reconnecte, on refait ses reglages.
  if SupprMedias then
    if SuppressibleMsgBox('Supprimer definitivement tout le contenu de :'
         + #13#10 + #13#10 + Chemins + #13#10 + #13#10
         + 'Cette action est irreversible. Continuer ?',
         mbError, MB_YESNO or MB_DEFBUTTON2, IDNO) <> IDYES then
      SupprMedias := False;
end;

// Garde-fou avant tout DelTree : le chemin vient d'un fichier JSON que
// l'utilisateur peut avoir edite. Un downloads_dir valant « D:\ » ou « \\NAS »
// effacerait un disque entier. On refuse la racine d'un lecteur, la racine d'un
// partage reseau, et tout chemin de moins de deux segments.
function CheminEffacable(const Chemin: String): Boolean;
var
  S: String;
  i, Segments: Integer;
begin
  Result := False;
  S := RemoveBackslash(Trim(Chemin));
  if Length(S) < 4 then
    exit;
  if Pos(':', S) = Length(S) then          { « D: » }
    exit;
  Segments := 0;
  for i := 1 to Length(S) do
    if S[i] = '\' then
      Segments := Segments + 1;
  if Copy(S, 1, 2) = '\\' then
  begin
    { \\serveur\partage = 3 antislashs : c'est la racine du partage, on refuse }
    Result := Segments >= 4;
    exit;
  end;
  Result := Segments >= 2;                 { « D:\dossier\sous-dossier » }
end;

procedure EffacerDossier(const Chemin, Libelle: String);
begin
  if (Chemin = '') or (not DirExists(Chemin)) then
    exit;
  if not CheminEffacable(Chemin) then
  begin
    SuppressibleMsgBox('Suppression refusee : « ' + Chemin + ' » est une racine de '
      + 'disque ou de partage. Rien n''a ete efface — supprime le contenu a la '
      + 'main si c''est bien ce que tu voulais.', mbError, MB_OK, IDOK);
    exit;
  end;
  if not DelTree(Chemin, True, True, True) then
    SuppressibleMsgBox('Certains fichiers de ' + Libelle + ' (' + Chemin + ') '
      + 'n''ont pas pu etre supprimes — application encore ouverte, ou partage '
      + 'reseau injoignable. Supprime le dossier a la main si besoin.',
      mbInformation, MB_OK, IDOK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir, Reglages, DlDir, ScanDir, Exe: String;
  SupprData, SupprTrousseau, SupprMedias: Boolean;
  Code: Integer;
begin
  if CurUninstallStep <> usUninstall then
    exit;

  DataDir := ExpandConstant('{app}\data');
  if not DirExists(DataDir) then
    exit;

  // Une desinstallation silencieuse ne supprime rien : personne n'est la pour
  // choisir, et le defaut sur (rien) est le seul qui ne detruise pas de donnees
  // sans mandat. Un MsgBox nu ignorerait /SUPPRESSMSGBOXES et bloquerait le
  // processus pour toujours sur une boite que personne ne regarde.
  if UninstallSilent() then
    exit;

  Reglages := DataDir + '\user_settings.json';
  DlDir := LireValeurJson(Reglages, 'downloads_dir');
  ScanDir := LireValeurJson(Reglages, 'scans_dir');

  if not DemanderOptions(DataDir, DlDir, ScanDir,
                         SupprData, SupprTrousseau, SupprMedias) then
    exit;

  // La cle Fernet vit dans le trousseau Windows, pas dans le dossier
  // d'installation : elle survivrait a la desinstallation. Son nom derive du
  // chemin d'installation, qu'Inno ne sait pas rehacher — c'est donc l'exe qui
  // la retire, tant qu'il existe encore. Il part avant data\, sinon l'exe
  // supprime ne peut plus rien purger.
  // Commentaires en // et non en accolades : une accolade fermante dans le
  // texte (un {app} cite, par exemple) refermerait le commentaire en plein
  // milieu, et c'est exactement ce qui a casse la generation de l'installeur.
  if SupprTrousseau then
  begin
    Exe := ExpandConstant('{app}\{#AppExe}');
    if FileExists(Exe) then
      Exec(Exe, '--purge-keyring', '', SW_HIDE, ewWaitUntilTerminated, Code);
  end;

  if SupprMedias then
  begin
    EffacerDossier(DlDir, 'tes videos');
    EffacerDossier(ScanDir, 'tes scans');
  end;

  if SupprData then
    EffacerDossier(DataDir, 'tes donnees');
end;
