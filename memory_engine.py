"""
memory_engine.py
Wand/Cheat Engine mantığında bellek tarama ve okuma/yazma motoru.
SADECE WINDOWS'ta çalışır (ReadProcessMemory / WriteProcessMemory kullanır).

Gereksinim: pip install pymem psutil
"""

import ctypes
import struct
import time
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import pymem
import pymem.process

# ---- Tip tanımları ----
# Not: 'byte' bilincli olarak UNSIGNED (0-255) - kullanicilar genelde
# kucuk sayilari (14, 100, 200 gibi) "byte" olarak arar ve 127 uzeri
# degerlerde eskiden struct.error firlatiliyordu.
TYPE_MAP = {
    "int16": ("h", 2),
    "uint16": ("H", 2),
    "int32": ("i", 4),
    "uint32": ("I", 4),
    "int64": ("q", 8),
    "uint64": ("Q", 8),
    "float": ("f", 4),
    "double": ("d", 8),
    "byte": ("B", 1),
}
ALL_TYPES = list(TYPE_MAP.keys())

# Windows sabitleri (VirtualQueryEx için)
MEM_COMMIT = 0x1000
PAGE_READWRITE = 0x04
PAGE_READONLY = 0x02
PAGE_EXECUTE_READWRITE = 0x40
PAGE_GUARD = 0x100
SCANNABLE_PROTECT = {PAGE_READWRITE, PAGE_EXECUTE_READWRITE}


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


def _configure_kernel32():
    """
    VirtualQueryEx icin argtypes/restype'i acikca tanimlar.
    Bunlar tanimlanmazsa ctypes bazi sistemlerde donus degerini/adresi
    32-bit varsayip erken kesebiliyor - bu, taramanin bellegin sadece kucuk
    bir kismini gormesine (dusuk sonuc sayisina) yol acan sessiz bir hataydi.
    """
    kernel32 = ctypes.windll.kernel32
    kernel32.VirtualQueryEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.POINTER(MEMORY_BASIC_INFORMATION),
        ctypes.c_size_t,
    ]
    kernel32.VirtualQueryEx.restype = ctypes.c_size_t
    return kernel32


@dataclass
class ScanResult:
    address: int
    value: object


@dataclass
class WatchedAddress:
    """Kullanıcının izleme listesine eklediği tek bir bellek adresi."""
    name: str
    address: int
    value_type: str
    frozen: bool = False
    frozen_value: object = None
    hotkey: Optional[str] = None
    # profil olarak kaydederken process'e göre değişmeyen offset zinciri
    offsets: List[int] = field(default_factory=list)


class MemoryEngine:
    def __init__(self):
        self.pm: Optional[pymem.Pymem] = None
        self.process_name: Optional[str] = None
        self.base_address: Optional[int] = None
        self.base_address_error: Optional[str] = None
        self.module_size: int = 0
        self._last_results: List[ScanResult] = []
        self.last_scan_truncated: bool = False
        # 'Bilinmeyen ilk deger' tarama modu icin: adres -> onceki byte snapshot
        self._unknown_scan_snapshot: dict = {}
        self._unknown_scan_type: Optional[str] = None

    # ---------------- Process yönetimi ----------------

    def attach(self, process_name: str):
        """Process adına göre bağlan (ör: 'Palworld-Win64-Shipping.exe').
        Zaten baska bir process'e bagliysa, eski handle'i once duzgunce kapatir
        (aksi halde her attach'te bir Windows handle sizdirilir)."""
        if self.pm is not None:
            self.detach()
        self.pm = pymem.Pymem(process_name)
        self.process_name = process_name
        self.base_address = None
        self.base_address_error = None
        self.module_size = 0
        try:
            mod = pymem.process.module_from_name(self.pm.process_handle, process_name)
            self.base_address = mod.lpBaseOfDll
            self.module_size = getattr(mod, "SizeOfImage", 0)
        except Exception as e:
            # Bagli olsak bile modul/base adres bulunamayabilir (ornek: 32-bit/
            # 64-bit uyumsuzlugu, izin sorunu). Bu durumda manuel/AOB tarama ve
            # ham adres ekleme calisir ama pointer zinciri (offsets) calismaz.
            self.base_address_error = str(e)
        return True

    def detach(self):
        """Baglantiyi duzgunce kapatir (process handle'ini serbest birakir)."""
        if self.pm is not None:
            try:
                self.pm.close_process()
            except Exception:
                pass
        self.pm = None
        self.process_name = None
        self.base_address = None
        self._last_results = []

    def is_process_alive(self) -> bool:
        """Bagli process hala calisiyor mu kontrol eder (oyun kapatildiysa False doner)."""
        if self.pm is None:
            return False
        try:
            import psutil
            return psutil.pid_exists(self.pm.process_id)
        except Exception:
            return True

    @property
    def attached(self) -> bool:
        return self.pm is not None

    # ---------------- Düşük seviye okuma/yazma ----------------

    def read_value(self, address: int, value_type: str):
        fmt, size = TYPE_MAP[value_type]
        data = self.pm.read_bytes(address, size)
        return struct.unpack("<" + fmt, data)[0]

    def write_value(self, address: int, value_type: str, value):
        fmt, size = TYPE_MAP[value_type]
        data = struct.pack("<" + fmt, value)
        self.pm.write_bytes(address, data, size)

    def read_pointer_chain(self, offsets: List[int], value_type: str):
        """base + offsets[0] -> pointer'i oku -> +offsets[1] -> pointer'i oku -> ...
        -> son offsette DEGERI oku (pointer degil)."""
        final_addr = self.resolve_pointer_chain(offsets)
        return self.read_value(final_addr, value_type)

    def resolve_pointer_chain(self, offsets: List[int]) -> int:
        """
        Offset zincirini cozup son (fiziksel) adresi dondurur.

        ONEMLI DUZELTME: onceki surumde son offsetten once bir dereference
        eksikti (addr+offsets[-1] direkt hesaplaniyordu, pointer okunmadan).
        Bu, kaydedilen her pointer-chain profilinin YANLIS adrese gitmesine
        neden oluyordu. Dogru mantik: N offset varsa (N-1) kere "pointer'i
        oku, offset ekle" yapilir; SADECE tek offset varsa (dogrudan statik
        adres) hic dereference yapilmaz.
        """
        if not offsets:
            raise ValueError("offsets bos olamaz")
        if self.base_address is None:
            raise ValueError(
                "Bu process icin module base adresi bulunamadi "
                f"({getattr(self, 'base_address_error', 'bilinmeyen sebep')}). "
                "Pointer zinciri kullanamazsin, ham/manuel adres veya AOB kullan."
            )
        addr = self.base_address + offsets[0]
        for off in offsets[1:]:
            addr = self.pm.read_longlong(addr) + off
        return addr

    # ---------------- Bellek bölgelerini tarama (Cheat Engine tarzı) ----------------

    def _enumerate_regions(self):
        """Process'in yazılabilir bellek bölgelerini döndürür (start, size)."""
        kernel32 = _configure_kernel32()
        handle = self.pm.process_handle
        mbi = MEMORY_BASIC_INFORMATION()
        address = 0
        regions = []
        # Kullanıcı alanı sınırı (64-bit için yaklaşık üst limit)
        max_address = 0x7FFFFFFFFFFF
        while address < max_address:
            result = kernel32.VirtualQueryEx(
                handle, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi)
            )
            if result == 0:
                break
            if (
                mbi.State == MEM_COMMIT
                and mbi.Protect in SCANNABLE_PROTECT
                and not (mbi.Protect & PAGE_GUARD)
                and mbi.RegionSize > 0
            ):
                regions.append((mbi.BaseAddress or 0, mbi.RegionSize))
            address += mbi.RegionSize if mbi.RegionSize else 0x1000
        return regions

    # Bir bolgeyi tek seferde okumak yerine parca parca (chunk) okur.
    # Boylece bir bolgenin KUCUK bir kismi okunamasa bile o bolgedeki
    # diger tum eslesmeleri kaybetmeyiz (onceki davranis: tek hata =
    # tum bolgeyi atla). overlap, deger/pattern sinir (chunk) kesitini
    # gecen eslesmeleri kacirmamak icin bir onceki chunk'tan tasinan
    # byte sayisidir.
    CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB

    def _iter_region_chunks(self, base: int, region_size: int, overlap: int):
        offset = 0
        while offset < region_size:
            this_size = min(self.CHUNK_SIZE, region_size - offset)
            try:
                data = self.pm.read_bytes(base + offset, this_size)
            except Exception:
                # Sadece bu kucuk parcayi atla, bolgenin geri kalanini
                # okumaya devam et.
                offset += this_size
                continue
            yield base + offset, data
            step = this_size - overlap if this_size > overlap else this_size
            offset += step

    # Bir tarama turunda tutulacak azami sonuc sayisi. Bunun uzerinde
    # cikan sonuclar ("value" cok yaygin bir bayt/deger oldugu icin)
    # pratikte kullanilamaz ve bellegi sisirir; bu durumda kullaniciyi
    # uyarmak icin self.last_scan_truncated bayragini set ederiz.
    MAX_SCAN_RESULTS = 200_000

    def first_scan(self, value, value_type: str) -> List[ScanResult]:
        """İlk tarama: verilen değere eşit tüm adresleri bulur."""
        fmt, size = TYPE_MAP[value_type]
        target = struct.pack("<" + fmt, value)
        overlap = size - 1
        results = []
        self.last_scan_truncated = False
        for base, region_size in self._enumerate_regions():
            for chunk_base, data in self._iter_region_chunks(base, region_size, overlap):
                start = 0
                while True:
                    idx = data.find(target, start)
                    if idx == -1:
                        break
                    results.append(ScanResult(chunk_base + idx, value))
                    start = idx + 1
                    if len(results) >= self.MAX_SCAN_RESULTS:
                        self.last_scan_truncated = True
                        self._last_results = results
                        return results
        self._last_results = results
        return results

    def next_scan(
        self,
        value_type: str,
        mode: str = "exact",
        value=None,
        previous_values: Optional[dict] = None,
    ) -> List[ScanResult]:
        """
        Önceki sonuçları yeniden okuyup filtreler.
        mode: 'exact' (yeni deger gir), 'changed', 'unchanged', 'increased', 'decreased'
        """
        new_results = []
        for r in self._last_results:
            try:
                current = self.read_value(r.address, value_type)
            except Exception:
                continue
            keep = False
            if mode == "exact":
                keep = current == value
            elif mode == "changed":
                keep = current != r.value
            elif mode == "unchanged":
                keep = current == r.value
            elif mode == "increased":
                keep = current > r.value
            elif mode == "decreased":
                keep = current < r.value
            if keep:
                new_results.append(ScanResult(r.address, current))
        self._last_results = new_results
        return new_results

    @property
    def last_results(self):
        return self._last_results

    # ---------------- AOB / Pattern tarama ----------------

    @staticmethod
    def _parse_pattern(pattern: str) -> Tuple[bytes, bytes]:
        """
        'A1 ?? ?? ?? ?? 8B 45' gibi bir pattern'i (bytes, mask) ciftine cevirir.
        mask: eslesecek byte icin 0xFF, wildcard (??) icin 0x00
        """
        tokens = pattern.strip().split()
        pat_bytes = bytearray()
        mask = bytearray()
        for tok in tokens:
            if tok in ("??", "?"):
                pat_bytes.append(0x00)
                mask.append(0x00)
            else:
                pat_bytes.append(int(tok, 16))
                mask.append(0xFF)
        return bytes(pat_bytes), bytes(mask)

    @staticmethod
    def _match_at(data: bytes, offset: int, pat: bytes, mask: bytes) -> bool:
        if offset + len(pat) > len(data):
            return False
        for i in range(len(pat)):
            if mask[i] and data[offset + i] != pat[i]:
                return False
        return True

    # Bellekte/binary'lerde asiri sik rastlanan dolgu byte'lari - bunlari
    # capa olarak secmekten kacinilir (secilirlerse bytes.find neredeyse
    # her yerde "hit" doner, gercek BMH avantajini yok eder).
    _COMMON_FILLER_BYTES = {0x00, 0xFF, 0x90, 0xCC}

    def pattern_scan(self, pattern: str, max_results: int = 200) -> List[int]:
        """
        AOB/pattern tarama. Ornek pattern: 'A1 ?? ?? ?? ?? 8B 45 FC'
        Tum yazilabilir/okunabilir bolgeleri tarar, eslesen adresleri dondurur.

        Performans notu: onceki surum pattern'deki ILK sabit byte'i capa
        olarak kullaniyordu. Sorun: bu byte 0x00 gibi cok yaygin bir deger
        olursa (sik rastlanir), bytes.find neredeyse her pozisyonda "aday"
        buluyor ve capa avantaji kayboluyor. Bu surum, pattern icindeki
        SABIT byte'lar arasindan once 0x00/0xFF/0x90/0xCC gibi asiri yaygin
        dolgu byte'i OLMAYAN birini secmeye calisiyor (varsa), yoksa ilk
        sabit byte'a duser. Bu basit degisiklik, gercek oyun pattern'lerinde
        (genelde 0x00 iceren) taramayi belirgin sekilde hizlandirir.
        """
        pat, mask = self._parse_pattern(pattern)
        if not pat:
            return []

        fixed_indices = [i for i, m in enumerate(mask) if m]
        if not fixed_indices:
            return []  # Pattern tamamen wildcard - anlamli degil

        anchor_idx = next(
            (i for i in fixed_indices if pat[i] not in self._COMMON_FILLER_BYTES),
            fixed_indices[0],
        )
        anchor_byte = bytes([pat[anchor_idx]])

        overlap = len(pat) - 1
        found = []
        for base, region_size in self._enumerate_regions():
            for chunk_base, data in self._iter_region_chunks(base, region_size, overlap):
                search_from = 0
                while True:
                    hit = data.find(anchor_byte, search_from)
                    if hit == -1:
                        break
                    candidate_start = hit - anchor_idx
                    search_from = hit + 1
                    if candidate_start < 0:
                        continue
                    if self._match_at(data, candidate_start, pat, mask):
                        found.append(chunk_base + candidate_start)
                        if len(found) >= max_results:
                            return found
        return found

    # ---------------- Bilinmeyen Ilk Deger Taramasi ----------------
    # Klasik Cheat Engine "Unknown initial value" ozelligi: kullanici
    # aranan sayiyi bilmiyor ama oyunda bir olay olduktan sonra (hasar
    # aldi, para harcadi vb.) degerin arttigini/azaldigini/degistigini
    # biliyor. Once TUM bellegin bir anlik goruntusunu (snapshot) aliriz,
    # sonra next_scan_unknown ile "changed/increased/decreased" filtreleriz.
    #
    # UYARI: bu islem agirdir (tum commit edilmis bellegi kopyalar).
    # Guvenlik icin varsayilan hizalama 4 byte ve MAX_SCAN_RESULTS ile
    # sinirlandirilmistir.

    def first_scan_unknown(self, value_type: str, alignment: int = 4) -> int:
        """
        Snapshot alir (adres -> o anki deger). Sonuc olarak kac adres
        izlendigini dondurur (bunlar next_scan_unknown ile filtrelenir).
        """
        fmt, size = TYPE_MAP[value_type]
        snapshot = {}
        self._unknown_scan_type = value_type
        for base, region_size in self._enumerate_regions():
            for chunk_base, data in self._iter_region_chunks(base, region_size, size - 1):
                limit = len(data) - size
                pos = 0
                while pos <= limit:
                    try:
                        val = struct.unpack_from("<" + fmt, data, pos)[0]
                    except struct.error:
                        pos += alignment
                        continue
                    snapshot[chunk_base + pos] = val
                    pos += alignment
                    if len(snapshot) >= self.MAX_SCAN_RESULTS:
                        self.last_scan_truncated = True
                        self._unknown_scan_snapshot = snapshot
                        return len(snapshot)
        self._unknown_scan_snapshot = snapshot
        self.last_scan_truncated = False
        return len(snapshot)

    def next_scan_unknown(self, mode: str = "changed") -> List[ScanResult]:
        """
        mode: 'changed', 'unchanged', 'increased', 'decreased'
        Snapshot'taki her adresi tekrar okuyup filtreler ve yeni snapshot'i
        bir sonraki tur icin gunceller (Cheat Engine'deki gibi ust uste
        daraltabilirsin).
        """
        if not self._unknown_scan_snapshot or not self._unknown_scan_type:
            raise ValueError("Once 'Bilinmeyen Ilk Deger' ile ilk taramayi yap.")
        value_type = self._unknown_scan_type
        new_snapshot = {}
        results = []
        for address, old_value in self._unknown_scan_snapshot.items():
            try:
                current = self.read_value(address, value_type)
            except Exception:
                continue
            keep = False
            if mode == "changed":
                keep = current != old_value
            elif mode == "unchanged":
                keep = current == old_value
            elif mode == "increased":
                keep = current > old_value
            elif mode == "decreased":
                keep = current < old_value
            if keep:
                new_snapshot[address] = current
                results.append(ScanResult(address, current))
        self._unknown_scan_snapshot = new_snapshot
        self._last_results = results
        return results

    # ---------------- Pointer Scan Yardimcisi ----------------
    # Cheat Engine'deki "Pointer scan for this address" ozelliginin
    # basitlestirilmis bir surumu. Amac: bulunan HAM (ASLR'a bagli) bir
    # adres icin, oyun yeniden baslatilsa da GECERLI kalacak statik bir
    # "modul_base + offset (+ offset...)" zinciri onermek.
    #
    # Yontem: bellekte, DEGERI hedef adrese yakin (target - [0, max_offset]
    # araliginda) olan 8-byte'lik "pointer benzeri" konumlari arar. Boyle
    # bir konum modulun statik alani icindeyse (base_address..base+size),
    # dogrudan kullanilabilir kalici bir pointer'dir. Degilse (level 2),
    # o konuma isaret eden BASKA bir statik pointer aranir.
    #
    # NOT: Bu, gercek Cheat Engine pointer scanner'i kadar kapsamli degildir
    # (o, milyonlarca olasiligi saatler suren bir islemle elemektedir).
    # Burada max_level=2 ile sinirli, pratik bir yardimci sunuluyor.

    POINTER_SCAN_MAX_OFFSET_DEFAULT = 0x2000  # struct icinde aranacak azami offset
    POINTER_SCAN_ALIGNMENT = 8  # pointerlar genelde 8-byte hizali (64-bit)

    def _find_pointer_candidates(
        self, target_value: int, max_offset: int, max_results: int = 20000
    ) -> List[Tuple[int, int]]:
        """
        Bellekte, okunan 8-byte deger (pointer sanilan) 'target_value - max_offset'
        ile 'target_value' arasinda olan konumlari bulur.
        Donen: [(pointer_in_adresi, o_adresteki_deger), ...]
        """
        lower = max(target_value - max_offset, 0)
        upper = target_value
        results = []
        alignment = self.POINTER_SCAN_ALIGNMENT
        for base, region_size in self._enumerate_regions():
            for chunk_base, data in self._iter_region_chunks(base, region_size, 7):
                limit = len(data) - 8
                pos = 0
                while pos <= limit:
                    val = struct.unpack_from("<Q", data, pos)[0]
                    if lower <= val <= upper:
                        results.append((chunk_base + pos, val))
                        if len(results) >= max_results:
                            return results
                    pos += alignment
        return results

    def find_pointers_to(
        self, target_address: int, max_level: int = 2,
        max_offset: int = None, max_results: int = 50,
    ) -> List[List[int]]:
        """
        target_address'e ulasan olasi KALICI offset zincirlerini bulmaya
        calisir. Donen deger, her biri resolve_pointer_chain() ile
        dogrudan kullanilabilecek offset listelerinin bir listesidir.

        Ornek donus: [[0x1A2B30, 0x8], [0x1A2B30, 0x10, 0x28], ...]
        Bunlarin her biri profile 'offsets' alanina yazilabilir.
        """
        if self.base_address is None:
            raise ValueError(
                "Bu process icin module base adresi yok, pointer scan yapilamaz."
            )
        if max_offset is None:
            max_offset = self.POINTER_SCAN_MAX_OFFSET_DEFAULT
        module_start = self.base_address
        module_end = self.base_address + (self.module_size or 0x10000000)

        chains: List[List[int]] = []

        level1 = self._find_pointer_candidates(target_address, max_offset, max_results=20000)
        non_static_level1 = []
        for addr, ptr_val in level1:
            offset_from_ptr = target_address - ptr_val
            if module_start <= addr < module_end:
                chains.append([addr - module_start, offset_from_ptr])
                if len(chains) >= max_results:
                    return chains
            else:
                non_static_level1.append((addr, ptr_val))

        if max_level >= 2:
            # Performans icin ikinci seviyede sadece ilk N aday genisletilir
            # (her biri icin ayrica tum bellek tekrar taranir - agir islemdir).
            for mid_addr, mid_ptr_val in non_static_level1[:30]:
                if len(chains) >= max_results:
                    break
                offset1 = target_address - mid_ptr_val
                level2 = self._find_pointer_candidates(mid_addr, max_offset, max_results=5000)
                for addr2, ptr_val2 in level2:
                    if module_start <= addr2 < module_end:
                        offset0 = mid_addr - ptr_val2
                        chains.append([addr2 - module_start, offset0, offset1])
                        if len(chains) >= max_results:
                            break
        return chains

    # ---------------- Byte-level patch / undo ----------------

    def apply_byte_patch(self, address: int, new_bytes: bytes) -> bytes:
        """
        Adrese ham byte yazar, geri alabilmek icin orijinal byte'lari dondurur.
        Cagiran taraf orijinal byte'lari saklamali (undo icin).
        """
        original = self.pm.read_bytes(address, len(new_bytes))
        self.pm.write_bytes(address, new_bytes, len(new_bytes))
        return original

    def restore_byte_patch(self, address: int, original_bytes: bytes):
        self.pm.write_bytes(address, original_bytes, len(original_bytes))

    def nop_fill(self, address: int, length: int) -> bytes:
        """Verilen adresten itibaren length kadar byte'i 0x90 (NOP) ile doldurur,
        orijinalini dondurur (undo icin)."""
        return self.apply_byte_patch(address, b"\x90" * length)


def list_processes():
    """psutil ile calisan TUM process listesini dondurur: [(pid, name), ...]
    (Windows servisleri, arka plan yardimci programlari dahil - kalabalik olur)."""
    import psutil

    procs = []
    for p in psutil.process_iter(["pid", "name"]):
        try:
            procs.append((p.info["pid"], p.info["name"]))
        except Exception:
            continue
    return sorted(procs, key=lambda x: x[1].lower())


def list_processes_with_windows():
    """
    Sadece GORUNUR bir pencereye sahip process'leri dondurur.
    Bu, ADPClientService.exe, AMDRSServ.exe gibi arka plan servislerini
    listeden eler - kullaniciya sadece gercekten acik olan uygulamalar/
    oyunlar gosterilir. Wand/WeMod'daki "acik oyunlar" listesine karsilik
    gelen filtre budur.
    """
    user32 = ctypes.windll.user32
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, ctypes.c_void_p)
    pids = set()

    def _callback(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value:
                pids.add(pid.value)
        return True

    user32.EnumWindows(EnumWindowsProc(_callback), 0)

    import psutil
    result = []
    for pid in pids:
        try:
            p = psutil.Process(pid)
            result.append((pid, p.name()))
        except Exception:
            continue
    return sorted(result, key=lambda x: x[1].lower())
