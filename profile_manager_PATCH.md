# profile_manager.py — Signature Cache patch

`save_profile` içindeki cheat dict'ine 3 alan ekle:

```python
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
                # --- Imza cache (yeni) ---
                "aob_pattern": getattr(a, "aob_pattern", None),
                "cache_module_offset": getattr(a, "cache_module_offset", None),
                "cache_exe_fingerprint": getattr(a, "cache_exe_fingerprint", None),
            }
            for a in addresses
        ],
    }
```

`load_profile` değişmiyor (zaten ham dict döndürüyor); yeni alanlar
`main.py`'deki `_load_profile_data` içinde `c.get(...)` ile okunacak.
