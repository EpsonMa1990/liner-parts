#ifndef AppVersion
  #define AppVersion "0.1.6"
#endif
#define AppName "Agamaship取件表制作工作台"

[Setup]
AppId={{C0301CA0-2B7F-4367-AE35-7927C8D8CB64}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Agamaship contributors
AppPublisherURL=https://github.com/EpsonMa1990/liner-parts
AppSupportURL=https://github.com/EpsonMa1990/liner-parts/issues
AppUpdatesURL=https://github.com/EpsonMa1990/liner-parts/releases
DefaultDirName={localappdata}\Programs\LinerParts
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=LinerParts-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\LinerParts.exe
CloseApplications=yes
RestartApplications=no
LicenseFile=..\LICENSE

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\LinerParts\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\LinerParts.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\LinerParts.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\LinerParts.exe"; Description: "Open {#AppName}"; Flags: nowait postinstall skipifsilent

; User projects live outside {app}; uninstall must never delete the data directory.
