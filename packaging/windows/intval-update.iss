; FILE: packaging/windows/intval-update.iss
; Inno Setup script for the Windows UPDATER: INTVAL-Update-<version>-windows-x64.exe.
; Built by packaging/build_windows.ps1 next to the full installer:
;   ISCC /DAppVersion=1.1.0 /DStageDir=..\..\build\stage-windows /DOutDir=..\..\installers intval-update.iss
;
; What it does on a computer that already has INTVAL:
;   1. finds the existing installation (per-user or for all users) from the
;      uninstall entry the Setup wrote - wherever it was installed;
;   2. backs up everything the user owns - data\ (company lists, watchlists,
;      training data state), output\intel (the research agents' memory and
;      history), agent_settings.yaml, .env, llm_providers.json - into
;      backups\<date>-<old>-to-<new>\ inside the install folder;
;   3. replaces only the program (INTVAL.exe, _internal\, web\dist\, docs);
;   4. runs "INTVAL.exe --migrate", which adds the new version's training
;      companies and settings sections without changing anything the user set.
; It refuses to run where INTVAL is not installed (use the Setup for that) and
; never offers to delete data.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef StageDir
  #define StageDir "..\..\build\stage-windows"
#endif
#ifndef ArtDir
  #define ArtDir "..\..\build\art"
#endif
#ifndef OutDir
  #define OutDir "..\..\installers"
#endif
#define AppName "INTVAL"
#define AppFullName "INTVAL - Intrinsic Value Calculator"
#define AppExe "INTVAL.exe"
; the same id as intval.iss: Windows sees one program, updated in place
#define AppGuid "{6B0F2E5C-9C4E-4E6B-A7C1-3D2B8F1E7A51}"

[Setup]
AppId={{6B0F2E5C-9C4E-4E6B-A7C1-3D2B8F1E7A51}
AppName={#AppFullName}
AppVersion={#AppVersion}
AppVerName={#AppFullName} {#AppVersion}
AppPublisher=Pingaksh Gaur
AppPublisherURL=https://github.com/pingakshgaur/intrinsic-value-calculator
DefaultDirName={code:FoundDir}
DisableDirPage=yes
DisableProgramGroupPage=yes
UsePreviousAppDir=no
DisableWelcomePage=no
DisableReadyPage=no
; a per-user install updates as the user; an all-users one relaunches itself elevated with /ALLUSERS
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutDir}
OutputBaseFilename=INTVAL-Update-{#AppVersion}-windows-x64
SetupIconFile=..\..\assets\intval.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppFullName}
WizardStyle=modern
WizardImageFile={#ArtDir}\wizard-large.bmp,{#ArtDir}\wizard-large@2x.bmp
WizardSmallImageFile={#ArtDir}\wizard-small.bmp,{#ArtDir}\wizard-small@2x.bmp
Compression=lzma2/max
SolidCompression=yes
LZMAUseSeparateProcess=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
SetupAppTitle=Update INTVAL
SetupWindowTitle=Update %1
WelcomeLabel1=Update [name] to version {#AppVersion}
ReadyLabel1=The updater is ready to update INTVAL.
ReadyLabel2a=Your companies, watchlists, research history, training data, settings and API keys are backed up first and kept as they are. Click Update to continue.
ButtonInstall=&Update
FinishedHeadingLabel=INTVAL is up to date
FinishedLabel=INTVAL has been updated to version {#AppVersion}. All of your data was kept, and a backup of it is in the backups folder inside the INTVAL folder.

[InstallDelete]
; the program and the web app are replaced wholesale, so no stale files linger
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\web\dist"

[Files]
; the program, the web app, docs and the factory defaults - never the user's own files
Source: "{#StageDir}\*"; DestDir: "{app}"; Excludes: "agent_settings.yaml,data\*,output\*,.env,llm_providers.json,backups\*"; Flags: ignoreversion recursesubdirs createallsubdirs
; starter lists only where the user has none yet (new lists in a new version)
Source: "{#StageDir}\data\*.csv"; DestDir: "{app}\data"; Flags: onlyifdoesntexist uninsneveruninstall

[Run]
Filename: "{app}\{#AppExe}"; Parameters: "--migrate --no-backup --previous-version ""{code:FoundVersion}"""; WorkingDir: "{app}"; StatusMsg: "Bringing your data up to date with the new version..."; Flags: runhidden waituntilterminated
Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Description: "Open INTVAL now"; Flags: nowait postinstall skipifsilent

[Code]
const
  UninstKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#AppGuid}_is1';

var
  InstDir, InstVer: String;
  InstAllUsers: Boolean;

function Lookup(Root: Integer): Boolean;
var
  V: String;
begin
  Result := RegQueryStringValue(Root, UninstKey, 'InstallLocation', V) and (V <> '');
  if Result then begin
    InstDir := RemoveBackslashUnlessRoot(V);
    if not RegQueryStringValue(Root, UninstKey, 'DisplayVersion', InstVer) then
      InstVer := '';
  end;
end;

function FindInstall(): Boolean;
var
  S: AnsiString;
begin
  InstAllUsers := False;
  Result := Lookup(HKCU);
  if not Result then begin
    Result := Lookup(HKLM);
    InstAllUsers := Result;
  end;
  // the VERSION file is the truth when the uninstall entry is older than the program
  if Result and LoadStringFromFile(InstDir + '\VERSION', S) then
    InstVer := Trim(String(S));
  if InstVer = '' then
    InstVer := 'earlier version';
end;

function FoundDir(Param: String): String;
begin
  Result := InstDir;
end;

function FoundVersion(Param: String): String;
begin
  Result := InstVer;
end;

{ 1.10.0 > 1.9.2: compare dotted numbers part by part }
function VersionPart(var S: String): Integer;
var
  P: Integer;
begin
  P := Pos('.', S);
  if P = 0 then begin
    Result := StrToIntDef(S, 0);
    S := '';
  end else begin
    Result := StrToIntDef(Copy(S, 1, P - 1), 0);
    Delete(S, 1, P);
  end;
end;

function CompareVersions(A, B: String): Integer;
var
  X, Y: Integer;
begin
  Result := 0;
  while (Result = 0) and ((A <> '') or (B <> '')) do begin
    X := VersionPart(A);
    Y := VersionPart(B);
    if X > Y then Result := 1 else if X < Y then Result := -1;
  end;
end;

function InitializeSetup(): Boolean;
var
  Code: Integer;
begin
  Result := False;
  if not FindInstall() then begin
    MsgBox('INTVAL is not installed on this computer, so there is nothing to update.' + #13#10 + #13#10 +
      'Use INTVAL-Setup-{#AppVersion}-windows-x64.exe for a first installation.', mbInformation, MB_OK);
    Exit;
  end;
  if not DirExists(InstDir) then begin
    MsgBox('Windows says INTVAL is installed in' + #13#10 + InstDir + #13#10 +
      'but that folder no longer exists. Use the Setup to install INTVAL again.', mbError, MB_OK);
    Exit;
  end;
  // an installation for all users lives in a protected folder: start again as administrator
  if InstAllUsers and not IsAdminInstallMode() then begin
    if ShellExec('runas', ExpandConstant('{srcexe}'), '/ALLUSERS', '', SW_SHOW, ewNoWait, Code) then
      Exit;
    MsgBox('This copy of INTVAL was installed for all users, so the update needs administrator rights.' + #13#10 +
      'Right-click the updater and choose "Run as administrator".', mbError, MB_OK);
    Exit;
  end;
  if (InstVer <> 'earlier version') and (CompareVersions(InstVer, '{#AppVersion}') >= 0) then
    if MsgBox('INTVAL ' + InstVer + ' is already installed - the same as or newer than this update ({#AppVersion}).' + #13#10 + #13#10 +
      'Replace the program files anyway? Your data is kept either way.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) <> IDYES then
      Exit;
  Result := True;
end;

procedure InitializeWizard();
begin
  WizardForm.WelcomeLabel2.Caption :=
    'INTVAL ' + InstVer + ' was found in:' + #13#10 + InstDir + #13#10 + #13#10 +
    'This updates it to version {#AppVersion}. Only the program is replaced: your companies, watchlists, ' +
    'research history, the agents'' memory, training data, settings and API keys stay exactly as they are, ' +
    'and are backed up first.' + #13#10 + #13#10 + 'Close INTVAL before you continue.';
end;

{ copy a folder and everything under it }
procedure CopyTree(const Src, Dst: String);
var
  R: TFindRec;
begin
  if not DirExists(Src) then
    Exit;
  ForceDirectories(Dst);
  if FindFirst(Src + '\*', R) then
    try
      repeat
        if (R.Name <> '.') and (R.Name <> '..') then begin
          if (R.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
            CopyTree(Src + '\' + R.Name, Dst + '\' + R.Name)
          else
            FileCopy(Src + '\' + R.Name, Dst + '\' + R.Name, False);
        end;
      until not FindNext(R);
    finally
      FindClose(R);
    end;
end;

procedure CopyOne(const Name, Dst: String);
begin
  if FileExists(InstDir + '\' + Name) then
    FileCopy(InstDir + '\' + Name, Dst + '\' + Name, False);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Dst: String;
begin
  if CurStep = ssInstall then begin
    // before a single file is replaced: a full copy of the user's own data
    Dst := InstDir + '\backups\' + GetDateTimeString('yyyymmdd-hhnnss', '-', ':') + '-' + InstVer + '-to-{#AppVersion}';
    StringChangeEx(Dst, ' ', '-', True);
    WizardForm.StatusLabel.Caption := 'Backing up your data...';
    ForceDirectories(Dst);
    CopyTree(InstDir + '\data', Dst + '\data');
    CopyTree(InstDir + '\output\intel', Dst + '\output\intel');
    CopyOne('agent_settings.yaml', Dst);
    CopyOne('.env', Dst);
    CopyOne('llm_providers.json', Dst);
    CopyOne('VERSION', Dst);
  end;
end;
