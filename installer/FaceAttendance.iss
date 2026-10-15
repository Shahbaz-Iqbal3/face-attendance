; Inno Setup script - builds FaceAttendance-Setup.exe from the PyInstaller output in ..\dist\FaceAttendance
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{B3C1A5E2-6F0D-4C57-9B1B-FA7A7E0D2025}
AppName=Face Attendance
AppVersion={#AppVersion}
DefaultDirName={autopf}\Face Attendance
DefaultGroupName=Face Attendance
DisableProgramGroupPage=yes
OutputDir=..\installer-out
OutputBaseFilename=FaceAttendance-Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
UninstallDisplayName=Face Attendance
CloseApplications=yes

[Tasks]
Name: "autostart"; Description: "Start Face Attendance automatically when Windows starts (recommended)"; GroupDescription: "Startup:"
Name: "kioskstart"; Description: "Also open the kiosk screen full-screen at login (tick this on the PC with the camera)"; GroupDescription: "Startup:"; Flags: unchecked
Name: "desktopicons"; Description: "Create desktop shortcuts"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\FaceAttendance\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "installed.flag"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
; all data (database, backups, logs) lives here, writable by every user
Name: "{commonappdata}\FaceAttendance"; Permissions: users-modify

[Icons]
Name: "{group}\Admin panel"; Filename: "{app}\FaceAttendance.exe"; Parameters: "--open admin"; Flags: runminimized
Name: "{group}\Kiosk screen (full-screen)"; Filename: "{app}\FaceAttendance.exe"; Parameters: "--open kiosk --fullscreen"; Flags: runminimized
Name: "{group}\Stop Face Attendance"; Filename: "{app}\FaceAttendance.exe"; Parameters: "--stop"; Flags: runminimized
Name: "{group}\Get high-accuracy face model"; Filename: "{app}\FaceAttendance.exe"; Parameters: "--get-hq-model"
Name: "{group}\Data and backups folder"; Filename: "{win}\explorer.exe"; Parameters: """{commonappdata}\FaceAttendance"""
Name: "{group}\Uninstall Face Attendance"; Filename: "{uninstallexe}"
Name: "{commondesktop}\Face Attendance Admin"; Filename: "{app}\FaceAttendance.exe"; Parameters: "--open admin"; Flags: runminimized; Tasks: desktopicons
Name: "{commondesktop}\Face Attendance Kiosk"; Filename: "{app}\FaceAttendance.exe"; Parameters: "--open kiosk --fullscreen"; Flags: runminimized; Tasks: desktopicons
Name: "{commonstartup}\Face Attendance (server)"; Filename: "{app}\FaceAttendance.exe"; Parameters: "--background"; Flags: runminimized; Tasks: autostart
Name: "{commonstartup}\Face Attendance (kiosk)"; Filename: "{app}\FaceAttendance.exe"; Parameters: "--open kiosk --fullscreen"; Flags: runminimized; Tasks: kioskstart

[Run]
; lets other PCs on the office network open the admin panel without a Windows Firewall prompt
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Face Attendance"" dir=in action=allow program=""{app}\FaceAttendance.exe"" enable=yes profile=private,domain"; Flags: runhidden
Filename: "{app}\FaceAttendance.exe"; Parameters: "--open admin"; Description: "Open Face Attendance now"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{app}\FaceAttendance.exe"; Parameters: "--stop"; Flags: runhidden; RunOnceId: "StopFaceAttendance"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Face Attendance"""; Flags: runhidden; RunOnceId: "DeleteFirewallRule"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  rc: Integer;
begin
  { stop a running copy so its files can be replaced during an upgrade }
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM FaceAttendance.exe', '', SW_HIDE, ewWaitUntilTerminated, rc);
  Result := '';
end;
