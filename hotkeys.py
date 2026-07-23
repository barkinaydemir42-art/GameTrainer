"""
hotkeys.py
Global hotkey dinleme (oyun penceresi odaktayken bile calisir).
pip install keyboard  (Windows'ta yonetici yetkisi gerekebilir)
"""

import keyboard


class HotkeyManager:
    def __init__(self):
        self._registered = {}

    def register(self, hotkey: str, callback):
        if not hotkey:
            return
        self.unregister(hotkey)
        handle = keyboard.add_hotkey(hotkey, callback)
        self._registered[hotkey] = handle

    def unregister(self, hotkey: str):
        handle = self._registered.pop(hotkey, None)
        if handle is not None:
            try:
                keyboard.remove_hotkey(handle)
            except KeyError:
                pass

    def unregister_all(self):
        for hk in list(self._registered.keys()):
            self.unregister(hk)
