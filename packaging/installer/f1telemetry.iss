; F1 Telemetry - Inno Setup script. PRIORITIES -> C8b.
;
; WHY THIS IS AN ADMIN INSTALL, AND THE INVARIANT IT MUST NOT BREAK
;   The Windows Firewall allow-rule needs administrator rights; the app needs NONE at runtime.
;   Everything it writes lives under %LOCALAPPDATA%\f1telemetry (src/paths.py data_root()), and
;   nothing is ever written beside the exe - so Program Files is safe. Elevation buys exactly two
;   things: the firewall rule and the all-users Start-menu entry. If a build ever needs admin to
;   *run*, that is a bug, not a consequence of this decision.
;   Full rationale: docs/PACKAGING.md -> "The installer is an admin install".
;
; HOW IT IS BUILT
;   By release.yml's windows-build job, from dist\f1telemetry, AFTER that job's bundle
;   sanity-check - so the installer can only ever package a bundle that already has the guide,
;   notices, licence and roster template beside the exe. Four defines, all supplied by CI:
;     /DAppVersion=0.7.0
;     /DBundleDir=<abs path to dist\f1telemetry>
;     /DOutputDir=<abs path to dist>
;     /DOutputBaseFilename=f1telemetry-v0.7.0-windows-x64-setup


#ifndef AppVersion
  #error AppVersion must be passed, e.g. /DAppVersion=0.7.0
#endif
#ifndef BundleDir
    #error BundleDir must be passed, e.g. /DBundleDir=C:\...\dist\f1telemetry
#endif
#ifndef OutputDir
    #define OutputDir "."
#endif
#ifndef OutputBaseFilename
    #define OutputBaseFilename "f1telemetry-setup"
#endif

#define AppName "F1 Telemetry"
#define ExeName "f1telemetry.exe"
#define RepoUrl "https://github.com/Soundscape93/f1telemetry"
; Keyed by NAME so the delete-before-add-below can find it again on every reinstall.
#define FirewallRule "F1 Telemetry (UDP 20777)"
#define TelemetryPort "20777"


[Setup]
; NEVER change the AppId. It is the only thing that makes an upgrade an upgrade rather than a second install.
; parallel installation with its own uninstall-entry.
AppId={{369930C2-4669-43DF-AC34-B48E089E1D68}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Kevin Fust (Soundscape93)
AppPublisherURL={#RepoUrl}
AppSupportURL={#RepoUrl}(issues)
AppUpdatesURL={#RepoUrl}(releases)
VersionInfoVersion={#AppVersion}

DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UninstallDisplayName={#AppName} {#AppVersion}
UninstallDisplayIcon={app}\{#ExeName}

OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseFilename}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

; Per-machine, and not negotiable: the firewall rule needs elevation. This is also what makes
; {autopf} resolve to Program Files and {autoprograms} to the all-users Start menu. The empty
; override list forbids the /CURRENTUSER command-line escape, so there is exactly one install
; shape to support and to test.
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=

; The Bundle is x64. Without these a 32-bit Installer would put an x64 app in
; "Program Files (x86)" and resolve {sys} to SysWOW64.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; Source-available, not open source - terms worth showing before the install rather than after.
LicenseFile={#BundleDir}\LICENSE

; A one-folder PyInstaller app holds file locks while it runs, which is the same problem that
; deferred velopack (C8c). Restart Manager finds the running instance and offers to close it;
; that is what makes an upgrade-in-place work instead of failing on a locked f1telemetry.exe.
CloseApplications=yes
RestartApplications=no


[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; \
    Flags: recursesubdirs createallsubdirs ignoreversion


[InstallDelete]
; Inno replaces only the files it is installing, so anything DROPPED by a late build would linger
; in _internal forever - a stale Qt plugin or DLL is exactly the shape of an unreproducable bug.
; Clear it first an let (Files) lay the new tree down. Safe because nothing user-owned is in
; here: all writable data lives in %LOCALAPPDATA% (see the header).
Type: filesandordirs; Name: "{app}\_internal"


[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; Flags: unchecked


[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#ExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#ExeName}"; Tasks: desktopicon


[Run]
; ---- THE REASON THIS INSTALLER EXISTS ----------------------------------------------------------
; The app listens for the game's UDP broadcast on 0.0.0.0:20777 (src/ingest/sources.py). Without a
; rule, Windows shows a prompt on the first recording - PACKAGING's #3 "easy to forget" - and a
; tester who dismisses it gets a recording that silently receives nothing, with no way to make the
; prompt come back.
;
; netsh rather than the firewall COM API, deliberately: it is legible, and it leaves a line in the
; install log that can be read out over a chat window on a machine we cannot debug.
;
; Delete-then-add, keyed by rule name, so a reinstall or an upgrade REPLACES the rule instead of
; stacking duplicates. The delete exits nonzero when nothing matches - the normal first-install
; case - and that is fine: Inno does not fail a [Run] entry on a nonzero exit code.
;
; profile=private,domain and NOT public, deliberately. This is a home-LAN listener whose parser
; reads untrusted datagrams, and it mirrors what the Windows prompt itself ticks by default.
; The consequence is a silent failure and is documented in USER_GUIDE section 2: if Windows has
; the home network classified as Public, this rule does not apply and no packets arrive.
Filename: "{sys}\netsh.exe"; \
    Parameters: "advfirewall firewall delete rule name=""{#FirewallRule}"""; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Replacing any previous firewall rule ..."

Filename: "{sys}\netsh.exe"; \
    Parameters: "advfirewall firewall add rule name=""{#FirewallRule}"" dir=in action=allow program=""{app}\{#ExeName}"" protocol=UDP localport={#TelemetryPort} profile=private,domain enable=yes"; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Allowing telemetry trough Windows Firewall (UDP {#TelemetryPort}) ..."

; NOTE: there is deliberately NO "launch the app now" checkbox. The installer runs elevated, so a post 
; install launch would hand the app an ADMIN token - creating the data root in the wrong user
; profile on exactly the standard-user machine this design targets, and quietly disproving the
; runtime invariant on its very first run. The Start-menu entry is the way in.


[UninstallRun]
; A rule naming a deleted exe is litter. Runs before the files go.
Filename: "{sys}\netsh.exe"; \
    Parameters: "advfirewall firewall delete rule name=""{#FirewallRule}"""; \
    Flags: runhidden waituntilterminated; \
    RunOnceId: "DeleteFirewallRule"

; NOTHING removes %LOCALAPPDATA%\f1telemetry, and there is deliberatel no opt-in checkbox fo it
; either. Two reasons, and the secon is decisive:
;   1. captures/ is the source of truth and can be gigabytes of data; the database is the disposable half.
;   2. An admin uninstall runs under the ADMINISTRATOR's token, but the data_root() is per-user. On the
;      machine this whole decision targets - installed as admin, run by standard user - it would
;      resolve the admins' %LOCALAPPDATA%, find nothing, and report success while deleting nothing.
;      A checkbox that lies is worse than no checkbox at all.
; Users remove it by hand; Help -> Open Data Folder puts them in the right place.


[Code]
// -------------------------------------------------------------------------------------------
// REFUSE TO UNINSTALL WHILE THE APP IS RUNNING.
//
// Found by the C8b clean-machine run: uninstalling with F1 Telemetry open deleted the documents
// beside the exe but left f1telemetry.exe and _internal behind - Windows will not remove a
// running executable or its loaded DLLs. The result is a half-removed install with no obvious
// way back, which is worse than either outcome on its own. CloseApplications=yes covers Setup;
// it does not save the uninstaller, which is itself holding the {app} directory.
//
// InitializeUninstall is the right hook precisely because returning False aborts BEFORE anything
// is removed, so a refusal leaves the installation exactly as it was.
//
// Detection is tasklist piped through find, for the same reason the firewall rule uses netsh: it
// is legible, needs no mutex in the app, and needs no DLL import. `find` exits 1 when it matches
// nothing, so the exit code IS the answer. The uninstaller runs elevated, and that matters here -
// elevated tasklist also sees an instance left open by a DIFFERENT user, which is exactly the
// case a per-machine admin install makes likely.
//
// NOTE FOR ANYONE EDITING THIS SECTION: use // comments, never Pascal's { } block comments.
// This file is full of Inno constants written as {app}, {cmd}, {sys} - and a } inside a brace
// comment CLOSES it, so the prose after it is parsed as code. That cost a CI round trip once.
// -------------------------------------------------------------------------------------------
function AppIsRunning(): Boolean;
var
  ResultCode: Integer;
begin
  Result := False;
  if Exec(ExpandConstant('{cmd}'),
          '/C tasklist /FI "IMAGENAME eq {#ExeName}" /NH | find /I "{#ExeName}"',
          '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Result := (ResultCode = 0);
  // If Exec itself fails we deliberately report "not running" and let the uninstall proceed.
  // A broken detector must not turn into a program that cannot be uninstalled at all.
end;

function InitializeUninstall(): Boolean;
begin
  Result := True;
  while AppIsRunning() do
  begin
    // A silent uninstall has nobody to answer a dialog, so refuse rather than hang or half-remove.
    if UninstallSilent then
    begin
      Result := False;
      Exit;
    end;
    if MsgBox('F1 Telemetry is still running.' + #13#10#13#10 +
              'Close it, then click Retry. Or click Cancel to leave it installed.' + #13#10#13#10 +
              'Uninstalling while it is open would leave part of the program behind, because ' +
              'Windows cannot remove files that are in use.',
              mbError, MB_RETRYCANCEL) = IDCANCEL then
    begin
      Result := False;
      Exit;
    end;
  end;
end;
