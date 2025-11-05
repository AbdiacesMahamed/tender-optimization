[Setup]
AppName=Tender Optimization
AppVersion=1.0
DefaultDirName={pf}\Tender Optimization
DefaultGroupName=Tender Optimization
OutputBaseFilename=Tender-Optimization-Setup
OutputDir={#SourcePath}\..\release
Compression=lzma
SolidCompression=yes

[Files]
Source: "{#SourcePath}\..\dist\app.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourcePath}\..\desktop_instructions.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Tender Optimization"; Filename: "{app}\app.exe"
Name: "{commondesktop}\Tender Optimization"; Filename: "{app}\app.exe"; Tasks: desktopicon

[Tasks]
Name: desktopicon; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"; Flags: unchecked

[Run]
Filename: "{app}\app.exe"; Description: "Launch Tender Optimization"; Flags: nowait postinstall skipifsilent

; Helper constant to set the path to the .iss file at compile-time
#define SourcePath GetCurrentDir()
