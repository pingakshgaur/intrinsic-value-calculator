; FILE: packaging/windows/intval.iss
; Inno Setup script for the Windows installer. Built by packaging/build_windows.ps1,
; which passes the version and the staged app folder:
;   ISCC /DAppVersion=1.0.0 /DStageDir=..\..\build\stage-windows /DOutDir=..\..\installers intval.iss

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

[Setup]
AppId={{6B0F2E5C-9C4E-4E6B-A7C1-3D2B8F1E7A51}
AppName={#AppFullName}
AppVersion={#AppVersion}
AppVerName={#AppFullName} {#AppVersion}
AppPublisher=Pingaksh Gaur
AppPublisherURL=https://github.com/pingakshgaur/intrinsic-value-calculator
AppSupportURL=https://github.com/pingakshgaur/intrinsic-value-calculator/issues
; Program Files for everyone, or the user's own programs folder - the user picks,
; and can then choose any folder on the next page
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
AllowNoIcons=yes
DisableProgramGroupPage=no
DisableDirPage=no
DisableWelcomePage=no
UsePreviousAppDir=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutDir}
OutputBaseFilename=INTVAL-Setup-{#AppVersion}-windows-x64
SetupIconFile=..\..\assets\intval.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppFullName}
WizardStyle=modern
WizardImageFile={#ArtDir}\wizard-large.bmp,{#ArtDir}\wizard-large@2x.bmp
WizardSmallImageFile={#ArtDir}\wizard-small.bmp,{#ArtDir}\wizard-small@2x.bmp
Compression=lzma2/max
SolidCompression=yes
LZMAUseSeparateProcess=yes
; a running INTVAL holds its files open; offer to close it first
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
WelcomeLabel2=This will install [name/ver] on your computer.%n%nINTVAL values Indian listed companies with eight models and a 23-agent research team, in a workbench that opens in your browser.%n%nIt runs entirely on this computer. AI providers and Ollama are optional and are set up inside the app.

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "startmenu"; Description: "Add to the &Start menu"; GroupDescription: "Shortcuts:"

[InstallDelete]
; an upgrade replaces the program and the web app wholesale, so no stale files linger
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\web\dist"

[Files]
Source: "{#StageDir}\*"; DestDir: "{app}"; Excludes: "agent_settings.yaml,data\*.csv"; Flags: ignoreversion recursesubdirs createallsubdirs
; the user's own settings and company lists survive an upgrade
Source: "{#StageDir}\agent_settings.yaml"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall
Source: "{#StageDir}\data\*.csv"; DestDir: "{app}\data"; Flags: onlyifdoesntexist uninsneveruninstall

[Dirs]
; INTVAL writes its reports, cache and settings next to itself, so the folder must
; be writable for the people who use it - even inside Program Files
Name: "{app}"; Permissions: users-modify
Name: "{app}\output"; Permissions: users-modify
Name: "{app}\data"; Permissions: users-modify

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; IconFilename: "{app}\{#AppExe}"; Comment: "Open the INTVAL workbench"; Tasks: startmenu
Name: "{group}\INTVAL folder"; Filename: "{app}"; Tasks: startmenu
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"; Tasks: startmenu
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; IconFilename: "{app}\{#AppExe}"; Comment: "Open the INTVAL workbench"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Description: "Launch INTVAL now"; Flags: nowait postinstall skipifsilent

[Code]
var
  RemoveData: Boolean;

function InitializeUninstall(): Boolean;
begin
  RemoveData := False;
  if not UninstallSilent() then
    RemoveData := MsgBox('Also delete your INTVAL data?' + #13#10 + #13#10 +
      'This removes your reports, research history, watchlists, settings and saved API keys.' + #13#10 +
      'Choose No to keep them for a later reinstall.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and RemoveData then
    DelTree(ExpandConstant('{app}'), True, True, True);
end;
