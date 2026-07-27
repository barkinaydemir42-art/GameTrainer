# memory_engine.py — Signature/Pointer Cache patch

## 1) En üste import ekle

```python
import os
```
(ctypes/struct/time importlarının yanına)

## 2) `WatchedAddress` dataclass'ına 3 alan ekle

```python
@dataclass
class WatchedAddress:
    name: str
    address: int
    value_type: str
    frozen: bool = False
    frozen_value: object = None
    hotkey: Optional[str] = None
    offsets: List[int] = field(default_factory=list)

    # --- Imza/Pointer Cache (exe hash'ine bagli) ---
    # AOB taramasiyla bulunan adresler process yeniden baslatildiginda
    # (ASLR yuzunden) gecersiz olur. Bu 3 alan, ayni exe surumu icin
    # taramayi tekrarlamadan adresi yeniden hesaplamayi saglar.
    aob_pattern: Optional[str] = None
    cache_module_offset: Optional[int] = None
    cache_exe_fingerprint: Optional[str] = None
```

## 3) `MemoryEngine.__init__`'e bir satır ekle

```python
        self._unknown_scan_type: Optional[str] = None
        self._fingerprint_cache: dict = {}  # process_id -> fingerprint (yeni satır)
```

## 4) `MemoryEngine` sınıfına yeni metodlar ekle
(`resolve_pointer_chain`'den hemen sonra eklenebilir)

```python
    # ---------------- Imza/Pointer Cache (exe hash'ine bagli) ----------------
    # Bir AOB pattern'i ayni exe surumunde HER ZAMAN ayni MODUL-GORECELI
    # offsette bulunur (ASLR sadece modulun baslangic adresini kaydirir,
    # icindeki goreli konumlari degil). Bu yuzden bir kere bulunan sonucu
    # module_offset = address - base_address seklinde exe fingerprint'iyle
    # birlikte kaydedersek, bir sonraki attach'te agir pattern_scan'i hic
    # calistirmadan address = yeni_base + module_offset ile dogrudan
    # cozebiliriz.

    def get_exe_fingerprint(self) -> Optional[str]:
        """
        Bagli process'in .exe dosyasina dayali ucuz bir 'parmak izi'.
        Amac: oyun GUNCELLENDIGINDE (surum degisti -> AOB adresleri
        kayabilir) cache'i otomatik gecersiz kilmak, ama devasa (GB'larca
        olabilen) bir exe'yi her attach'te bastan hashlemekten kacinmak.

        Yontem: dosya boyutu + degisim zamani + ilk 1MB'in sha256'si.
        Kriptografik butunluk garantisi degil, ama "ayni surum mu"
        sorusu icin milisaniyeler icinde yeterince guvenilir bir cevap.
        """
        if self.pm is None:
            return None
        pid = self.pm.process_id
        if pid in self._fingerprint_cache:
            return self._fingerprint_cache[pid]
        try:
            import psutil
            import hashlib
            exe_path = psutil.Process(pid).exe()
            stat = os.stat(exe_path)
            h = hashlib.sha256()
            h.update(str(stat.st_size).encode())
            h.update(str(int(stat.st_mtime)).encode())
            with open(exe_path, "rb") as f:
                h.update(f.read(1024 * 1024))
            fingerprint = h.hexdigest()
        except Exception:
            return None
        self._fingerprint_cache[pid] = fingerprint
        return fingerprint

    def to_module_offset(self, address: int) -> Optional[int]:
        """Ham bir adresi module-goreli offset'e cevirir (cache'e yazarken kullanilir)."""
        if self.base_address is None or address is None:
            return None
        return address - self.base_address

    def resolve_cached_address(
        self, module_offset: int, exe_fingerprint: Optional[str],
        verify_pattern: Optional[str] = None,
    ) -> Optional[int]:
        """
        Onceden bulunmus bir AOB cache kaydini bu oturum icin cozer.

        - exe_fingerprint eslesmiyorsa (oyun guncellenmis olabilir) None
          doner - cagiran taraf normal AOB taramasina geri donmeli.
        - eslesiyorsa address = base_address + module_offset dondurur.
        - verify_pattern verilirse, o adresteki byte'lar pattern'le hala
          eslesiyor mu diye ucuz bir dogrulama yapilir; eslesmezse
          (beklenmedik durum, ekstra guvenlik icin) yine None doner.
        """
        if self.base_address is None:
            return None
        if not exe_fingerprint or exe_fingerprint != self.get_exe_fingerprint():
            return None
        address = self.base_address + module_offset
        if verify_pattern:
            try:
                pat, mask = self._parse_pattern(verify_pattern)
                data = self.pm.read_bytes(address, len(pat))
                if not self._match_at(data, 0, pat, mask):
                    return None
            except Exception:
                return None
        return address
```
