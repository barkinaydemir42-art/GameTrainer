"""
memory_engine.py
Wand/Cheat Engine mantığında bellek tarama ve okuma/yazma motoru.
SADECE WINDOWS'ta çalışır (ReadProcessMemory / WriteProcessMemory kullanır).

Gereksinim: pip install pymem psutil
"""

import ctypes
import os
import struct
import time
import multiprocessing
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import pymem
import pymem.process

# ---- Tip tanımları ----
# Not: 'byte' bilincli olarak UNSIGNED (0-255) - kullanicilar genelde
# kucuk sayilari (14, 100, 200 gibi) "byte" olarak arar ve 127 uzeri
# degerlerde eskiden struct.error firlatiliyordu.
# ---- Tip tanımları ----
# NOT: SIRALAMA ONEMLI - bu sozlukteki ILK eleman, arayuzdeki tum tip
# secim kutularinda (QComboBox/QInputDialog) VARSAYILAN olarak secili
# gelir. Eskiden 'int16' ilk siradaydi; bu, kullanicilarin (varsayilani
# degistirmeyi unutup) yanlislikla 2-byte okuma yapmasina, oysa oyunlarin
# buyuk cogunlugunun stat/para/mermi degerlerini 4-byte (int32/float)
# sakladigina yol acan gercek bir hataydi - Cheat Engine'in kendi
# varsayilani da "4 Bytes" (int32) oldugu icin artik burada da ayni
# varsayilanla tutarli olacak sekilde int32 ILK SIRAYA alindi.
TYPE_MAP = {
    "int32": ("i", 4),
    "float": ("f", 4),
    "uint32": ("I", 4),
    "int64": ("q", 8),
    "uint64": ("Q", 8),
    "double": ("d", 8),
    "int16": ("h", 2),
    "uint16": ("H", 2),
    "byte": ("B", 1),
}
ALL_TYPES = list(TYPE_MAP.keys())

# Windows sabitleri (VirtualQueryEx için)
MEM_COMMIT = 0x1000
PAGE_READWRITE = 0x04
PAGE_READONLY = 0x02
PAGE_EXECUTE = 0x10
PAGE_EXECUTE_READ = 0x20
PAGE_EXECUTE_READWRITE = 0x40
PAGE_EXECUTE_WRITECOPY = 0x80
PAGE_GUARD = 0x100
SCANNABLE_PROTECT = {PAGE_READWRITE, PAGE_EXECUTE_READWRITE}
# Kod (calistirilabilir) bolgeler icin ayri bir set: Auto Pointer Repair
# 'anchor' aramasi (bkz. find_anchor_for_address), bir statik adrese
# ERISEN RIP-relative MOV/LEA instruction'ini ARIYOR - bu instruction'lar
# genelde SADECE-OKUNUR+CALISTIRILABILIR (.text bolumu, PAGE_EXECUTE_READ)
# sayfalarda bulunur, SCANNABLE_PROTECT'in kapsadigi yazilabilir veri
# bolgelerinde DEGIL. Bu yuzden normal deger/AOB taramasi bu sayfalari
# atlar (yazilamaz oldugu icin "cheat" saklamaya uygun degildir) ama
# anchor aramasi ozellikle bunlari hedefler.
CODE_PROTECT = {PAGE_EXECUTE, PAGE_EXECUTE_READ, PAGE_EXECUTE_READWRITE, PAGE_EXECUTE_WRITECOPY}
# Memory Region Filter icin bolge TIPLERI (MEMORY_BASIC_INFORMATION.Type) -
# yukaridaki protect_set/CODE_PROTECT'ten FARKLI bir eksen: protect_set
# "okunabilir/yazilabilir/calistirilabilir mi" sorusuna, Type ise "bu bolge
# exe/dll'in kendi statik bolumu mu (MEM_IMAGE) yoksa oyunun calisirken
# ayirdigi dinamik heap/yigin mi (MEM_PRIVATE)" sorusuna cevap verir.
MEM_IMAGE = 0x1000000
MEM_MAPPED = 0x40000
MEM_PRIVATE = 0x20000


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
    # ---- Auto Pointer Repair (bkz. find_anchor_for_address/repair_anchor) ----
    # Doldurulmussa, offsets[0]'un (module_base + offsets[0] ile hesaplanan
    # SABIT SAYISAL offset) yerine, bu AOB pattern'i her seferinde yeniden
    # TARAYIP bulunan instruction'in RIP-relative disp32'sinden GUNCEL
    # statik pointer adresi hesaplanir. Oyun guncellenip kodun/verinin
    # modul icindeki KONUMU (RVA) kayarsa bile, bu instruction genelde
    # ayni islevi gormeye devam eder ve dogru (yeni) adresi kendiliginden
    # verir - yani her okuma/yazmada OTOMATIK ONARIM saglanmis olur, ayrica
    # bir 'onar' butonuna basmaya GEREK YOKTUR (bkz. MemoryEngine.
    # resolve_watched_address). offsets[1:] (struct ici alanlar) DEGISMEDEN
    # kullanilmaya devam eder - onlar struct duzenine bagli, kod konumuna
    # degil (struct'in kendisi de degismedigi surece gecerliligini korur).
    anchor_pattern: Optional[str] = None      # ornek: "48 8B 0D ?? ?? ?? ??"
    anchor_disp_pos: Optional[int] = None     # pattern icinde disp32'nin basladigi index (byte)
    anchor_instr_len: Optional[int] = None    # instruction'in TOPLAM uzunlugu (RIP bu kadar sonra baslar)


# ---------------------------------------------------------------------
# AOB / Pattern tarama - MODUL SEVIYESI yardimci fonksiyonlar
# ---------------------------------------------------------------------
# Bilerek MemoryEngine sinifinin DISINDA tanimlandi: hem MemoryEngine.
# pattern_scan (tek-process) hem de _parallel_scan_worker (multiprocessing,
# ayri process'lerde calisir) tarafindan ortak kullanilir. Bir worker
# process, bir MemoryEngine ORNEGINE (ic ice pymem Windows handle'i icerir)
# erisemez/pickle'layamaz - bu yuzden bu fonksiyonlar sadece duz
# bytes/dict/int alip donduren, PICKLENEBILIR VERIYLE calisan saf
# fonksiyonlar olarak yazildi.

def _parse_pattern(pattern: str) -> Tuple[bytes, bytes]:
    """'A1 ?? ?? ?? ?? 8B 45' gibi bir pattern'i (bytes, mask) ciftine cevirir.
    mask: eslesecek byte icin 0xFF, wildcard (??) icin 0x00"""
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


def _match_at(data: bytes, offset: int, pat: bytes, mask: bytes) -> bool:
    if offset + len(pat) > len(data):
        return False
    for i in range(len(pat)):
        if mask[i] and data[offset + i] != pat[i]:
            return False
    return True


def _build_bmh_shift_table(pat: bytes, mask: bytes) -> dict:
    """
    Gercek Boyer-Moore-Horspool 'kotu karakter' kaydirma tablosunu kurar -
    wildcard destekli.

    ONCEKI SURUM pattern'deki TEK bir sabit byte'i 'capa' secip
    bytes.find() ile o capayi ariyor, sonra tam pattern'i dogruluyordu.
    Bu, capa byte'i bellekte sik rastlanan bir deger oldugunda (ornegin
    x86 kodunda cok yaygin bir opcode) cok sayida yanlis aday uretip
    bosuna dogrulama yaptiriyordu - pattern'deki DIGER sabit byte'lar
    kaydirma hesabina hic katilmiyordu.

    Bu fonksiyon, klasik BMH mantigini kurar: pattern icindeki SON pozisyon
    HARIC her SABIT (wildcard olmayan) byte icin, "pencerenin son
    pozisyonunda bu byte'i gorursen, kac ileri atlayabilirsin" degerini
    tabloya yazar.

    ONEMLI DUZELTME (wildcard guvenligi): bir WILDCARD pozisyonu, ICINDE
    HANGI BYTE OLURSA OLSUN eslesir kabul edilir. Bu yuzden, bir sabit
    byte'a gore hesaplanan kaydirma miktari, o sabit byte'in SAGINDA
    (pattern sonuna daha yakin) bir wildcard varsa, o wildcard'in
    dayattigi daha kucuk/daha guvenli sinirla KISITLANMALIDIR - aksi
    halde pattern'in ortasinda/sonunda bir wildcard varken sadece solundaki
    bir sabit byte'a bakip daha BUYUK bir kaydirma yapmak, wildcard'in
    "her seyle eslesebilir" olma ozelligiyle olusabilecek GERCEK bir
    eslesmeyi atlayip kacirabilir (ilk surumde tam olarak bu hataya
    rastlanip fuzz testiyle yakalandi - bkz. gecmis). Ayni mantikla,
    tabloda hic karsiligi olmayan (pattern'de sabit byte olarak hic
    gecmeyen) bir deger icin varsayilan kaydirma da, en sagdaki wildcard'in
    izin verdigi miktarla sinirlidir (wildcard yoksa tam pattern uzunlugu
    guvenlidir).

    Donen sozluk her BYTE DEGERI (0-255) icin guvenli kaydirma miktarini
    tutar; ozel `None` anahtari, tabloda karsiligi olmayan degerler icin
    kullanilacak VARSAYILAN kaydirma miktarini tasir (data pozisyonlarindaki
    gercek byte degerleri 0-255 oldugu icin None ile hicbir zaman
    cakismaz).
    """
    n = len(pat)
    wildcard_positions = [i for i in range(n - 1) if not mask[i]]
    wildcard_bound = (n - 1 - max(wildcard_positions)) if wildcard_positions else n

    table = {}
    for i in range(n - 1):
        if mask[i]:
            # Ayni byte birden fazla sabit pozisyonda geçiyorsa, soldan
            # saga ilerleyip uzerine yazarak EN SAGDAKI (en kucuk kaydirma
            # miktarina sahip) oluşumun kazanmasi saglanir.
            table[pat[i]] = n - 1 - i

    for c in list(table.keys()):
        if wildcard_bound < table[c]:
            table[c] = wildcard_bound
    table[None] = wildcard_bound
    return table


def _bmh_find_all(
    data: bytes, pat: bytes, mask: bytes, shift_table: dict,
    max_results: int, found: list, base_addr: int,
) -> bool:
    """Tek bir bellek parcasi (chunk) icinde BMH ile TUM eslesmeleri bulur,
    (base_addr + pozisyon) olarak found listesine ekler. max_results'a
    ulasilirsa True dondurur (cagiran taraf taramayi tamamen durdurmali)."""
    n = len(pat)
    limit = len(data) - n
    default_shift = shift_table[None]
    pos = 0
    while pos <= limit:
        if _match_at(data, pos, pat, mask):
            found.append(base_addr + pos)
            if len(found) >= max_results:
                return True
            pos += 1  # ust uste binen (overlapping) eslesmeleri de yakala
            continue
        key_byte = data[pos + n - 1]
        pos += shift_table.get(key_byte, default_shift)
    return False


# ---------------------------------------------------------------------
# Coklu-process (multiprocessing) AOB tarama - yardimcilar
# ---------------------------------------------------------------------
# GIL yuzunden CPU-bound byte karsilastirmasini THREAD'lerle paralellestir-
# menin faydasi yoktur (ayni anda sadece 1 Python bytecode calisir) -
# gercek paralellik icin AYRI PROCESS gerekir. Her worker process kendi
# OpenProcess/ReadProcessMemory cagrilarini yapar (pymem'in Pymem nesnesi
# process'ler arasi tasınamaz/pickle'lanamaz).

_PROCESS_QUERY_INFORMATION = 0x0400
_PROCESS_VM_READ = 0x0010


def _open_process_for_read(pid: int) -> int:
    handle = ctypes.windll.kernel32.OpenProcess(
        _PROCESS_QUERY_INFORMATION | _PROCESS_VM_READ, False, pid
    )
    if not handle:
        raise OSError(f"OpenProcess basarisiz (pid={pid})")
    return handle


def _read_process_memory_raw(handle: int, address: int, size: int) -> bytes:
    buffer = ctypes.create_string_buffer(size)
    bytes_read = ctypes.c_size_t(0)
    ok = ctypes.windll.kernel32.ReadProcessMemory(
        handle, ctypes.c_void_p(address), buffer, size, ctypes.byref(bytes_read)
    )
    if not ok:
        raise OSError(f"ReadProcessMemory basarisiz (adres={hex(address)})")
    return buffer.raw[:bytes_read.value]


def _split_regions_balanced(
    regions: List[Tuple[int, int]], num_workers: int
) -> List[List[Tuple[int, int]]]:
    """Bolgeleri num_workers gruba TOPLAM BOYUTA GORE dengeli dagitir
    (greedy bin-packing: her bolge, o ana kadar en az yuklenmis kovaya
    eklenir). Boylece bir worker'a tesadufen dev bolgelerin (ornegin bazi
    Unreal Engine oyunlarinin GB'larca commit alani) cogu duserken
    digerleri erken bitirip bos oturmaz."""
    buckets: List[List[Tuple[int, int]]] = [[] for _ in range(num_workers)]
    bucket_totals = [0] * num_workers
    for base, size in sorted(regions, key=lambda r: r[1], reverse=True):
        idx = bucket_totals.index(min(bucket_totals))
        buckets[idx].append((base, size))
        bucket_totals[idx] += size
    return [b for b in buckets if b]  # bolge sayisi < worker sayisiysa bos kovalari at


def _parallel_scan_worker(args) -> List[int]:
    """
    AYRI BIR PROCESS'TE calisir (multiprocessing.Pool tarafindan
    baslatilir) - bu yuzden 'self' YOK, sadece picklenebilir argumanlar
    (pid, bolge listesi, pattern/mask, vb.) kullanilabilir.

    Kendi process handle'ini acar, kendisine atanan bellek bolgelerini
    okuyup BMH ile tarar, bulunan adresleri dondurur. Bir bolge/parca
    okunamazsa (nadiren olur) sadece o parcayi atlar, TUM taramayi iptal
    etmez - MemoryEngine._iter_region_chunks'taki ayni davranisla tutarli.
    """
    pid, regions, pat, mask, max_results, chunk_size = args
    try:
        handle = _open_process_for_read(pid)
    except OSError:
        return []

    shift_table = _build_bmh_shift_table(pat, mask)
    overlap = len(pat) - 1
    found: List[int] = []
    try:
        for base, region_size in regions:
            offset = 0
            while offset < region_size:
                this_size = min(chunk_size, region_size - offset)
                try:
                    data = _read_process_memory_raw(handle, base + offset, this_size)
                except OSError:
                    offset += this_size
                    continue
                if _bmh_find_all(data, pat, mask, shift_table, max_results, found, base + offset):
                    return found
                step = this_size - overlap if this_size > overlap else this_size
                offset += step
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)
    return found


class MemoryEngine:
    def __init__(self):
        self.pm: Optional[pymem.Pymem] = None
        self.process_name: Optional[str] = None
        self.base_address: Optional[int] = None
        self.base_address_error: Optional[str] = None
        self.module_size: int = 0
        self.exe_fingerprint: Optional[str] = None
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
        self.exe_fingerprint: Optional[str] = None
        try:
            mod = pymem.process.module_from_name(self.pm.process_handle, process_name)
            self.base_address = mod.lpBaseOfDll
            self.module_size = getattr(mod, "SizeOfImage", 0)
        except Exception as e:
            # Bagli olsak bile modul/base adres bulunamayabilir (ornek: 32-bit/
            # 64-bit uyumsuzlugu, izin sorunu). Bu durumda manuel/AOB tarama ve
            # ham adres ekleme calisir ama pointer zinciri (offsets) calismaz.
            self.base_address_error = str(e)
        self.exe_fingerprint = self.get_exe_fingerprint()
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
        self.exe_fingerprint = None
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

    def resolve_watched_address(self, wa: "WatchedAddress") -> int:
        """
        resolve_pointer_chain'in Auto Pointer Repair FARKINDA versiyonu.

        - wa.anchor_pattern DOLUYSA: offsets[0]'un sabit sayisal
          module_base+offset hesabi yerine, repair_anchor() ile GUNCEL
          statik pointer adresi bulunur (AOB tekrar taranir, RIP-relative
          disp32 tekrar okunur). Bu, HER cagride yapilir - yani oyun
          guncellenip kodun modul icindeki konumu kaysa bile, bu adres
          KENDILIGINDEN dogru kalir (ayri bir 'onar' adimi gerekmez).
        - Kalan offsets[1:] (struct ici alanlar) AYNI KALIR - onlar
          struct'in duzenine bagli, kodun konumuna degil.
        - anchor_pattern yoksa (eski/normal pointer zinciri), davranis
          resolve_pointer_chain ile birebir aynidir (module_base+offsets[0]).
        """
        if not wa.offsets:
            raise ValueError("offsets bos olamaz")
        if wa.anchor_pattern:
            addr = self.repair_anchor(
                wa.anchor_pattern, wa.anchor_disp_pos, wa.anchor_instr_len
            )
            if addr is None:
                raise ValueError(
                    f"Anchor pattern bulunamadi ('{wa.name}') - oyun guncellenip "
                    "bu instruction tamamen kaldirilmis/degistirilmis olabilir. "
                    "Anchor'i yeniden bulmayi dene."
                )
        else:
            if self.base_address is None:
                raise ValueError(
                    "Bu process icin module base adresi bulunamadi "
                    f"({getattr(self, 'base_address_error', 'bilinmeyen sebep')}). "
                    "Pointer zinciri kullanamazsin, ham/manuel adres veya AOB kullan."
                )
            addr = self.base_address + wa.offsets[0]
        for off in wa.offsets[1:]:
            addr = self.pm.read_longlong(addr) + off
        return addr

    def verify_pattern_at(self, address: int, pattern: str) -> bool:
        """Verilen adreste, verilen AOB pattern'i hala eslesiyor mu kontrol
        eder. Signature Cache dogrulamasi icin kullanilir: tek bir kucuk
        okuma yapar (ucuzdur), tam bir tarama gerektirmez."""
        try:
            pat, mask = _parse_pattern(pattern)
            if not pat:
                return False
            data = self.pm.read_bytes(address, len(pat))
        except Exception:
            return False
        return _match_at(data, 0, pat, mask)

    # ---------------- Oyun Surumu Parmak Izi (Version Checker) ----------------
    def get_exe_fingerprint(self) -> Optional[str]:
        """Bagli oldugu process'in ana exe'sinin diskteki boyutu+degisim
        zamanina dayali ucuz bir 'parmak izi' uretir. Bu, oyun bir surum
        guncellemesi aldiginda (patch/DLC/Steam guncellemesi) degisir - tam
        exe'yi (genelde onlarca-yuzlerce MB) hash'lemek yavas olacagi icin
        bilincli olarak boyut+mtime kombinasyonu tercih edildi; bu ikisi
        birlikte pratikte bir hash kadar guvenilir bir 'degisti/degismedi'
        sinyali verir. Kaydedilmis bir profil/cache yuklenirken bu deger
        farkliysa, kullaniciya 'oyun guncellenmis olabilir, adresler artik
        gecersiz olabilir' diye uyarmak icin kullanilir.

        NOT: Bu proje ayrica Auto Pointer Repair (anchor_pattern, bkz.
        asagisi) ile RIP-relative statik pointer'lari OTOMATIK onarabiliyor;
        bu fingerprint ise DAHA GENIS bir uyari katmanidir - anchor'i
        olmayan profiller (ham adres/normal offset zinciri) icin de
        calisir ve struct'in kendisi degisse bile (anchor onaramasa da)
        kullaniciyi bilgilendirir."""
        if self.pm is None or not self.process_name:
            return None
        try:
            module = pymem.process.module_from_name(self.pm.process_handle, self.process_name)
            exe_path = module.filename
            if not exe_path or not os.path.isfile(exe_path):
                return None
            stat = os.stat(exe_path)
            return f"{stat.st_size}:{int(stat.st_mtime)}"
        except Exception:
            return None

    # ---------------- Auto Pointer Repair (RIP-relative "anchor") ----------------
    # AMAC: bir pointer zincirinin ILK adimi (module_base + offsets[0]) genelde
    # tek bir yerde, koddaki bir "MOV reg, [rip+disp32]" veya "LEA reg,
    # [rip+disp32]" (x64 RIP-relative adresleme) instruction'indan turer.
    # Oyun guncellenince bu instruction'in MODUL ICINDEKI KONUMU (RVA)
    # kayabilir (derleyici kodu yeniden duzenler), bu yuzden sabit sayisal
    # "offsets[0]" degeri artik YANLIS statik adrese isaret eder.
    #
    # COZUM: instruction'in KENDISINI (disp32 wildcard'lanmis halde) bir AOB
    # imzasi olarak saklariz. Oyun guncellenip instruction baska bir yere
    # tasinsa bile, KODUN KENDISI (compiler ayni islevi ureten benzer byte
    # dizisini tekrar uretecegi icin) genelde AYNI kalir - AOB tekrar
    # bulunur, o anki (GUNCEL, doğru) disp32'si okunur, hedef yeniden
    # hesaplanir. Boylece "offsets[0]" kalici sayi yerine KENDI KENDINI
    # GUNCELLEYEN bir referansa donusur.
    #
    # SINIR: bu, sadece STATIK POINTER'IN KONUMUNU (offsets[0]) onarir.
    # Struct'in kendisi (offsets[1:] alanlarinin gecerliligi) yeniden
    # duzenlenirse (alan eklenip/cikarilirsa) bu otomatik olarak
    # DUZELTILEMEZ - kullanicinin struct offsetlerini yeniden bulmasi
    # gerekir. Pratikte oyun guncellemelerinin buyuk kismi bu senaryo
    # DEGILDIR (struct nadiren degisir, kod/RVA'lar sik degisir).

    # x64'te ilgilenilen RIP-relative MOV/LEA opcode'lari:
    # REX.W(0x48/0x4C/0x49/0x4D) + [8B=MOV r64,r/m64 | 8D=LEA r64,m] +
    # ModRM(mod=00,rm=101 -> RIP-relative) + disp32(4 byte) = 7 byte toplam.
    _ANCHOR_OPCODES = (0x8B, 0x8D)
    _ANCHOR_INSTR_LEN = 7  # REX(1) + opcode(1) + ModRM(1) + disp32(4)

    def find_anchor_for_address(
        self, target_address: int, max_results: int = 5
    ) -> List[dict]:
        """
        target_address'e RIP-relative olarak erisen MOV/LEA instruction'
        larini kod (.text) bolgelerinde arar. Bulunan her aday icin
        wildcard'li AOB pattern'i + disp32 pozisyonu + instruction uzunlugunu
        dondurur - bunlar dogrudan WatchedAddress.anchor_* alanlarina
        yazilabilir.

        Donen: [{"pattern": "48 8B 0D ?? ?? ?? ??", "disp_pos": 3,
                 "instr_len": 7, "instr_addr": 0x7ff6...}, ...]

        Birden fazla sonuc donebilir (ayni statik adrese birden fazla yerden
        erisilebilir) - cagiran taraf (main.py) genelde ilkini kullanir ya
        da kullaniciya secim sunar (pointer scan akisiyla tutarli UX icin).
        """
        results = []
        overlap = self._ANCHOR_INSTR_LEN - 1
        for base, region_size in self._enumerate_code_regions():
            for chunk_base, data in self._iter_region_chunks(base, region_size, overlap):
                limit = len(data) - self._ANCHOR_INSTR_LEN
                pos = 0
                while pos <= limit:
                    rex = data[pos]
                    if not (0x48 <= rex <= 0x4D):
                        pos += 1
                        continue
                    opcode = data[pos + 1]
                    if opcode not in self._ANCHOR_OPCODES:
                        pos += 1
                        continue
                    modrm = data[pos + 2]
                    if (modrm & 0xC7) != 0x05:  # mod=00, rm=101 (RIP-relative)
                        pos += 1
                        continue
                    disp32 = struct.unpack_from("<i", data, pos + 3)[0]
                    instr_addr = chunk_base + pos
                    next_instr_addr = instr_addr + self._ANCHOR_INSTR_LEN
                    if next_instr_addr + disp32 == target_address:
                        instr_bytes = data[pos:pos + self._ANCHOR_INSTR_LEN]
                        pattern = " ".join(
                            f"{b:02X}" if i < 3 else "??"
                            for i, b in enumerate(instr_bytes)
                        )
                        results.append({
                            "pattern": pattern,
                            "disp_pos": 3,
                            "instr_len": self._ANCHOR_INSTR_LEN,
                            "instr_addr": instr_addr,
                        })
                        if len(results) >= max_results:
                            return results
                    pos += 1
        return results

    def repair_anchor(
        self, anchor_pattern: str, anchor_disp_pos: int, anchor_instr_len: int
    ) -> Optional[int]:
        """
        Kayitli AOB anchor'ini tekrar tarar (find_anchor_for_address ile
        bulunmus, disp32'si wildcard'lanmis instruction), instruction'i
        (muhtemelen kaymis yeni konumunda) yeniden bulur, o anki disp32'yi
        okuyup GUNCEL hedef (statik pointer) adresini hesaplar.

        Instruction hic bulunamazsa (kod tamamen kaldirilmis/degistirilmis)
        None doner - cagiran taraf (resolve_watched_address) bunu acikca
        bir hataya cevirir.
        """
        matches = self.pattern_scan(anchor_pattern, max_results=5)
        if not matches:
            return None
        instr_addr = matches[0]
        try:
            disp_bytes = self.pm.read_bytes(instr_addr + anchor_disp_pos, 4)
            disp32 = struct.unpack("<i", disp_bytes)[0]
        except Exception:
            return None
        next_instr_addr = instr_addr + anchor_instr_len
        return next_instr_addr + disp32

    # ---------------- Bellek bölgelerini tarama (Cheat Engine tarzı) ----------------

    def _enumerate_regions(self, protect_set=None, region_filter: Optional[str] = None):
        """Process'in bellek bolgelerini dondurur (start, size).
        protect_set verilmezse varsayilan olarak YAZILABILIR/OKUNABILIR
        bolgeler (SCANNABLE_PROTECT) dondurulur - deger/AOB taramasi bunu
        kullanir. Kod (.text) bolgelerini taramak icin (bkz.
        find_anchor_for_address) protect_set=CODE_PROTECT verilir.

        region_filter (Memory Region Filter, protect_set'ten BAGIMSIZ bir
        ikinci eksen):
          None       -> bolge tipine bakma (eski davranis, varsayilan)
          "image"    -> sadece exe/dll'in kendi bolumleri (MEM_IMAGE)
          "private"  -> sadece heap/yigin gibi dinamik bolgeler (MEM_PRIVATE)
        Taramayi tek bir bolge tipine daraltmak hem hizlandirir hem de
        (ozellikle "private" ile) kod bolumlerindeki alakasiz eslesmeleri eler.
        """
        if protect_set is None:
            protect_set = SCANNABLE_PROTECT
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
            step = mbi.RegionSize if mbi.RegionSize else 0x1000
            is_scannable = (
                mbi.State == MEM_COMMIT
                and mbi.Protect in protect_set
                and not (mbi.Protect & PAGE_GUARD)
                and mbi.RegionSize > 0
            )
            type_ok = (
                region_filter is None
                or (region_filter == "image" and mbi.Type == MEM_IMAGE)
                or (region_filter == "private" and mbi.Type == MEM_PRIVATE)
            )
            if is_scannable and type_ok:
                regions.append((mbi.BaseAddress or 0, mbi.RegionSize))
            address += step
        return regions

    def _enumerate_code_regions(self):
        """Calistirilabilir (.text benzeri) bolgeleri dondurur - Auto
        Pointer Repair'in anchor (RIP-relative instruction) aramasi
        icin. Bkz. _enumerate_regions docstring'i."""
        return self._enumerate_regions(protect_set=CODE_PROTECT)

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

    def first_scan(self, value, value_type: str, region_filter: Optional[str] = None) -> List[ScanResult]:
        """İlk tarama: verilen değere eşit tüm adresleri bulur."""
        fmt, size = TYPE_MAP[value_type]
        target = struct.pack("<" + fmt, value)
        overlap = size - 1
        results = []
        self.last_scan_truncated = False
        for base, region_size in self._enumerate_regions(region_filter=region_filter):
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
    # Yardimci fonksiyonlar (_parse_pattern, _match_at, _build_bmh_shift_table,
    # _bmh_find_all) BILEREK bu sinifin DISINDA, MODUL SEVIYESINDE tanimlandi
    # (asagida) - hem pattern_scan (tek-process) hem de pattern_scan_parallel
    # (coklu-process, bkz. asagisi) tarafindan ortak kullanilabilmesi icin.
    # multiprocessing worker'lari AYRI BIR PYTHON PROCESS'INDE calisir ve
    # orada bir MemoryEngine ORNEGINE (dolayisiyla self.pm'nin Windows handle'ina)
    # erisemez - handle'lar process'e ozeldir, pickle'lanip tasınamaz.

    def pattern_scan(self, pattern: str, max_results: int = 200, region_filter: Optional[str] = None) -> List[int]:
        """
        AOB/pattern tarama. Ornek pattern: 'A1 ?? ?? ?? ?? 8B 45 FC'
        Tum yazilabilir/okunabilir bolgeleri tarar, eslesen adresleri dondurur.

        Bu, TEK process icinde calisan versiyondur (esas cagiran taraf zaten
        bunu ScanWorker/QThread'de calistiriyor - arayuz donmuyor). CPU-bound
        bu isi THREAD'lerle daha da paralellestirmenin CPython'da GIL yuzunden
        pratik faydasi yoktur; gercek paralellik icin pattern_scan_parallel()
        (multiprocessing, AYRI PROCESS'ler) kullanilmali - bkz. asagisi.

        Performans notu: Gercek Boyer-Moore-Horspool 'kotu karakter' kaydirma
        tablosu kullanir (bkz. _build_bmh_shift_table). ONCEKI SURUM sadece
        pattern'deki TEK bir sabit byte'i 'capa' secip bytes.find() ile
        ariyor, sonra tam pattern'i dogruluyordu - capa byte'i bellekte sik
        rastlanan bir deger oldugunda (ornegin x86 kodunda cok yaygin bir
        opcode) cok sayida yanlis aday uretip bosuna dogrulama yapiyordu.
        Bu surum pattern'deki TUM sabit byte'lari kaydirma hesabina katar,
        bu yuzden capa olarak "nadir" bir byte olmasa bile (uzun/yogun
        pattern'lerde) belirgin sekilde daha az aday dogrular.
        """
        pat, mask = _parse_pattern(pattern)
        if not pat or not any(mask):
            return []  # Bos pattern veya tamamen wildcard - anlamli degil

        shift_table = _build_bmh_shift_table(pat, mask)
        overlap = len(pat) - 1
        found: List[int] = []
        for base, region_size in self._enumerate_regions(region_filter=region_filter):
            for chunk_base, data in self._iter_region_chunks(base, region_size, overlap):
                if _bmh_find_all(data, pat, mask, shift_table, max_results, found, chunk_base):
                    return found
        return found

    def pattern_scan_parallel(
        self, pattern: str, max_results: int = 200, max_workers: Optional[int] = None,
        region_filter: Optional[str] = None,
    ) -> List[int]:
        """
        pattern_scan ile AYNI SONUCU (ayni pattern, ayni BMH algoritmasi)
        uretir, ama byte karsilastirma isini birden fazla PROCESS'e boler
        (THREAD DEGIL).

        NEDEN THREAD DEGIL: Bu is CPU-bound (saf Python dongusunde byte
        karsilastirma). CPython'da GIL (Global Interpreter Lock) ayni anda
        SADECE TEK bir thread'in Python bytecode calistirmasina izin verir -
        yani threading.Thread ile bolmenin CPU-bound bir iste pratik faydasi
        YOKTUR (I/O-bound islerde -ornegin ag indirmesi, bkz. main.py'deki
        CoverFetchWorker- fayda saglar, cunku bekleme sirasinda GIL serbest
        birakilir). Gercek paralellik icin ayri process'ler (her biri kendi
        Python yorumlayicisi + kendi GIL'i ile) gerekir - burada
        'multiprocessing' kullanilmasinin sebebi budur.

        Her worker process, pymem'in Pymem nesnesini/handle'ini KULLANAMAZ
        (Windows process handle'lari baska bir process'e tasınamaz/pickle'
        lanamaz) - bunun yerine kendi OpenProcess/ReadProcessMemory
        cagrilarini yapar (bkz. modul seviyesindeki _parallel_scan_worker).

        Buyuk (GB'larca commit alani olan, ornegin bazi Unreal Engine
        oyunlari) bellek tarayan agir AOB taramalarinda, cok cekirdekli
        CPU'larda anlamli bir hizlanma saglar. Kucuk/hizli taramalarda
        process baslatma maliyeti (platforma gore onlarca-yuzlerce ms)
        faydayi gotürebilir - bu yuzden varsayilan DEGIL, kullanicinin
        acikca sectigi bir secenektir (bkz. main.py'deki 'Cok Cekirdekli
        Tara' onay kutusu).

        Herhangi bir sebeple basarisiz olursa (multiprocessing baslatilamadi,
        yetersiz izin, vb.) sessizce tek-process pattern_scan()'e duser -
        kullaniciya "coklu-process ozelligi bozuk" diye bosuna hata vermez,
        taramayi yine de (biraz daha yavas) tamamlar.
        """
        pat, mask = _parse_pattern(pattern)
        if not pat or not any(mask):
            return []

        try:
            pid = self.pm.process_id
            regions = self._enumerate_regions(region_filter=region_filter)
            if not regions:
                return []

            cpu_count = os.cpu_count() or 1
            workers = max_workers or max(1, min(cpu_count, 8, len(regions)))
            if workers <= 1:
                return self.pattern_scan(pattern, max_results=max_results, region_filter=region_filter)

            region_groups = _split_regions_balanced(regions, workers)
            args_list = [
                (pid, group, pat, mask, max_results, self.CHUNK_SIZE)
                for group in region_groups
            ]

            # Windows'ta zaten varsayilan olan 'spawn' baslatma yontemi
            # ACIKCA istenir - PyInstaller ile derlenmis (.exe) halde
            # calisirken 'fork' mevcut degildir ve platformlar arasi
            # tutarlilik icin en guvenli secimdir.
            ctx = multiprocessing.get_context("spawn")
            with ctx.Pool(processes=len(args_list)) as pool:
                worker_results = pool.map(_parallel_scan_worker, args_list)

            found: List[int] = []
            for r in worker_results:
                found.extend(r)
            found.sort()
            return found[:max_results]
        except Exception:
            return self.pattern_scan(pattern, max_results=max_results, region_filter=region_filter)

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
            # NOT: Bu deger dusuruldu (30 -> 12). Her aday, ASAGIDA
            # tum bellegi TEKRAR tarayan agir bir _find_pointer_candidates
            # cagrisi tetikler - 30 aday, gercek oyunlarda dakikalarca
            # surebiliyordu. Artik bu tarama arka plan thread'inde
            # calistigi icin arayuz artik kilitlenmiyor, ama yine de
            # makul bir sinirla tutuyoruz.
            for mid_addr, mid_ptr_val in non_static_level1[:12]:
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
