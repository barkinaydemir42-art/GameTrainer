; installer.iss
; Inno Setup betigi - LocalTrainer Studio icin GERCEK bir Windows kurulum
; sihirbazi (Setup.exe) uretir: Program Files'a kurar, Baslat Menusu ve
; Masaustu kisayolu ekler, duzgun bir kaldirici (uninstaller) olusturur.
;
; Nasil derlenir (yerelde, Windows'ta):
;   1) Inno Setup'i kur: https://jrsoftware.org/isinfo.php (ucretsiz)
;   2) PyInstaller ile once main.py'yi derle (build.bat)
;   3) Bu dosyayi Inno Setup Compiler ile ac ve "Compile" de
;      (veya komut satirindan: ISCC.exe installer.iss)
;   4) Cikti: installer_output\LocalTrainerStudio-Setup.exe
;
; GitHub Actions bu dosyayi OTOMATIK derler (bkz. .github/workflows/release.yml),
; yani normalde bunu elle calistirman gerekmez - sadece bir git tag push'laman yeterli.

#define MyAppName "LocalTrainer Studio"
#define MyAppPublisher "Barkin Aydemir"
#define MyAppExeName "LocalTrainerStudio.exe"
; MyAppVersion, GitHub Actions tarafindan /DMyAppVersion=X.Y.Z ile disaridan
; verilir (build_scripts/set_version.py ile senkronize). Yerelde elle
; derlerken bu satiri kendin degistirebilir veya varsayilani kullanabilirsin.
#ifndef MyAppVersion
  #define MyAppVersion "1.1.0"
#endif

[Setup]
AppId={{B6C1E2A4-7F3D-4A9E-9C2B-9C1E2A4B6C1E}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=LocalTrainerStudio-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Uygulama Program Files'a kuruluyor - yonetici yetkisi gerektirir.
; Bu, memory read/write yapan bir arac icin zaten dogal bir gereksinimdir.
PrivilegesRequired=admin
; Otomatik guncelleme, calisirken kendi installer'ini calistirabilsin diye
; ayni AppId ile ustune kurulum (upgrade) sorunsuz calisir.
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; PyInstaller --onefile ciktisi (build.bat calistirildiktan sonra dist/ altinda olusur).
; --uac-admin bayragi sayesinde bu exe, cift tiklandiginda HER ZAMAN
; yonetici yetkisi ister (memory read/write islemleri genelde bunu
; gerektirir - elle "yonetici olarak calistir" secmeyi unutma riskini ortadan kaldirir).
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme
; NOT: profiller/ayarlar/loglar ARTIK Program Files altina degil,
; %LOCALAPPDATA%\LocalTrainerStudio klasorune yaziliyor (bkz. app_paths.py).
; Bu, Program Files'in normalde yazma korumali olmasindan kaynaklanan
; "profilim kayboluyor" sorununu onler - bu yuzden burada profiles/
; klasorunu Program Files'a kopyalamiyoruz, gereksiz olurdu.

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; NOT: "skipifsilent" bilerek KALDIRILDI. Bu bayrak varken, /VERYSILENT
; ile calisan (yani otomatik guncelleme sirasinda kullanilan) kurulumlarda
; bu satir hic calismiyordu - kurulum sessizce bitiyor ama uygulama tekrar
; acilmiyordu. skipifsilent olmadan bu satir HEM interaktif kurulumda HEM
; sessiz/otomatik guncellemede calisir, yani "Simdi Guncelle" sonrasi
; uygulama otomatik olarak yeniden acilir.
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall

[UninstallDelete]
; Kullanicinin kendi profillerini/loglarini kaldirirken SILME - sadece
; uygulamanin kendisini kaldir. (profiles/ ve logs/ klasorleri kasitli
; olarak burada silinmiyor, boylece yeniden kurulumda veriler korunur.)
