#ifndef PayloadDir
  #error PayloadDir must point to a clean, verified payload directory
#endif
#ifndef MyAppVersion
  #define MyAppVersion "0.4.0"
#endif

[Setup]
AppId=FjordSeed.Converter
AppName=Fjord-konvertering
AppVersion={#MyAppVersion}
AppPublisher=Fjord
AppPublisherURL=https://github.com/qlerup/fjordseed
DefaultDirName={localappdata}\FjordEncode
DefaultGroupName=Fjord-konvertering
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputBaseFilename=Fjord-konvertering-Setup
SetupIconFile={#PayloadDir}\fjord.ico
UninstallDisplayIcon={app}\Fjord-konvertering.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "danish"; MessagesFile: "compiler:Languages\Danish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Opret en genvej på skrivebordet"; GroupDescription: "Genveje:"; Flags: unchecked

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Fjord-konvertering"; Filename: "{app}\Fjord-konvertering.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Fjord-konvertering"; Filename: "{app}\Fjord-konvertering.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\Fjord-konvertering.exe"; Description: "Åbn Fjord-konvertering"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  StartupValue: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'FjordConverter', StartupValue) then
    begin
      StringChangeEx(StartupValue, '"', '', True);
      if CompareText(StartupValue, ExpandConstant('{app}\Fjord-konvertering.exe --background')) = 0 then
        RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'FjordConverter');
    end;
  end;
end;
