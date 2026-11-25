; YomiScan Engine installer (Stage 5b increment 5), built by scripts/build_installer.py with NSIS 3.
; Per-user: installs into %LOCALAPPDATA%\Programs, writes only HKCU, needs no administrator rights.
; The models are not included: the extension offers their download, and the engine checks each
; file's SHA-256. Unsigned (owner decision): Windows SmartScreen may warn before it runs.
;
; Silent install:   YomiScan-Engine-Setup.exe /S /EXTENSIONID=<32 letters a-p> [/D=<folder>]
; Silent uninstall: Uninstall.exe /S [/PURGE]   (/PURGE also removes downloaded models and data)

Unicode true
!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "nsDialogs.nsh"
!include "LogicLib.nsh"

!ifndef VERSION
  !error "Build with scripts/build_installer.py (missing VERSION)"
!endif
!ifndef SOURCE
  !error "Build with scripts/build_installer.py (missing SOURCE)"
!endif
!ifndef OUTFILE
  !error "Build with scripts/build_installer.py (missing OUTFILE)"
!endif
!ifndef LICENSE_FILE
  !error "Build with scripts/build_installer.py (missing LICENSE_FILE)"
!endif
!ifndef INSTALLED_KB
  !error "Build with scripts/build_installer.py (missing INSTALLED_KB)"
!endif
!ifndef DEFAULT_EXTENSION_ID
  !define DEFAULT_EXTENSION_ID ""
!endif
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\YomiScanEngine"

Name "YomiScan Engine ${VERSION}"
OutFile "${OUTFILE}"
RequestExecutionLevel user
InstallDir "$LOCALAPPDATA\Programs\YomiScan Engine"
SetCompressor /SOLID lzma
SetCompressorDictSize 64
ShowInstDetails show
ShowUninstDetails show
BrandingText "YomiScan ${VERSION}"

Var ExtensionId
Var IdField

!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TEXT "This installs the YomiScan local engine for your Windows account only.$\r$\n$\r$\nChrome starts it when the YomiScan extension needs it; it stops itself after 15 idle minutes. Its reading models (about 805 MB) are downloaded later, after you agree in the extension."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${LICENSE_FILE}"
Page custom ExtensionPage ExtensionPageLeave
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_TEXT "Reload the YomiScan extension in Chrome (chrome://extensions), then open its panel: it offers the engine's reading models once."
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Function .onInit
  StrCpy $ExtensionId "${DEFAULT_EXTENSION_ID}"
  ${GetParameters} $R0
  ClearErrors
  ${GetOptions} $R0 "/EXTENSIONID=" $R1
  ${IfNot} ${Errors}
    StrCpy $ExtensionId $R1
  ${EndIf}
FunctionEnd

Function ExtensionPage
  !insertmacro MUI_HEADER_TEXT "Connect to Chrome" "Which YomiScan extension may start the engine?"
  nsDialogs::Create 1018
  Pop $0
  ${NSD_CreateLabel} 0 0 100% 52u "In Chrome, open the YomiScan panel, then Advanced → Browser engine. Its first line shows this extension's ID: 32 letters from a to p. Paste it below. Only that extension can start the engine."
  Pop $0
  ${NSD_CreateText} 0 60u 100% 13u "$ExtensionId"
  Pop $IdField
  nsDialogs::Show
FunctionEnd

Function ExtensionPageLeave
  ${NSD_GetText} $IdField $ExtensionId
  StrLen $0 $ExtensionId
  ${If} $0 <> 32
    MessageBox MB_ICONEXCLAMATION "A Chrome extension ID has exactly 32 letters from a to p."
    Abort
  ${EndIf}
FunctionEnd

Section "YomiScan Engine" SecEngine
  SectionIn RO
  ; An update replaces files the running engine holds open: ask it to stop first.
  ${If} ${FileExists} "$INSTDIR\yomiscan-engine.exe"
    nsExec::ExecToLog '"$INSTDIR\yomiscan-engine.exe" --stop'
    Pop $0
  ${EndIf}
  SetOutPath "$INSTDIR"
  File /r "${SOURCE}\*.*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  ; Writes the native-messaging host manifest and HKCU\Software\Google\Chrome\NativeMessagingHosts\com.yomiscan.engine.
  nsExec::ExecToLog '"$INSTDIR\yomiscan-engine.exe" --register --extension-id $ExtensionId'
  Pop $0
  ${If} $0 <> 0
    MessageBox MB_ICONSTOP "Connecting the engine to Chrome failed (exit code $0). Check the extension ID, then run the installer again." /SD IDOK
    SetErrorLevel 2
    Abort
  ${EndIf}
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayName" "YomiScan Engine"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "Publisher" "YomiScan"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\yomiscan-engine.exe"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${UNINSTALL_KEY}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoRepair" 1
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "EstimatedSize" ${INSTALLED_KB}
SectionEnd

Section "Uninstall"
  nsExec::ExecToLog '"$INSTDIR\yomiscan-engine.exe" --stop'
  Pop $0
  nsExec::ExecToLog '"$INSTDIR\yomiscan-engine.exe" --unregister'
  Pop $0
  RMDir /r "$INSTDIR"
  DeleteRegKey HKCU "${UNINSTALL_KEY}"
  ${un.GetParameters} $R0
  ClearErrors
  ${un.GetOptions} $R0 "/PURGE" $R1
  ${IfNot} ${Errors}
    RMDir /r "$LOCALAPPDATA\YomiScan"
  ${Else}
    MessageBox MB_YESNO|MB_DEFBUTTON2 "Also remove the downloaded models, the processing cache and your glossaries ($LOCALAPPDATA\YomiScan)?" /SD IDNO IDNO keep
    RMDir /r "$LOCALAPPDATA\YomiScan"
    keep:
  ${EndIf}
SectionEnd
