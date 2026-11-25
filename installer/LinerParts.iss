#ifndef AppVersion
  #define AppVersion "0.1.4"
#endif
#define AppName "Liner Parts"

[Setup]
AppId={{C0301CA0-2B7F-4367-AE35-7927C8D8CB64}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Liner Parts contributors
AppPublisherURL=https://github.com/EpsonMa1990/liner-parts
AppSupportURL=https://github.com/EpsonMa1990/liner-parts/issues
AppUpdatesURL=https://github.com/EpsonMa1990/liner-parts/releases
DefaultDirName={localappdata}\Programs\LinerParts
DefaultGroupName=Liner Parts
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
Name: "{group}\Liner Parts"; Filename: "{app}\LinerParts.exe"
Name: "{autodesktop}\Liner Parts"; Filename: "{app}\LinerParts.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\LinerParts.exe"; Description: "Open Liner Parts"; Flags: nowait postinstall skipifsilent

; User projects live outside {app}; uninstall must never delete the data directory.
