; Per-user by design. The toolkit's premise is a per-user Chrome profile and a
; user-level logon task -- autostart.py is explicit that a system service runs
; as another user and finds none of the logins. So: no Program Files, no UAC,
; and the winget manifest can declare Scope: user.

#define AppName "AI Browser Toolkit"
#define AppExe "abt.cmd"

[Setup]
AppId={{7C4C9B2E-2F1A-4E63-9D5B-3A1C8F6E2D74}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=skssmd
AppPublisherURL=https://github.com/skssmd/Ai-Browser-Toolkit
DefaultDirName={localappdata}\Programs\AIBrowserToolkit
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=aibrowsertoolkit-{#AppVersion}-windows-x86_64-setup
Compression=lzma2
SolidCompression=yes
LicenseFile={#PayloadDir}\LICENSE
WizardStyle=modern
UninstallDisplayName={#AppName}
DisableProgramGroupPage=yes

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Tasks]
; Unchecked, deliberately. The opt-in rule is recorded in autostart.py and is
; the whole reason the feature is safe: an always-on logon entry that opened
; Chrome would cost ~2 minutes of every boot.
Name: "autostart"; Description: "Start {#AppName} at logon"; Flags: unchecked
Name: "addtopath"; Description: "Add abt to my PATH"
; Worded as a conditional because it is one. The box cannot be hidden when a
; browser already exists: detection runs `abt doctor`, which does not exist on
; disk until [Files] has run, and tasks are chosen before that. Duplicating
; doctor.py's registry lookups in Pascal would drift the first time either
; changed. So the box always shows, and `doctor --install-browser` no-ops when
; a browser is already present -- which, since Edge ships with Windows 10 and
; 11, is nearly always.
Name: "chrome"; Description: "Install Google Chrome if no browser is found (via winget)"; Flags: unchecked

[Registry]
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; \
    ValueData: "{olddata};{app}"; Check: NeedsAddPath(ExpandConstant('{app}')); \
    Tasks: addtopath; Flags: preservestringtype

[Run]
Filename: "{app}\{#AppExe}"; Parameters: "doctor --install-browser"; \
    Tasks: chrome; StatusMsg: "Installing Google Chrome..."
; --browser is whatever doctor found, never a hardcoded 'chrome'. On an
; Edge-only machine a hardcoded one writes a logon task that fails every boot,
; with the only evidence in a log file nobody reads.
Filename: "{app}\{#AppExe}"; Parameters: "autostart install --browser {code:DetectedBrowser}"; \
    Tasks: autostart; Flags: runhidden; StatusMsg: "Registering the logon task..."

[UninstallRun]
; Before the files go, or Task Scheduler is left holding an entry that points
; at a deleted executable and fails at every logon forever.
Filename: "{app}\{#AppExe}"; Parameters: "autostart uninstall"; \
    Flags: runhidden; RunOnceId: "RemoveAutostart"

[Code]
var
  Detected: string;
  DetectionDone: Boolean;

function NeedsAddPath(Param: string): Boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', OrigPath) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Param + ';', ';' + OrigPath + ';') = 0;
end;

// The same detection `abt doctor` does, rather than a second copy of it in
// Pascal. Reading the App Paths registry keys here would drift from
// doctor.py the first time either changed.
procedure Detect;
var
  Tmp: string;
  Code: Integer;
  Lines: TArrayOfString;
begin
  // Cache only a SUCCESSFUL detection. This runs once on the wizard page --
  // where {app}\abt.cmd does not exist yet and it necessarily fails -- and
  // again from [Run] after [Files] has copied it. Caching the first, empty
  // answer would make every install register a logon task for the wrong
  // browser.
  if DetectionDone then exit;
  Detected := '';
  Tmp := ExpandConstant('{tmp}\browser.txt');
  // Inno cannot capture stdout, so route it through cmd into a file. This is
  // why doctor grew --print-browser: one word, no JSON to parse in Pascal.
  if Exec(ExpandConstant('{cmd}'),
          '/C ""' + ExpandConstant('{app}\{#AppExe}') + '" doctor --print-browser > "' + Tmp + '""',
          '', SW_HIDE, ewWaitUntilTerminated, Code) then
  begin
    if LoadStringsFromFile(Tmp, Lines) and (GetArrayLength(Lines) > 0) then
      Detected := Trim(Lines[0]);
  end;
  if Detected <> '' then
    DetectionDone := True;
end;

function DetectedBrowser(Param: string): string;
begin
  Detect;
  if Detected = '' then
    // Nothing found -- either the chrome task just installed one, or the user
    // declined and will install a browser later. Chrome is the right guess:
    // it is what `abt serve` defaults to and what doctor offers to install.
    Result := 'chrome'
  else
    Result := Detected;
end;
