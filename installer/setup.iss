; Instalador de "Mis Finanzas Personales". Compilar con:
;   ISCC installer\setup.iss
; (o pasando la version explicita, como hace el workflow de CI: ISCC /DMyAppVersion=1.2.3 installer\setup.iss)
;
; Requiere que ya exista dist\MisFinanzasPersonales\ (salida de
; `pyinstaller MisFinanzasPersonales.spec`, corrido desde la raiz del repo).

#ifndef MyAppVersion
  #define FileHandle = FileOpen("..\VERSION")
  #define MyAppVersion = Trim(FileRead(FileHandle))
  #expr FileClose(FileHandle)
#endif

#define MyAppName "Mis Finanzas Personales"
#define MyAppExeName "MisFinanzasPersonales.exe"
#define MyAppPublisher "Javier Ignacio Rivas Poblete"

[Setup]
; GUID fijo generado una sola vez -- NO regenerar nunca. Es lo que le permite a Inno Setup
; reconocer una instalacion existente y actualizarla en el mismo lugar en vez de crear una
; instalacion nueva en paralelo.
AppId={{E103F50C-0B60-4D29-BA33-A32F8CE2CD36}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Instalacion por usuario, sin pedir permisos de administrador: nada de UAC, cero friccion
; para un usuario sin conocimientos tecnicos.
PrivilegesRequired=lowest
; Carpeta de instalacion del PROGRAMA -- deliberadamente separada de la carpeta de DATOS
; (%LOCALAPPDATA%\MisFinanzasPersonales\data, definida en src/db.py). Asi, desinstalar o
; actualizar la app nunca puede tocar el historial financiero del usuario: Inno Setup solo
; borra/sobreescribe lo que puso bajo {app}, y {app} no es ni contiene la carpeta de datos.
DefaultDirName={localappdata}\Programs\MisFinanzasPersonales
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist_installer
OutputBaseFilename=MisFinanzasPersonales-Setup-{#MyAppVersion}
SetupIconFile=..\assets\app.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el Escritorio"; GroupDescription: "Accesos directos:"

[Files]
Source: "..\dist\MisFinanzasPersonales\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName}"; Flags: nowait postinstall skipifsilent
