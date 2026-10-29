#ifndef RepositoryArchiveHash
  #error Define RepositoryArchiveHash when compiling this installer.
#endif

#ifndef RepositoryArchiveExpandedSize
  #error Define RepositoryArchiveExpandedSize when compiling this installer.
#endif

#define AppVersion "1.3"
#define RepositoryArchiveName "HANDMOVE-Repository-v1.3.zip"
#define RepositoryArchiveURL "https://github.com/IamOumarIbrahim/handmove/releases/download/v1.3/HANDMOVE-Repository-v1.3.zip"

[Setup]
AppId={{D636F9E7-0E2A-4A0C-978F-5DFB810C7D93}
AppName=HANDMOVE Repository
AppVersion={#AppVersion}
AppVerName=HANDMOVE Repository {#AppVersion}
AppPublisher=HANDMOVE
DefaultDirName={userdocs}\HANDMOVE
DefaultGroupName=HANDMOVE
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
Uninstallable=yes
WizardStyle=modern
ArchiveExtraction=full
OutputDir=..\dist
OutputBaseFilename=HANDMOVE-Setup-v{#AppVersion}
Compression=lzma2
SolidCompression=yes

[Messages]
WelcomeLabel2=This setup downloads the HANDMOVE v1.3 repository from GitHub and extracts the source files to the selected folder. It does not install Python or the project dependencies.

[Files]
Source: "{#RepositoryArchiveURL}"; DestDir: "{app}"; DestName: "{#RepositoryArchiveName}"; ExternalSize: {#RepositoryArchiveExpandedSize}; Hash: "{#RepositoryArchiveHash}"; Flags: external download extractarchive ignoreversion
