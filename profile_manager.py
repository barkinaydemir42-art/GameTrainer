"""
profile_manager.py
Her oyun icin bir JSON "trainer profili" saklar/yukler.
Wand'daki "exe'yi sec, trainer otomatik yuklensin" davranisini
bu dosya isimleri process adiyla eslestirerek taklit eder.

Profil dosya adi = process adi (ornek: Palworld-Win64-Shipping.exe.json)
"""

import json
import os
from typing import List, Optional

from memory_engine import WatchedAddress
from app_paths import get_app_data_dir

PROFILES_DIR = os.path.join(get_app_data_dir(), "profiles")


def _profile_path(process_name: str) -> str:
    safe_name = process_name.strip()
    return os.path.join(PROFILES_DIR, f"{safe_name}.json")


def profile_exists(process_name: str) -> bool:
    return os.path.exists(_profile_path(process_name))


def save_profile(
    process_name: str,
    game_label: str,
    addresses: List[WatchedAddress],
    exe_fingerprint: Optional[str] = None,
):
    """
    Profili kaydeder. Iki tur cheat vardir:
    - offsets doluysa: kalici pointer zinciri, oyun/pc yeniden baslatilsa da gecerli.
    - offsets bossa: ham adres (Scanner'dan bulunan). Bu adres SADECE oyun
      process'i yeniden baslatilana kadar geçerlidir (ASLR yuzunden oyun
      kapatilip acilinca degisir). Yine de ayni oturum icinde (uygulamayi
      kapatip acmak ama oyunu kapatmamak) ise yarar, bu yuzden saklaniyor.

    anchor_pattern/anchor_disp_pos/anchor_instr_len doluysa (Auto Pointer
    Repair), bunlar da kaydedilir - eski profillerde bu alanlar yok, ama
    load_profile()'in .get(...) ile okumasi sayesinde geriye donuk uyumlu
    (eksikse None/varsayilan olarak yuklenir, anchor'siz normal pointer
    zinciri gibi davranir).

    exe_fingerprint (Version Checker): kayit anindaki oyun exe'sinin
    boyut+degisim-zamani parmak izi. Profil daha sonra yuklenirken bagli
    oyunun GUNCEL parmak izi bununla karsilastirilir - farkliysa oyun
    guncellenmis olabilir demektir; main.py bu durumda kullaniciyi uyarir
    (anchor_pattern'i olan cheat'ler Auto Pointer Repair sayesinde yine de
    kendiliginden dogru adresi bulmaya calisir, ama struct'in kendisi
    degistiyse bu uyari yine de faydalidir). Mevcut "signature_cache"
    varsa (bkz. save_signature_cache) korunur.
    """
    os.makedirs(PROFILES_DIR, exist_ok=True)
    existing = load_profile(process_name) or {}
    data = {
        "process_name": process_name,
        "game_label": game_label,
        "exe_fingerprint": exe_fingerprint,
        "signature_cache": existing.get("signature_cache", {}),
        "cheats": [
            {
                "name": a.name,
                "value_type": a.value_type,
                "address": a.address,
                "offsets": a.offsets,
                "hotkey": a.hotkey,
                "permanent": bool(a.offsets),
                "anchor_pattern": a.anchor_pattern,
                "anchor_disp_pos": a.anchor_disp_pos,
                "anchor_instr_len": a.anchor_instr_len,
            }
            for a in addresses
        ],
    }
    with open(_profile_path(process_name), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_signature_cache(process_name: str, pattern: str, exe_fingerprint: Optional[str], module_offset: int):
    """
    Signature/Pointer Cache: bir AOB pattern'i icin bulunan adresi, MODUL
    BASINDAN OFFSET olarak (mutlak adres degil - ASLR yuzunden mutlak adres
    her oyun acilisinda degisir, ama ayni exe surumunde bir patern'in
    modul icindeki GORECELI konumu genelde SABIT kalir) process'in profil
    dosyasina kaydeder. Bir sonraki tarama isteginde bu offset once
    dogrulanir (bkz. MemoryEngine.verify_pattern_at); tutarsa tam bir
    bellek taramasi hic yapilmadan aninda sonuc donulebilir.

    NOT: Bu, Auto Pointer Repair'in anchor_pattern'inden FARKLI bir
    mekanizmadir - anchor_pattern tek bir cheat'in KALICI pointer zincirini
    her okumada yeniden dogrulayip onarirken, bu cache genel AOB
    (Scanner sekmesindeki "Auto Signature Builder") aramalarini hizlandirir.

    Profil dosyasi henuz yoksa (kullanici hic "Profili Kaydet" yapmadiysa)
    sadece cache'i tasiyan minimal bir profil olusturulur - boylece
    cache ozelligi "once profil kaydet" sartina bagli kalmaz.
    """
    os.makedirs(PROFILES_DIR, exist_ok=True)
    data = load_profile(process_name) or {
        "process_name": process_name,
        "game_label": process_name,
        "exe_fingerprint": exe_fingerprint,
        "signature_cache": {},
        "cheats": [],
    }
    data.setdefault("signature_cache", {})
    data["signature_cache"][pattern] = {
        "exe_fingerprint": exe_fingerprint,
        "module_offset": module_offset,
    }
    with open(_profile_path(process_name), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_signature_cache(process_name: str, pattern: str) -> Optional[dict]:
    """Bir pattern icin daha once kaydedilmis cache girdisini dondurur
    ({"exe_fingerprint":..., "module_offset":...}) veya yoksa None."""
    data = load_profile(process_name)
    if not data:
        return None
    return data.get("signature_cache", {}).get(pattern)


def load_profile(process_name: str) -> Optional[dict]:
    path = _profile_path(process_name)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_profiles() -> List[str]:
    if not os.path.exists(PROFILES_DIR):
        return []
    return [f[:-5] for f in os.listdir(PROFILES_DIR) if f.endswith(".json")]
