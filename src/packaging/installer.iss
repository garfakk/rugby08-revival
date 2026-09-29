; Inno Setup script — one script, three installers (see release.sh):
;   /DVariant=full   program + data pack (first install)
;   /DVariant=app    program only (upgrade, keeps data)
;   /DVariant=data   data pack only (new season etc, no program needed)
; Other defines: AppVersion, DataVersion, ProgramDir (staged program+assets),
; DataDir (staged data pack), OutDir, IncDir (generated data_*.inc).
#ifndef Variant
  #define Variant "full"
#endif
#if Variant != "data"
  #define WithApp
#endif
#if Variant != "app"
  #define WithData
#endif

[Setup]
#ifdef WithApp
AppId={{6C1E0B7A-4A0B-4B0E-9E52-0A08D0F0E001}
AppName=Rugby 08 Revival
AppVersion={#AppVersion}
DefaultDirName={userdocs}\R08Revival
DefaultGroupName=Rugby 08 Revival
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\R08Revival.exe
#else
AppId={{6C1E0B7A-4A0B-4B0E-9E52-0A08D0F0E002}
AppName=Rugby 08 Revival data
AppVersion={#DataVersion}
DefaultDirName={code:DefaultDataDir}
AppendDefaultDirName=no
DirExistsWarning=no
Uninstallable=no
#endif
; Everything (program, app_data, mod_data, user_data, game_files) lives under the one
; install folder, and the mod writes there at runtime (config, logs, Team/Player editor
; saves, the game copy). So it is a per-user install with no elevation offered, and
; protected folders such as Program Files are refused (see InstallDirProblem).
PrivilegesRequired=lowest
OutputDir={#OutDir}
#if Variant == "full"
OutputBaseFilename=R08Revival_{#AppVersion}_setup
#elif Variant == "app"
OutputBaseFilename=R08Revival_{#AppVersion}_program_only
#else
OutputBaseFilename=R08Revival_data_{#DataVersion}_setup
#endif
AppPublisher=Rugby 08 Revival
SetupIconFile={#SourcePath}icon\app_icon.ico
Compression=lzma2/normal
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern

; No [Types]/[Components]: always a full install (program + music + all data).

#ifdef WithApp
[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; Flags: unchecked
#endif

[Files]
#ifdef WithApp
Source: "{#ProgramDir}\R08Revival.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ProgramDir}\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ProgramDir}\app_data\*"; DestDir: "{app}\app_data"; Flags: ignoreversion recursesubdirs createallsubdirs
; the private copy of the game the mod works on (skipped when patching in place / upgrading;
; onlyifdoesntexist keeps a previous copy, and any changes the mod made to it, intact).
; Copies exactly config.original_game_files / config.original_game_folders (see
; gen_game_includes.py) instead of copying everything, so a game folder that
; already has the mod - or another patch - installed can't bake stale/foreign
; files into what's supposed to be a clean copy; the mod writes them all fresh
; on first launch.
#include AddBackslash(IncDir) + "game_includes.inc"
#endif
#ifdef WithData
#include AddBackslash(IncDir) + "data_files.inc"
#endif

#ifdef WithApp
[Icons]
Name: "{group}\Rugby 08 Revival"; Filename: "{app}\R08Revival.exe"; WorkingDir: "{app}"
Name: "{group}\Uninstall Rugby 08 Revival"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Rugby 08 Revival"; Filename: "{app}\R08Revival.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\R08Revival"; ValueType: string; ValueName: "InstallDir"; ValueData: "{app}"; Flags: uninsdeletevalue uninsdeletekeyifempty

[Run]
; Started through explorer.exe on purpose: a UI launched directly by the installer inherits the
; installer's process context, and the game it spawns then ran WITHOUT the d3d8 proxy (stock
; fullscreen, profile not applied) for that whole UI session. Explorer as parent = a normal start.
Filename: "{win}\explorer.exe"; Parameters: """{app}\R08Revival.exe"""; Description: "Launch Rugby 08 Revival"; Flags: nowait postinstall skipifsilent

; Uninstall removes the whole install folder content: program, app_data, mod_data (edits and
; _backup included) and game_files (the game copy; the original game is never touched).
; user_data (config, prefs, logs) is removed only if the user ticks the box that
; InitializeUninstall shows (silent uninstall: /DELETEUSERDATA).
[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\app_data"
Type: filesandordirs; Name: "{app}\mod_data"
Type: filesandordirs; Name: "{app}\game_files"
Type: filesandordirs; Name: "{app}\user_data"; Check: DeleteUserData
#endif

[Code]
const
  GameExe = 'Rugby08.exe';

var
  GamePage: TInputDirWizardPage;
#ifdef WithApp
  ModPage: TWizardPage;
  CopyRadio, InPlaceRadio: TNewRadioButton;
  CopyInfo: TNewStaticText;
  GameBytes: Int64;
#endif

function ConfigPath: string;
begin
  Result := AddBackslash(WizardDirValue) + 'user_data\config.ini';
end;

function DefaultDataDir(Param: string): string;
var
  Root: string;
begin
  { data-only installer: default to mod_data\ of the installed program (recorded by its installer) }
  if RegQueryStringValue(HKCU, 'Software\R08Revival', 'InstallDir', Root) and DirExists(Root) then
    Result := AddBackslash(Root) + 'mod_data'
  else
    Result := ExpandConstant('{param:DATADIR|{userdocs}\R08Revival\mod_data}');
end;

{ ---- the install folder must be one the mod can write to ---- }

function IsInside(const Child, Parent: string): Boolean;
begin
  Result := (Parent <> '') and (Pos(Lowercase(AddBackslash(Parent)), Lowercase(AddBackslash(Child))) = 1);
end;

function CanWriteTo(Dir: string): Boolean;
var
  Probe: string;
begin
  { try in the nearest existing parent: the folder itself may not exist yet }
  while (Dir <> '') and (not DirExists(Dir)) and (ExtractFileDir(Dir) <> Dir) do
    Dir := ExtractFileDir(Dir);
  Probe := AddBackslash(Dir) + '.r08_write_test';
  Result := SaveStringToFile(Probe, 'x', False);
  if Result then DeleteFile(Probe);
end;

function InstallDirProblem(Dir: string): string;
begin
  Result := '';
  Dir := RemoveBackslash(Dir);
  if IsInside(Dir, ExpandConstant('{commonpf}')) or IsInside(Dir, ExpandConstant('{commonpf32}')) or
     IsInside(Dir, ExpandConstant('{commonpf64}')) or IsInside(Dir, ExpandConstant('{win}')) or
     (ExtractFileDir(Dir) = Dir) then
    Result := 'This folder is protected (Program Files, Windows or a drive root). Rugby 08 Revival saves ' +
      'its settings, data and game copy next to the program, so it needs a folder you can write to.' + #13#10 + #13#10 +
      'Choose another folder, for example ' + ExpandConstant('{userdocs}\R08Revival') + '.'
  else if not CanWriteTo(Dir) then
    Result := 'Setup cannot write to this folder. Choose a folder you have write access to, for example ' +
      ExpandConstant('{userdocs}\R08Revival') + '.';
end;

function GameDirLooksRight(Dir: string): Boolean;
begin
  Result := (Dir <> '') and FileExists(AddBackslash(Dir) + GameExe);
end;

{ ---- find the Rugby 08 installation ---- }

function ProbeUninstallKey(RootKey: Integer; const Base: string): string;
var
  Names: TArrayOfString;
  I: Integer;
  Display, Loc: string;
begin
  Result := '';
  if not RegGetSubkeyNames(RootKey, Base, Names) then Exit;
  for I := 0 to GetArrayLength(Names) - 1 do
    if RegQueryStringValue(RootKey, Base + '\' + Names[I], 'DisplayName', Display) and
       (Pos('rugby 08', Lowercase(Display)) > 0) and
       RegQueryStringValue(RootKey, Base + '\' + Names[I], 'InstallLocation', Loc) and
       GameDirLooksRight(Loc) then
    begin
      Result := Loc;
      Exit;
    end;
end;

function TryDefaultFolders(const PF: string): string;
var
  Vendors, Games: TArrayOfString;
  V, G: Integer;
begin
  Result := '';
  if PF = '' then Exit;
  SetArrayLength(Vendors, 4);
  Vendors[0] := 'EA SPORTS'; Vendors[1] := 'EA SPORT'; Vendors[2] := 'EA Games'; Vendors[3] := 'Electronic Arts';
  SetArrayLength(Games, 3);
  Games[0] := 'EA SPORTS(TM) Rugby 08'; Games[1] := 'Rugby 08'; Games[2] := 'EA SPORTS Rugby 08';
  for V := 0 to 3 do
    for G := 0 to 2 do
      if GameDirLooksRight(PF + '\' + Vendors[V] + '\' + Games[G]) then
      begin
        Result := PF + '\' + Vendors[V] + '\' + Games[G];
        Exit;
      end;
end;

function DetectGameDir: string;
var
  Unin: string;
begin
  Unin := 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall';
  Result := ExpandConstant('{param:GAMEDIR|}');
  if GameDirLooksRight(Result) then Exit;
  Result := GetIniString('Main', 'R08_original_directory', '', ConfigPath);
  if GameDirLooksRight(Result) then Exit;
  Result := GetIniString('Main', 'R08_directory', '', ConfigPath);
  if GameDirLooksRight(Result) then Exit;
  Result := ProbeUninstallKey(HKLM32, Unin);
  if Result = '' then Result := ProbeUninstallKey(HKLM64, Unin);
  if Result = '' then Result := ProbeUninstallKey(HKCU, Unin);
  if Result = '' then Result := TryDefaultFolders(ExpandConstant('{commonpf32}'));
  if Result = '' then Result := TryDefaultFolders(ExpandConstant('{commonpf64}'));
end;

{ ---- the game copy the mod works on ---- }
{ The mod rewrites game files every time a match starts, so by default it works on
  a private copy of the installation and the original is never touched. }

#ifdef WithApp
function Upgrading: Boolean;
begin
  { program-only upgrade of an existing install: game folder is already configured }
#if Variant == "app"
  Result := GameDirLooksRight(GetIniString('Main', 'R08_directory', '', ConfigPath));
#else
  Result := False;
#endif
end;

function WantCopy: Boolean;
begin
  Result := (not Upgrading) and CopyRadio.Checked;
end;

function GameSrcDir(Param: string): string;
begin
  Result := RemoveBackslash(GamePage.Values[0]);
end;

function GameDestDir(Param: string): string;
begin
  Result := AddBackslash(WizardDirValue) + 'game_files';   { always inside the install folder }
end;

function FinalGameDir: string;
begin
  if WantCopy then Result := GameDestDir('') else Result := GameSrcDir('');
end;

function DirSize(const Dir: string): Int64;
var
  R: TFindRec;
begin
  Result := 0;
  if not FindFirst(Dir + '\*', R) then Exit;
  try
    repeat
      if (R.Name = '.') or (R.Name = '..') then Continue;
      if (R.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
      begin
        if CompareText(R.Name, 'R08_mod') <> 0 then
          Result := Result + DirSize(Dir + '\' + R.Name);
      end else
        Result := Result + R.SizeLow;
    until not FindNext(R);
  finally
    FindClose(R);
  end;
end;

function DirIsEmpty(const Dir: string): Boolean;
var
  R: TFindRec;
begin
  Result := True;
  if not DirExists(Dir) then Exit;
  if not FindFirst(Dir + '\*', R) then Exit;
  try
    repeat
      if (R.Name <> '.') and (R.Name <> '..') then
      begin
        Result := False;
        Exit;
      end;
    until not FindNext(R);
  finally
    FindClose(R);
  end;
end;

function FreeSpaceAt(Dir: string): Int64;
var
  Free, Total: Int64;
begin
  Result := -1;
  while (Dir <> '') and (not DirExists(Dir)) and (ExtractFileDir(Dir) <> Dir) do
    Dir := ExtractFileDir(Dir);
  if GetSpaceOnDisk64(Dir, Free, Total) then Result := Free;
end;

procedure UpdateModPage;
begin
  if GameBytes > 0 then
    CopyInfo.Caption := 'The copy goes to the game_files folder of the install folder and needs about ' +
      IntToStr(GameBytes div (1024 * 1024)) + ' MB. The mod changes game files every time a match ' +
      'starts, so it works on this copy and your original installation stays untouched.'
  else
    CopyInfo.Caption := 'The copy goes to the game_files folder of the install folder. The mod changes game ' +
      'files every time a match starts, so it works on this copy and your original installation stays untouched.';
end;

procedure ModRadioClick(Sender: TObject);
begin
  UpdateModPage;
end;

procedure CreateModPage(AfterID: Integer);
var
  W: Integer;
begin
  ModPage := CreateCustomPage(AfterID, 'Modded game folder',
    'Copy the original game, or patch it in place?');
  W := ModPage.SurfaceWidth;

  CopyRadio := TNewRadioButton.Create(ModPage);
  CopyRadio.Parent := ModPage.Surface;
  CopyRadio.Left := 0; CopyRadio.Top := 0; CopyRadio.Width := W; CopyRadio.Height := ScaleY(17);
  CopyRadio.Caption := 'Copy the original game into the install folder (recommended)';
  CopyRadio.Font.Style := [fsBold];
  CopyRadio.Checked := ExpandConstant('{param:COPYGAME|1}') <> '0';
  CopyRadio.OnClick := @ModRadioClick;

  CopyInfo := TNewStaticText.Create(ModPage);
  CopyInfo.Parent := ModPage.Surface;
  CopyInfo.Left := ScaleX(18); CopyInfo.Top := CopyRadio.Top + CopyRadio.Height + ScaleY(4);
  CopyInfo.Width := W - ScaleX(18);
  CopyInfo.AutoSize := False; CopyInfo.WordWrap := True; CopyInfo.Height := ScaleY(48);

  InPlaceRadio := TNewRadioButton.Create(ModPage);
  InPlaceRadio.Parent := ModPage.Surface;
  InPlaceRadio.Left := 0; InPlaceRadio.Top := CopyInfo.Top + CopyInfo.Height + ScaleY(20); InPlaceRadio.Width := W; InPlaceRadio.Height := ScaleY(17);
  InPlaceRadio.Caption := 'Use the original installation directly (not recommended)';
  InPlaceRadio.Checked := not CopyRadio.Checked;
  InPlaceRadio.OnClick := @ModRadioClick;

  UpdateModPage;
end;
#endif

{ ---- wizard pages ---- }

procedure InitializeWizard;
begin
#ifdef WithApp
  GamePage := CreateInputDirPage(wpSelectComponents,
    'Original Rugby 08 installation',
    'Where is Rugby 08 installed?',
    'Select the folder that contains ' + GameExe + '. This is your original game; it is only read (unless you choose to patch it in place on the next page).',
    False, '');
  GamePage.Add('');
  GamePage.Values[0] := DetectGameDir;
  CreateModPage(GamePage.ID);
#endif
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
#ifdef WithApp
  if Upgrading and ((PageID = GamePage.ID) or (PageID = ModPage.ID)) then Result := True;
#endif
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Problem: string;
#ifdef WithApp
  Src, Dst: string;
  Free: Int64;
#endif
begin
  Result := True;
  if CurPageID = wpSelectDir then
  begin
    Problem := InstallDirProblem(WizardDirValue);
    if Problem <> '' then
    begin
      MsgBox(Problem, mbError, MB_OK);
      Result := False;
    end;
  end;
#ifdef WithApp
  if CurPageID = GamePage.ID then
  begin
    if not GameDirLooksRight(GamePage.Values[0]) then
    begin
      MsgBox(GameExe + ' was not found in that folder. Select the Rugby 08 installation folder.', mbError, MB_OK);
      Result := False;
    end else begin
      WizardForm.NextButton.Enabled := False;
      try
        GameBytes := DirSize(RemoveBackslash(GamePage.Values[0]));
      finally
        WizardForm.NextButton.Enabled := True;
      end;
      UpdateModPage;
    end;
  end;
  if (CurPageID = ModPage.ID) and CopyRadio.Checked then
  begin
    Src := GameSrcDir('');
    Dst := GameDestDir('');
    if Dst = '' then
    begin
      MsgBox('Choose the install folder first.', mbError, MB_OK);
      Result := False;
    end else if IsInside(Dst, Src) or IsInside(Src, Dst) then
    begin
      MsgBox('The install folder cannot be inside the original game folder (or contain it). Go back and choose a separate install folder.', mbError, MB_OK);
      Result := False;
    end else if (not DirIsEmpty(Dst)) and (not GameDirLooksRight(Dst)) then
    begin
      MsgBox(Dst + ' exists, is not empty and does not hold a game copy. Remove it or choose another install folder.', mbError, MB_OK);
      Result := False;
    end else if not GameDirLooksRight(Dst) then
    begin
      Free := FreeSpaceAt(Dst);
      if (Free >= 0) and (GameBytes > 0) and (Free < GameBytes) then
      begin
        MsgBox('Not enough free disk space for the copy (' + IntToStr(GameBytes div (1024 * 1024)) +
          ' MB needed, ' + IntToStr(Free div (1024 * 1024)) + ' MB free).', mbError, MB_OK);
        Result := False;
      end;
    end;
  end;
  if (CurPageID = ModPage.ID) and InPlaceRadio.Checked and Result then
    Result := MsgBox('The mod will modify files in your original Rugby 08 folder and can leave it in a ' +
      'changed state.' + #13#10 + #13#10 + 'Copying the game is safer. Patch the original anyway?',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
#endif
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := InstallDirProblem(WizardDirValue);
end;

{ ---- data folder: where it goes, and a safety copy of the editable files ---- }

function DataDir(Param: string): string;
begin
#if Variant == "data"
  Result := WizardDirValue;         { the data-only installer's own directory page }
#elif Variant == "full"
  Result := AddBackslash(WizardDirValue) + 'mod_data';  { inside the install folder, asked once }
#else
  Result := DefaultDataDir('');     { app-only variant: no data installed, but keep a sane value }
#endif
end;

procedure BackupTree(const Root, Dir, Dest: string);
var
  R: TFindRec;
  Ext, Rel: string;
begin
  if not FindFirst(Dir + '\*', R) then Exit;
  try
    repeat
      if (R.Name = '.') or (R.Name = '..') then Continue;
      if (R.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
      begin
        if CompareText(R.Name, '_backup') <> 0 then
          BackupTree(Root, Dir + '\' + R.Name, Dest);
      end else begin
        Ext := Lowercase(ExtractFileExt(R.Name));
        if (Ext = '.json') or (Ext = '.xml') or (Ext = '.ini') then
        begin
          Rel := Copy(Dir, Length(Root) + 1, MaxInt);
          ForceDirectories(Dest + Rel);
          CopyFile(Dir + '\' + R.Name, Dest + Rel + '\' + R.Name, False);
        end;
      end;
    until not FindNext(R);
  finally
    FindClose(R);
  end;
end;

procedure BackupExistingData;
var
  Root, Dest: string;
begin
  Root := RemoveBackslash(DataDir(''));
  if not DirExists(Root + '\players') then Exit;   { fresh install: nothing to save }
  Dest := Root + '\_backup\' + GetDateTimeString('yyyymmdd-hhnnss', '-', ':');
  BackupTree(Root, Root, Dest);
end;

procedure WriteConfig;
#ifdef WithApp
var
  Cfg: string;
#endif
begin
#ifdef WithApp
  Cfg := ConfigPath;
  ForceDirectories(ExtractFileDir(Cfg));
  if not Upgrading then
  begin
    SetIniString('Main', 'R08_directory', AddBackslash(FinalGameDir), Cfg);
    SetIniString('Main', 'R08_original_directory', AddBackslash(GameSrcDir('')), Cfg);
  end;
  SetIniString('Main', 'R08_filename', GameExe, Cfg);
  SetIniString('Main', 'mod_directory', AddBackslash(WizardDirValue), Cfg);
#endif
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
#ifdef WithData
  if CurStep = ssInstall then BackupExistingData;
#endif
  if CurStep = ssPostInstall then WriteConfig;
end;

#ifdef WithApp
{ ---- uninstall: ask whether the user's own files go too ---- }

var
  WipeUserData: Boolean;

function DeleteUserData: Boolean;
begin
  Result := WipeUserData;
end;

function InitializeUninstall: Boolean;
var
  F: TSetupForm;
  Info: TNewStaticText;
  Box: TNewCheckBox;
  Ok, Cancel: TNewButton;
begin
  Result := True;
  if UninstallSilent then
  begin
    WipeUserData := ExpandConstant('{param:DELETEUSERDATA|0}') = '1';
    Exit;
  end;
  F := CreateCustomForm(ScaleX(440), ScaleY(170), False, False);
  try
    F.Caption := 'Uninstall Rugby 08 Revival';
    F.Position := poScreenCenter;

    Info := TNewStaticText.Create(F);
    Info.Parent := F;
    Info.Left := ScaleX(16); Info.Top := ScaleY(16); Info.Width := F.ClientWidth - ScaleX(32);
    Info.AutoSize := False; Info.WordWrap := True; Info.Height := ScaleY(60);
    Info.Caption := 'The program, the mod data (teams, players, kits...) and the game copy will be removed. ' +
      'Your original Rugby 08 installation is not touched.';

    Box := TNewCheckBox.Create(F);
    Box.Parent := F;
    Box.Left := ScaleX(16); Box.Top := Info.Top + Info.Height + ScaleY(4); Box.Width := F.ClientWidth - ScaleX(32);
    Box.Height := ScaleY(20);
    Box.Caption := 'Also delete my settings, preferences and logs (user_data)';
    Box.Checked := False;

    Ok := TNewButton.Create(F);
    Ok.Parent := F; Ok.Caption := 'Uninstall'; Ok.ModalResult := mrOk; Ok.Default := True;
    Ok.Width := ScaleX(90); Ok.Height := ScaleY(25);
    Ok.Left := F.ClientWidth - ScaleX(16) - Ok.Width * 2 - ScaleX(8); Ok.Top := F.ClientHeight - ScaleY(41);

    Cancel := TNewButton.Create(F);
    Cancel.Parent := F; Cancel.Caption := 'Cancel'; Cancel.ModalResult := mrCancel; Cancel.Cancel := True;
    Cancel.Width := ScaleX(90); Cancel.Height := ScaleY(25);
    Cancel.Left := F.ClientWidth - ScaleX(16) - Cancel.Width; Cancel.Top := Ok.Top;

    Result := F.ShowModal = mrOk;
    WipeUserData := Box.Checked;
  finally
    F.Free;
  end;
end;
#endif
