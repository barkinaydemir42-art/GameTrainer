"""
hotkeys.py
Global hotkey dinleme (oyun penceresi odaktayken bile calisir).
pip install keyboard  (Windows'ta yonetici yetkisi gerekebilir)

ONEMLI (duzeltildi): Eskiden bir hotkey stringine (ornek: 'f1') ikinci bir
cheat daha atandiginda, register() once eskisini unregister ediyor, sonra
yenisini kaydediyordu - yani ayni tusa birden fazla cheat atamak SESSIZCE
ilkini devre disi birakiyordu (WeMod/Wand'daki gibi "bir tusla birden fazla
cheat'i ayni anda ac/kapa" grup davranisi hic calismiyordu). Artik her
hotkey stringi icin BIRDEN FAZLA callback (owner_id ile ayirt edilir)
saklanabiliyor; OS seviyesinde tek bir binding var ama tetiklendiginde
o tusa atanmis TUM callback'ler sirayla calisiyor.
"""

import keyboard


class HotkeyManager:
    def __init__(self):
        # hotkey_str -> {"os_handle": <keyboard handle>, "callbacks": {owner_id: fn}}
        self._registered = {}

    def register(self, hotkey: str, callback, owner_id=None):
        """Bir hotkey'e bir callback baglar. Ayni hotkey'e farkli owner_id'lerle
        birden fazla callback baglanabilir (grup/profil bazli toplu tetikleme
        icin) - hepsi tus basildiginda sirayla calisir."""
        if not hotkey:
            return
        hotkey = hotkey.strip()
        if owner_id is None:
            owner_id = id(callback)

        entry = self._registered.get(hotkey)
        if entry is None:
            entry = {"os_handle": None, "callbacks": {}}
            self._registered[hotkey] = entry

        entry["callbacks"][owner_id] = callback

        if entry["os_handle"] is None:
            def _dispatch(hk=hotkey):
                for cb in list(self._registered.get(hk, {}).get("callbacks", {}).values()):
                    try:
                        cb()
                    except Exception:
                        pass
            entry["os_handle"] = keyboard.add_hotkey(hotkey, _dispatch)

    def unregister(self, hotkey: str, owner_id=None):
        """owner_id verilirse sadece o cheat'in bu hotkey'deki callback'ini
        kaldirir (hotkey'i baskalari hala kullaniyorsa OS binding'i korur).
        owner_id verilmezse (eski davranis) hotkey'e bagli HER SEYI kaldirir."""
        entry = self._registered.get(hotkey)
        if entry is None:
            return
        if owner_id is not None:
            entry["callbacks"].pop(owner_id, None)
            if entry["callbacks"]:
                return  # baska cheat(ler) hala bu tusu kullaniyor, OS binding kalsin

        handle = entry["os_handle"]
        if handle is not None:
            try:
                keyboard.remove_hotkey(handle)
            except KeyError:
                pass
        self._registered.pop(hotkey, None)

    def unregister_owner(self, owner_id):
        """Belirli bir cheat'in TUM hotkey atamalarini (hangi tusa baglanmis
        olurlarsa olsunlar) kaldirir. Cheat silinirken kullanilir."""
        for hotkey in list(self._registered.keys()):
            self.unregister(hotkey, owner_id=owner_id)

    def unregister_all(self):
        for hk in list(self._registered.keys()):
            self.unregister(hk)
