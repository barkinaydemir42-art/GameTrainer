"""
updater.py
LocalTrainer Studio icin surum kontrolu + kendi kendini guncelleme motoru.

NASIL CALISIR (ozet):
1) Sen (gelistirici) bir "manifest" JSON dosyasini bir yerde barindirirsin
   (en kolayi: GitHub'da bir repo + raw.githubusercontent.com linki - ucretsiz).
   Ornek manifest:
   {
     "version": "1.1.0",
     "changelog": "AOB tarama hizlandirildi, yeni sayi tipleri eklendi.",
     "download_url": "https://.../LocalTrainerStudio-1.1.0.zip",
     "sha256": "opsiyonel_dosya_hash_i_buraya"
   }
2) Uygulama bu URL'i cekip CURRENT_VERSION ile karsilastirir.
3) Yeni surum varsa, indirir, (varsa) SHA256 ile dogrular.
4) Eger uygulama PyInstaller ile derlenmis (.exe) halde calisiyorsa,
   kendini degistirip yeniden baslatabilir (Windows'ta calisan bir exe
   dogrudan uzerine yazilamadigi icin kucuk bir .bat "koprusu" kullanilir).
   Kaynak koddan (python main.py) calisiyorsa, guvenlik/basitlik icin
   otomatik dosya degistirme YAPILMAZ - kullaniciya indirilen dosyanin
   yolu gosterilir, elle guncellemesi istenir.

GUVENLIK NOTU: Bu modul sadece kullanicinin KENDI belirledigi bir
manifest URL'inden indirme yapar - hicbir sabit/gizli sunucuya baglanmaz.
Indirilen dosyanin SHA256'si manifestte varsa dogrulanir; yoksa kullaniciya
acikca "dogrulanamadi" uyarisi verilir.
"""

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

CURRENT_VERSION = "1.1.0"


@dataclass
class UpdateInfo:
    version: str
    changelog: str
    download_url: str
    sha256: Optional[str] = None
    # installer=True ise indirilen dosya bir Inno Setup Setup.exe'sidir ve
    # sessizce calistirilir (kopyala-degistir yerine). GitHub Actions
    # pipeline'i bunu otomatik bu sekilde uretir (bkz. installer.iss).
    installer: bool = False
    silent_args: str = ""


def _parse_version(v: str) -> tuple:
    parts = []
    for p in v.strip().split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def is_newer(remote_version: str, local_version: str = CURRENT_VERSION) -> bool:
    return _parse_version(remote_version) > _parse_version(local_version)


def check_for_update(manifest_url: str, timeout: int = 10) -> Optional[UpdateInfo]:
    """
    Manifest URL'ini ceker. Yeni surum varsa UpdateInfo, yoksa None dondurur.
    Ag hatasi durumunda exception firlatir (cagiran taraf yakalamali).
    """
    if not manifest_url:
        raise ValueError("Guncelleme manifest URL'i bos - Ayarlar'dan gir.")
    req = urllib.request.Request(manifest_url, headers={"User-Agent": "LocalTrainerStudio-Updater"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    remote_version = data.get("version", "0.0.0")
    if not is_newer(remote_version):
        return None
    return UpdateInfo(
        version=remote_version,
        changelog=data.get("changelog", ""),
        download_url=data.get("download_url", ""),
        sha256=data.get("sha256"),
        installer=bool(data.get("installer", False)),
        silent_args=data.get("silent_args", ""),
    )


def download_file(url: str, dest_path: str, progress_cb: Optional[Callable[[int, int], None]] = None):
    """Dosyayi indirir. progress_cb(indirilen_bayt, toplam_bayt) periyodik cagrilir."""
    req = urllib.request.Request(url, headers={"User-Agent": "LocalTrainerStudio-Updater"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        chunk_size = 65536
        with open(dest_path, "wb") as out:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                out.write(chunk)
                downloaded += len(chunk)
                if progress_cb:
                    progress_cb(downloaded, total)


def verify_sha256(file_path: str, expected_hex: str) -> bool:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().lower() == expected_hex.lower()


def is_frozen() -> bool:
    """PyInstaller ile derlenmis (.exe) halde mi calisiyoruz, yoksa kaynak koddan mi?"""
    return getattr(sys, "frozen", False)


def build_installer_launch_command(installer_path: str, silent_args: str) -> list:
    """
    Kurulum dosyasini calistirmak icin komut listesini olusturur.
    Bilerek saf/yan-etkisiz bir fonksiyon - boylece gercek bir surec
    baslatmadan test edilebilir.
    """
    command = [installer_path]
    if silent_args:
        command.extend(shlex.split(silent_args))
    return command


def apply_installer_update(installer_path: str, silent_args: str = ""):
    """
    Indirilen Setup.exe'yi sessiz modda calistirir.
    Inno Setup'in /CLOSEAPPLICATIONS ve /RESTARTAPPLICATIONS bayraklari
    calisan LocalTrainerStudio.exe'yi otomatik kapatip kurulumdan sonra
    yeniden acar - bu yuzden eski (onefile .exe uzerine kopyalama) yontemine
    gore cok daha guvenilirdir ve dosya kilidi sorunlariyla ugrasmaz.
    """
    command = build_installer_launch_command(installer_path, silent_args)
    subprocess.Popen(command)
    # Cagiran taraf (main.py) bu fonksiyondan sonra kendi uygulamasini
    # kapatmali (QApplication.quit()) - Inno Setup zaten kapatmaya
    # calisacaktir ama biz de temiz bir kapanis icin proaktif davraniriz.


def apply_update_and_restart(new_exe_path: str):
    """
    ESKI YONTEM (installer=False oldugunda kullanilir, ornegin manuel/
    zip tabanli dagitimlar icin). SADECE derlenmis (.exe) halde
    calisirken anlamlidir. Su anki .exe'nin uzerine yeni .exe'yi yazan
    bir .bat script'i olusturup calistirir, sonra mevcut uygulamayi
    kapatir. .bat, uygulama tamamen kapanana kadar bekler (dosya kilidi
    cozulsun diye), eski dosyayi yenisiyle degistirir ve yeniden baslatir.

    NOT: installer.iss + GitHub Actions pipeline'i kullaniyorsan bu
    fonksiyona GENELDE ihtiyacin olmaz - manifestte "installer": true
    varsa main.py otomatik olarak apply_installer_update()'i kullanir.
    """
    if not is_frozen():
        raise RuntimeError(
            "Otomatik dosya degistirme sadece derlenmis .exe halinde desteklenir. "
            "Kaynak koddan calisirken indirilen dosyayi elle uygulaman gerekiyor."
        )

    current_exe = sys.executable  # calisan .exe'nin tam yolu
    bat_path = os.path.join(tempfile.gettempdir(), "lts_update.bat")
    bat_content = f"""@echo off
:wait_loop
tasklist /FI "PID eq {os.getpid()}" | find "{os.getpid()}" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto wait_loop
)
copy /Y "{new_exe_path}" "{current_exe}" >nul
start "" "{current_exe}"
del "%~f0"
"""
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(bat_content)

    subprocess.Popen(["cmd", "/c", bat_path], creationflags=subprocess.CREATE_NEW_CONSOLE)
    # Cagiran taraf (main.py) bu fonksiyondan sonra uygulamayi kapatmali (QApplication.quit()).


def download_and_prepare_update(info: UpdateInfo, progress_cb=None) -> str:
    """
    Guncellemeyi gecici bir klasore indirir, (varsa) SHA256 dogrular.
    Indirilen dosyanin yolunu dondurur. Hata durumunda exception firlatir.
    """
    if not info.download_url:
        raise ValueError("Manifestte download_url yok.")
    tmp_dir = tempfile.mkdtemp(prefix="lts_update_")
    filename = info.download_url.split("/")[-1] or "update.bin"
    dest_path = os.path.join(tmp_dir, filename)
    download_file(info.download_url, dest_path, progress_cb=progress_cb)

    if info.sha256:
        if not verify_sha256(dest_path, info.sha256):
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise ValueError(
                "SHA256 dogrulamasi BASARISIZ - indirilen dosya bozuk veya "
                "beklenmedik. Guvenlik icin guncelleme uygulanmadi."
            )
    return dest_path
