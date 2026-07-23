"""
config_manager.py
Uygulama genel ayarlarini (profil disinda kalan kucuk tercihler) saklar:
- guncelleme manifest URL'i
- baslangicta otomatik guncelleme kontrolu yapilsin mi
"""

import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_config.json")

DEFAULTS = {
    "update_manifest_url": "",
    "auto_check_updates": True,
}


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = dict(DEFAULTS)
        merged.update(data)
        return merged
    except Exception:
        return dict(DEFAULTS)


def save_config(config: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
