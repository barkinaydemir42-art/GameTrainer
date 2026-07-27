"""
game_library.py

Steam / Epic Games / GOG / Xbox (UWP) icin kurulu oyunlari otomatik
bulmaya calisir. Sadece Windows'ta anlamli calisir (registry + launcher'a
ozel dosya formatlari kullaniyor); Linux/mac'te veya herhangi bir adim
basarisiz olursa sessizce bos liste doner - uygulamanin geri kalanini
bozmaz.

Kullanim:
    from game_library import scan_all_libraries
    games = scan_all_libraries()   # List[GameEntry]
"""

import os
import re
import json
import glob
import platform
import subprocess
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import List, Optional

from app_paths import get_app_data_dir

IS_WINDOWS = platform.system() == "Windows"

try:
    import winreg
except ImportError:
    winreg = None


@dataclass
class GameEntry:
    name: str
    source: str                    # "Steam" | "Epic" | "GOG" | "Xbox"
    install_dir: str
    exe_path: Optional[str] = None
    steam_appid: Optional[str] = None   # Sadece Steam icin - kapak gorseli icin gerekli

    @property
    def process_name(self) -> Optional[str]:
        if self.exe_path:
            return os.path.basename(self.exe_path)
        return None

    @property
    def cover_url(self) -> Optional[str]:
        """Steam kutuphanesindeki dikey kapak gorseli (600x900, 2:3 oran).
        Steam'in herkese acik CDN'i - API anahtari veya kimlik dogrulama
        gerektirmez. Sadece Steam kaynakli oyunlar icin (appid gerekir)."""
        if self.source == "Steam" and self.steam_appid:
            return f"https://cdn.akamai.steamstatic.com/steam/apps/{self.steam_appid}/library_600x900.jpg"
        return None

    @property
    def cover_url_fallback(self) -> Optional[str]:
        """Bazi eski/az bilinen oyunlarda dikey kapak yok, ama yatay
        'header' gorseli neredeyse her zaman mevcut - yedek olarak kullanilir."""
        if self.source == "Steam" and self.steam_appid:
            return f"https://cdn.akamai.steamstatic.com/steam/apps/{self.steam_appid}/header.jpg"
        return None


# Bu kaliplari iceren .exe'ler genelde oyunun kendisi degil, yardimci/
# kaldirici araclardir - ana yurutulebilir dosyayi tahmin ederken bunlari
# elemek yanlis pozitifleri (crash reporter, redist installer vb.) azaltir.
_EXE_BLACKLIST_PATTERNS = (
    "unins", "vc_redist", "vcredist", "dxsetup", "directx", "crashpad",
    "crashreport", "crashhandler", "easyanticheat", "battleye",
    "setup", "redist", "helper", "dotnet", "prereq",
)


def _looks_like_helper_exe(filename: str) -> bool:
    lower = filename.lower()
    return any(p in lower for p in _EXE_BLACKLIST_PATTERNS)


def _guess_main_exe(install_dir: str) -> Optional[str]:
    """Bir kurulum klasorunde en olasi ana .exe'yi tahmin eder: yardimci
    arac isimlerini eler, kalanlar arasindan en buyuk dosyayi secer (ana
    oyun exe'si genelde launcher/yardimci exe'lerden belirgin buyuktur).
    Cok derin/genis taramadan kacinmak icin 3 seviyeyle sinirlandirilir."""
    if not install_dir or not os.path.isdir(install_dir):
        return None
    candidates = []
    for root, _dirs, files in os.walk(install_dir):
        depth = root[len(install_dir):].count(os.sep)
        if depth > 3:
            continue
        for f in files:
            if f.lower().endswith(".exe") and not _looks_like_helper_exe(f):
                full = os.path.join(root, f)
                try:
                    size = os.path.getsize(full)
                except OSError:
                    size = 0
                candidates.append((size, full))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


# ---------------------------------------------------------------------
# STEAM
# ---------------------------------------------------------------------
def _steam_install_path() -> Optional[str]:
    if not winreg:
        return None
    for hive, key_path, value_name in (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
    ):
        try:
            with winreg.OpenKey(hive, key_path) as k:
                value, _ = winreg.QueryValueEx(k, value_name)
                if value and os.path.isdir(value):
                    return value
        except OSError:
            continue
    return None


def _parse_vdf_libraryfolders(path: str) -> List[str]:
    """libraryfolders.vdf'den ek kutuphane yollarini cikarir. Tam bir VDF
    parser'a gerek yok - Valve'in bu dosya icin kullandigi basit
    "anahtar" "deger" formati stabil oldugu icin regex yeterli."""
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except OSError:
        return []
    return [p.replace("\\\\", "\\") for p in re.findall(r'"path"\s*"([^"]+)"', content)]


def find_steam_games() -> List[GameEntry]:
    games: List[GameEntry] = []
    steam_path = _steam_install_path()
    if not steam_path:
        return games

    library_roots = {steam_path}
    library_roots.update(
        _parse_vdf_libraryfolders(os.path.join(steam_path, "steamapps", "libraryfolders.vdf"))
    )

    for root in library_roots:
        steamapps = os.path.join(root, "steamapps")
        if not os.path.isdir(steamapps):
            continue
        for acf_path in glob.glob(os.path.join(steamapps, "*.acf")):
            try:
                with open(acf_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except OSError:
                continue
            name_m = re.search(r'"name"\s*"([^"]+)"', content)
            installdir_m = re.search(r'"installdir"\s*"([^"]+)"', content)
            appid_m = re.search(r'"appid"\s*"(\d+)"', content)
            if not name_m or not installdir_m:
                continue
            install_dir = os.path.join(steamapps, "common", installdir_m.group(1))
            games.append(GameEntry(
                name=name_m.group(1),
                source="Steam",
                install_dir=install_dir,
                exe_path=_guess_main_exe(install_dir),
                steam_appid=appid_m.group(1) if appid_m else None,
            ))
    return games


# ---------------------------------------------------------------------
# EPIC GAMES
# ---------------------------------------------------------------------
def find_epic_games() -> List[GameEntry]:
    games: List[GameEntry] = []
    manifest_dir = r"C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests"
    if not os.path.isdir(manifest_dir):
        return games
    for item_path in glob.glob(os.path.join(manifest_dir, "*.item")):
        try:
            with open(item_path, "r", encoding="utf-8-sig", errors="ignore") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        name = data.get("DisplayName")
        if not name:
            continue
        install_dir = data.get("InstallLocation", "")
        launch_exe = data.get("LaunchExecutable", "")
        exe_path = None
        if install_dir and launch_exe:
            candidate = os.path.join(install_dir, launch_exe)
            if os.path.isfile(candidate):
                exe_path = candidate
        if not exe_path:
            exe_path = _guess_main_exe(install_dir)
        games.append(GameEntry(name=name, source="Epic", install_dir=install_dir, exe_path=exe_path))
    return games


# ---------------------------------------------------------------------
# GOG
# ---------------------------------------------------------------------
def find_gog_games() -> List[GameEntry]:
    games: List[GameEntry] = []
    if not winreg:
        return games

    root_key = None
    for key_path in (r"SOFTWARE\WOW6432Node\GOG.com\Games", r"SOFTWARE\GOG.com\Games"):
        try:
            root_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
            break
        except OSError:
            continue
    if root_key is None:
        return games

    with root_key:
        i = 0
        while True:
            try:
                subkey_name = winreg.EnumKey(root_key, i)
            except OSError:
                break
            i += 1
            try:
                with winreg.OpenKey(root_key, subkey_name) as sub:
                    def _get(value_name, default=""):
                        try:
                            return winreg.QueryValueEx(sub, value_name)[0]
                        except OSError:
                            return default

                    name = _get("gameName")
                    path = _get("path")
                    exe = _get("exe")
                    if not name:
                        continue
                    exe_path = None
                    if path and exe:
                        candidate = exe if os.path.isabs(exe) else os.path.join(path, exe)
                        if os.path.isfile(candidate):
                            exe_path = candidate
                    if not exe_path:
                        exe_path = _guess_main_exe(path)
                    games.append(GameEntry(name=name, source="GOG", install_dir=path, exe_path=exe_path))
            except OSError:
                continue
    return games


# ---------------------------------------------------------------------
# XBOX / MICROSOFT STORE (UWP) - EN IYI CABA
# ---------------------------------------------------------------------
# UWP paketleri normal .exe kurulumlarindan farkli calisir (paketlenmis,
# genelde WindowsApps altinda, appxmanifest.xml icinde
# <Application Executable="..."> tanimli). Registry'de tek bir sabit yer
# yok; en guvenilir yol PowerShell'in Get-AppxPackage cmdlet'i. Bu
# bilincli olarak "best effort": PowerShell calismazsa veya beklenmedik
# bir cikti donerse sessizce bos liste doner, uygulamayi bozmaz.
_XBOX_SYSTEM_PACKAGE_HINTS = (
    "microsoft.", "windows.", "clipchamp", "bingweather", "gamingapp",
    "xboxapp", "xboxidentityprovider", "xboxspeechtotext", "gamebar",
    "webexperience", "outlook",
)


def find_xbox_games() -> List[GameEntry]:
    games: List[GameEntry] = []
    if not IS_WINDOWS:
        return games
    ps_cmd = (
        "Get-AppxPackage | Where-Object { -not $_.IsFramework -and "
        "$_.SignatureKind -eq 'Store' } | "
        "Select-Object Name, InstallLocation | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=20,
        )
        raw = result.stdout.strip()
        if not raw:
            return games
        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]
    except Exception:
        return games

    for entry in data:
        name = entry.get("Name", "")
        install_loc = entry.get("InstallLocation", "")
        if not name or not install_loc:
            continue
        if any(hint in name.lower() for hint in _XBOX_SYSTEM_PACKAGE_HINTS):
            continue  # sistem/arka plan paketi - oyun degil
        games.append(GameEntry(
            name=name, source="Xbox", install_dir=install_loc,
            exe_path=_find_exe_from_appxmanifest(install_loc),
        ))
    return games


def _find_exe_from_appxmanifest(install_dir: str) -> Optional[str]:
    manifest = os.path.join(install_dir, "AppxManifest.xml")
    if not os.path.isfile(manifest):
        return None
    try:
        with open(manifest, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except OSError:
        return None
    m = re.search(r'Executable="([^"]+)"', content)
    if not m:
        return None
    candidate = os.path.join(install_dir, m.group(1))
    return candidate if os.path.isfile(candidate) else None


# ---------------------------------------------------------------------
def scan_all_libraries() -> List[GameEntry]:
    """Tum kaynaklari tarar. Bir kaynak hata verirse digerlerini
    engellemez (her tarama fonksiyonu ayri try/except icinde calisir -
    bu, agir islemlerin ScanWorker/QThread uzerinde calistirilmasi
    gerektigini vurgulayan mevcut proje kuraliyla tutarlidir)."""
    all_games: List[GameEntry] = []
    for scan_fn in (find_steam_games, find_epic_games, find_gog_games, find_xbox_games):
        try:
            all_games.extend(scan_fn())
        except Exception:
            continue

    # Ayni oyun birden fazla kaynakta gorunebilir (nadir) - exe yoluna
    # gore de-duplicate et.
    seen = set()
    unique = []
    for g in all_games:
        key = (g.exe_path or g.install_dir or g.name).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(g)
    unique.sort(key=lambda g: g.name.lower())
    return unique


# ---------------------------------------------------------------------
# KAPAK GORSELLERI (Steam CDN)
# ---------------------------------------------------------------------
# Sadece Steam icin - Epic/GOG/Xbox'in bu tarz herkese acik, appid'siz
# bir CDN'i yok (Epic/GOG kapaklari icin ayri, imzali/kimlik dogrulamali
# API'ler gerekir - kapsam disi birakildi, kartlar bu kaynaklar icin
# placeholder ikonla gosterilir).
def _covers_cache_dir() -> str:
    d = os.path.join(get_app_data_dir(), "covers")
    os.makedirs(d, exist_ok=True)
    return d


def get_cached_cover_path(game: GameEntry) -> Optional[str]:
    """Diskte onceden indirilmis bir kapak varsa yolunu dondurur. AG
    CAGRISI YAPMAZ - sadece dosya sistemine bakar, bu yuzden UI (ana)
    thread'inden guvenle cagrilabilir (ornegin kart ilk olusturulurken)."""
    if not game.steam_appid:
        return None
    path = os.path.join(_covers_cache_dir(), f"{game.steam_appid}.jpg")
    return path if os.path.isfile(path) else None


def download_cover(game: GameEntry, timeout: int = 8) -> Optional[str]:
    """Kapak gorselini indirir, diskte kalici olarak onbelleğe alir ve
    yerel dosya yolunu dondurur.

    AG CAGRISI YAPAR - bu fonksiyon UI thread'inde DEGIL, bir arka plan
    thread'inde cagrilmalidir (bkz. main.py'deki CoverFetchWorker), yoksa
    her kapak indirmesi arayuzu kisa sureligine dondurur.

    Once dikey kutuphane gorselini (`cover_url`) dener; bu 404 donerse
    (bazi eski/az bilinen oyunlarda dikey kapak yayinlanmamis olabilir)
    yatay 'header' gorseline (`cover_url_fallback`) duser. Appid yoksa,
    ag hatasi olursa veya iki URL de basarisiz olursa sessizce None
    doner - kart placeholder ikonuyla gosterilmeye devam eder, uygulama
    bozulmaz.
    """
    cached = get_cached_cover_path(game)
    if cached:
        return cached
    if not game.steam_appid:
        return None

    dest = os.path.join(_covers_cache_dir(), f"{game.steam_appid}.jpg")
    for url in (game.cover_url, game.cover_url_fallback):
        if not url:
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "LocalTrainerStudio-CoverFetch"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
            if not data:
                continue
            # Once gecici dosyaya yaz, sonra atomik olarak yeniden adlandir -
            # yarim inen bir dosyanin gecerli bir kapakmis gibi onbellekte
            # kalmasini onler (ornegin indirme sirasinda ag kesilirse).
            tmp_path = dest + ".tmp"
            with open(tmp_path, "wb") as f:
                f.write(data)
            os.replace(tmp_path, dest)
            return dest
        except (urllib.error.URLError, OSError, ValueError):
            continue
    return None
