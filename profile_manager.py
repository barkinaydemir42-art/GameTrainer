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

PROFILES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles")


def _profile_path(process_name: str) -> str:
    safe_name = process_name.strip()
    return os.path.join(PROFILES_DIR, f"{safe_name}.json")


def profile_exists(process_name: str) -> bool:
    return os.path.exists(_profile_path(process_name))


def save_profile(process_name: str, game_label: str, addresses: List[WatchedAddress]):
    """
    Profili kaydeder. Iki tur cheat vardir:
    - offsets doluysa: kalici pointer zinciri, oyun/pc yeniden baslatilsa da gecerli.
    - offsets bossa: ham adres (Scanner'dan bulunan). Bu adres SADECE oyun
      process'i yeniden baslatilana kadar geçerlidir (ASLR yuzunden oyun
      kapatilip acilinca degisir). Yine de ayni oturum icinde (uygulamayi
      kapatip acmak ama oyunu kapatmamak) ise yarar, bu yuzden saklaniyor.
    """
    os.makedirs(PROFILES_DIR, exist_ok=True)
    data = {
        "process_name": process_name,
        "game_label": game_label,
        "cheats": [
            {
                "name": a.name,
                "value_type": a.value_type,
                "address": a.address,
                "offsets": a.offsets,
                "hotkey": a.hotkey,
                "permanent": bool(a.offsets),
            }
            for a in addresses
        ],
    }
    with open(_profile_path(process_name), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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
