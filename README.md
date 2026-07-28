# LocalTrainer Studio — Merged Edition

## Değişiklik Günlüğü (Genel Denetim Sonrası)

Kod tabanı baştan sona tarandı, gerçek PyQt5 + sahte (mock) bellek ortamıyla
test edildi. Bulunan hatalar ve eklenen özellikler:

### Düzeltilen hatalar
- **[KRİTİK] Pointer/offset zinciri çözümleme hatası**: Zincirdeki son
  adımda bir dereference eksikti — kaydedilen her kalıcı profil yanlış
  adrese gidiyordu. Artık `N` offset için doğru şekilde `N-1` dereference
  yapılıyor (testle doğrulandı).
- **`byte` tipi signed'dı**: 128-255 arası bir değer yazmaya çalışınca
  çöküyordu. Artık unsigned (0-255). Ayrıca `int16/uint16/uint32/uint64`
  tipleri eklendi.
- **`base_address` bulunamazsa çökme**: Attach sonrası durum etiketi
  `None` değeri formatlamaya çalışıp hata veriyordu. Artık güvenli mesaj
  gösteriliyor, pointer zinciri dışındaki özellikler (manuel/AOB adres)
  yine çalışıyor.
- **[ÖNEMLİ] Freeze Manager tablosu her 500ms'de tamamen yeniden
  çiziliyordu**: Bu, kullanıcının seçtiği satırı sürekli sıfırlıyor,
  "Seç: Değer Yaz / Hotkey Ata / Sil" butonlarını pratikte kullanılamaz
  hale getiriyordu. Artık arka plan döngüsü sadece değer sütununu
  günceller, seçim korunur.
- **Detach (bağlantıyı kes) özelliği hiç yoktu** — eklendi.
- **Farklı bir oyuna bağlanınca eski watch list/hotkey/patch temizlenmiyordu**
  — yanlış process'in belleğine yazma riski vardı. Artık her yeni Attach'te
  otomatik temizleniyor.
- **Process handle sızıntısı**: Detach/yeniden attach handle'ı kapatmıyordu.
  Artık `close_process()` çağrılıyor.
- **Hotkey yeniden atama sızıntısı**: Bir cheat'e yeni hotkey atanınca eski
  hotkey kayıttan silinmiyordu (hayalet tuş bağı kalıyordu). Düzeltildi.
- **AOB tarama çok yavaştı**: Her byte pozisyonu Python döngüsünde tek tek
  kontrol ediliyordu. Artık ilk sabit byte'ı "çapa" alıp `bytes.find` ile
  atlıyor (C hızında) — büyük oyunlarda ciddi hızlanma.
- **Profil kaydetme ham adresleri kaydetmiyordu**: Scanner'dan bulunan
  (offset zinciri olmayan) cheat'ler profile kaydedilip yüklenince sessizce
  işe yaramaz hale geliyordu. Artık ham adres de saklanıyor (aynı oyun
  oturumu içinde geçerli, oyun kapanınca geçersiz olacağı loglanıyor).
- **Büyük bellek bölgesinin bir kısmı okunamazsa TÜM bölge atlanıyordu**:
  Artık bölgeler 4MB'lık parçalar halinde okunuyor, tek bir parçadaki hata
  sadece o parçayı etkiliyor.

### Yeni özellikler
- **Bilinmeyen İlk Değer taraması** (klasik Cheat Engine özelliği): Aranan
  sayıyı bilmiyorsan, önce tüm belleğin anlık görüntüsünü al, oyunda değeri
  değiştir, sonra `changed/unchanged/increased/decreased` ile filtrele.
- **"Tümünü Çöz" / "Tümünü Sil"** butonları (Freeze Manager).
- **Hızlı NOP Doldur** butonu (Patch sekmesi) — tek tıkla N byte'ı 0x90 ile doldurur.
- **Manuel profil yükleyici**: Sadece process adına göre otomatik yükleme
  değil, kayıtlı tüm profilleri listeleyip istediğini elle de yükleyebilirsin.
- **Process kapanma algılama**: Oyun kapatıldığında uygulama bunu algılayıp
  otomatik olarak bağlantıyı kesiyor ve logluyor (sessizce boşa yazmaya
  devam etmek yerine).
- **"Tüm process'leri göster" seçeneği** korunuyor, varsayılan hâlâ sadece
  görünür pencereli uygulamalar.

### Test edildi
Bu ortamda Windows/pymem gerçek olarak çalıştırılamadığı için, sahte
(mock) bir process/bellek ortamı kurup hem çekirdek motoru (`test_engine.py`
mantığı) hem de gerçek PyQt5 ile tüm arayüzü (`test_gui.py` mantığı) uçtan
uca test ettim: attach, scan, freeze, patch/undo, script engine, detach —
hepsi hatasız çalıştı. Yine de gerçek Windows + gerçek oyun testinin yerini
tutmaz; ilk kullanımda beklenmedik bir şeyle karşılaşırsan mesajı paylaş.

---

## Otomatik Güncelleme Kurulumu

Uygulamada artık bir **Güncelleme** sekmesi var: sürüm kontrolü yapar,
yeni sürümü indirir, SHA256 ile doğrular ve (derlenmiş `.exe` halindeyken)
kendini değiştirip yeniden başlatır. Bunun çalışması için **bir "manifest"
JSON dosyasını sen barındırmalısın** — ben senin için sunucu çalıştıramam,
ama en kolay ve ücretsiz yol GitHub:

### 1) Manifest dosyasını hazırla ve barındır
`update_manifest_example.json` dosyasını örnek al:
```json
{
  "version": "1.1.0",
  "changelog": "Bu surumde neler degisti...",
  "download_url": "https://github.com/kullanici/repo/releases/download/v1.1.0/LocalTrainerStudio.exe",
  "sha256": "opsiyonel-dosya-hash-i"
}
```
- Bunu bir GitHub reposuna `update_manifest.json` olarak koy (repo public
  olabilir, içinde hassas bilgi yok).
- Raw linkini al: `https://raw.githubusercontent.com/kullanici/repo/main/update_manifest.json`
- Yeni `.exe`'yi GitHub **Releases** kısmına yükle, `download_url`'i o linkle güncelle.
- (Önerilir) `sha256` alanını doldur — böylece indirilen dosya bozuk/değişmiş
  ise uygulama güncellemeyi **uygulamaz**, sadece hata verir. Windows'ta hash
  almak için: `certutil -hashfile LocalTrainerStudio.exe SHA256`

### 2) Yeni sürüm çıkardığında
1. `updater.py` içindeki `CURRENT_VERSION` değerini artır (örn. `"1.2.0"`).
2. `build.bat` ile yeni `.exe`'yi derle.
3. GitHub Release'e yükle, manifest'teki `version`, `download_url`,
   `sha256` alanlarını güncelle.
4. Kullanıcıların uygulaması açıkken (veya "Kontrol Et"e basınca) yeni
   sürümü otomatik görecek.

### 3) Uygulama tarafında
- **Güncelleme** sekmesine git, manifest URL'ini gir, **Kaydet**.
- **Baslangicta otomatik kontrol et** işaretliyse, her açılışta sessizce
  kontrol eder ve yeni sürüm varsa bildirir.
- **Simdi Guncelle** dediğinde: indirir → (varsa) SHA256 doğrular →
  onay ister → uygulamayı kapatıp yeni `.exe` ile yeniden başlatır.

### Önemli sınırlama
Kendi kendini değiştirme **sadece derlenmiş `.exe` halinde** çalışır
(`build.bat` ile üretilen). Kaynak koddan (`python main.py`) çalışırken
güncelleme kontrolü ve indirme yine çalışır, ama dosya değişimi otomatik
yapılmaz — sana indirilen dosyanın yolu gösterilir, elle güncellersin.
Bu bilinçli bir güvenlik tercihi: bir Python betiğinin kendi kaynak
dosyalarını otomatik üzerine yazması çok daha riskli bir işlemdir.

---

## Sonraki Geliştirme Önerileri

Öncelik sırasına göre, üzerine eklenebilecek anlamlı özellikler:

1. **Çoklu oyun profili yönetimi** — şu an tek `MemoryEngine` örneği var;
   birden fazla oyunu aynı anda izlemek istersen (nadir ama mümkün) her
   sekme için ayrı bir engine örneği gerekir.
2. **Pointer scan yardımcısı** — Cheat Engine'deki "bu adrese ne erişiyor"
   / "pointer zinciri bul" özelliğinin basit bir sürümü: bir adresi işaret
   eden diğer adresleri geriye doğru tarayıp olası offset zincirlerini
   otomatik önerme. Şu an bu iş tamamen Cheat Engine'e bırakılmış durumda.
3. ~~**AOB tarama performansı**~~ — **YAPILDI**: `memory_engine.py` artık
   gercek Boyer-Moore-Horspool 'kotu karakter' kaydirma tablosu kullaniyor
   (pattern'deki TUM sabit byte'lari kaydirma hesabina katiyor, tek bir
   capa byte'ina degil). Ayrica `pattern_scan_parallel()` ile
   **multiprocessing** tabanli cok-cekirdekli tarama eklendi (bilerek
   THREADING DEGIL - bu CPU-bound bir is oldugu icin CPython'daki GIL
   yuzunden thread'lerle paralellestirmenin faydasi olmazdi; her worker
   kendi process'inde, kendi OpenProcess/ReadProcessMemory handle'iyla
   calisir). Arayuzde 'Auto Signature (AOB) Builder' altinda "Cok
   cekirdekli tara (deneysel)" onay kutusu ile acilir; kapaliyken
   varsayilan tek-process BMH taramasi calisir.
4. **Freeze Manager'da doğrudan tabloda deger düzenleme** — şu an değer
   değiştirmek için ayrı bir dialog açılıyor; tabloya çift tıklayıp
   hücrede düzenleme daha akıcı olur.
5. **Import/Export (dışa aktar) profil**: mevcut profilleri tek bir
   `.json` veya `.zip` olarak dışa/içe aktarma, başka bir bilgisayara
   taşımak için.
6. **Bildirim/log dosyasına yazma**: şu an loglar sadece uygulama içi
   panelde; bir `logs/` klasörüne de yazılsa, hata ayıklaması kolaylaşır.
7. **Otomatik sürüm numarası bulma**: `build.bat`'a `CURRENT_VERSION`'ı
   git tag'inden otomatik okuyacak küçük bir script eklenebilir, böylece
   sürüm numarasını elle senkronize etmek gerekmez.

İstersen bunlardan hangisine öncelik vermek istediğini söyle, onu
uygulayayım.

---

## Proje Kökeni

Bu proje iki parçayı birleştiriyor:
- **Arayüz tasarımı**: senin yüklediğin `LocalTrainerStudio_Auto` projesindeki
  PyQt5 koyu tema, Wizard/Scanner/Freeze/Patch/Script sekme yapısı (bu
  gerçekten daha profesyonel görünüyordu, aynen korundu).
- **Çalışan motor**: benim yazdığım `memory_engine.py` — process attach,
  gerçek bellek tarama, artık **AOB/pattern (wildcard) tarama** ve
  **byte-patch/undo** da eklendi.

Önceki yüklenen versiyonda arayüz tamamen hazırdı ama hiçbir butonun arkasında
kod yoktu (`pymem` bile import edilmemişti). Bu sürümde her buton gerçekten
çalışıyor.

## Yenilikler (önceki iki sürüme göre)

- **AOB/Pattern tarama** (`memory_engine.pattern_scan`): `A1 ?? ?? ?? ?? 8B 45 FC`
  gibi wildcard destekli imzalarla adres bulma — Scanner sekmesindeki
  "Auto Signature (AOB) Builder" artık gerçekten çalışıyor.
- **Byte-level patch + undo** (`apply_byte_patch` / `restore_byte_patch`):
  Disasm & Patch sekmesi artık gerçekten ham byte yazıyor ve orijinalini
  saklayıp geri alabiliyor.
- **Kısıtlı script motoru** (`script_engine.py`): `eval()`/`exec()` KULLANMAZ,
  sadece 4 sabit komutu tanır (`ScanPattern`, `Freeze`, `Write`, `Log`).
  Bu bilinçli bir güvenlik tercihi — serbest Python çalıştıran bir "script
  engine" hem güvenlik hem kötüye kullanım riski taşır.

## Kurulum (Windows gerekli)

```
pip install -r requirements.txt
python main.py
```

Yönetici olarak çalıştırman gerekebilir (çoğu oyun process'i korumalıdır).

## .exe'ye çevirme

```
build.bat
```

**Önemli:** Bu adım **kaynak koddan** (yani `python main.py` çalışabildiğin
ortamdan) yapılmalı. Derlenmiş bir `.exe`'nin içinden kendini yeniden derlemesi
mümkün değil — PyInstaller'ın kendisi bir Python paketi, çalışan bir onefile
exe'nin içine gömülü değil. Önceki yüklenen sürümdeki "Build Trainer.exe"
sekmesi bu yüzden gerçek bir derleme yapamaz; Wizard sekmesindeki 4. adım
bunun yerine mevcut profili kaydeder ve sana doğru komutu gösterir.

## Kullanım akışı

1. **Trainer Wizard** → process seç veya `.exe` göster → **Attach**.
2. Profil daha önce kaydedilmişse otomatik yüklenir.
3. **Scanner & Auto AOB**:
   - Manuel tarama: bilinen değeri gir → First Scan → oyunda değiştir →
     yeni değeri gir → Next Scan → tek adrese inene kadar tekrarla.
   - AOB tarama: Cheat Engine'de bulduğun bir instruction'ın byte'larını
     `A1 ?? ?? ?? ??` formatında gir → Tara.
   - Sonuca çift tıkla → **Freeze Manager**'a eklenir.
4. **Freeze Manager**: checkbox ile dondur, hotkey ata, **Profili Kaydet**.
5. **Disasm & Patch**: ham byte enjekte et (örn. bir `jne`'yi `nop`'a çevirmek
   için `90 90` yaz), gerektiğinde **Geri Al** ile eski haline döndür.
6. **Script Engine**: tekrarlayan işlemleri küçük scriptlerle otomatikleştir.

## Dosya yapısı

```
LocalTrainerStudio/
  main.py            # PyQt5 arayüz + tüm buton bağlantıları
  memory_engine.py    # attach, read/write, first/next scan, AOB scan, patch/undo
  script_engine.py    # kısıtlı, güvenli mini komut dili
  profile_manager.py  # profil kaydet/yükle (JSON)
  hotkeys.py           # global tuş dinleyici
  profiles/             # oyun başına profil dosyaları
  requirements.txt
  build.bat
```

## Sınırlamalar / dürüst notlar

- Windows'ta test edilmedi (bu ortam Linux) — mantık doğru API'leri
  kullanıyor ama ilk çalıştırmada küçük hatalarla karşılaşabilirsin.
- AOB tarama brute-force byte karşılaştırması yapıyor; çok büyük bellek
  bölgelerinde (bazı Unreal Engine oyunları GB'larca commit alan açar)
  yavaş olabilir. Gerekirse bunu optimize ederiz (örn. Boyer-Moore benzeri
  bir algoritma veya bölgesel filtreleme).
- Script motoru bilinçli olarak kısıtlı — yeni komut eklemek istersen
  `script_engine.py`'deki `_run_line` fonksiyonuna yeni bir `re.match` bloğu
  eklemek yeterli.
- Bu araç yalnızca **tek oyunculu/offline** oyunlarda kullanılmak üzere
  tasarlandı.

---

## İkinci Tur Geliştirmeler (Öneriler Uygulandı)

Önceki önerilerin tamamı uygulandı ve gerçek testle doğrulandı:

1. **Pointer Scan Yardımcısı** (`find_pointers_to`): Freeze Manager'da
   "Sec: Pointer Zinciri Bul (Kalıcı Yap)" butonu — ham bir adres için
   modül+offset zinciri arar (1-2 seviye). Cheat Engine'deki tam pointer
   scanner kadar kapsamlı değil ama pratik ve gerçek testle doğrulandı.
2. **AOB tarama çapa optimizasyonu**: İlk sabit byte yerine, 0x00/0xFF/
   0x90/0xCC gibi aşırı yaygın dolgu byte'larından KAÇINAN bir çapa seçiliyor
   — gerçek oyun pattern'lerinde (genelde 0x00 içerir) belirgin hızlanma.
3. **Freeze Manager'da satır içi düzenleme**: "Değer" hücresine çift tıkla,
   yaz, Enter'a bas — ayrı bir dialog açmaya gerek yok.
4. **Profil Dışa/İçe Aktarma**: Wizard sekmesinde "Dışa Aktar"/"İçe Aktar"
   butonları — profili `.json` olarak kaydedip başka bir bilgisayara
   taşıyabilirsin.
5. **Log dosyası**: Tüm loglar artık `logs/session_TARIH_SAAT.log`
   dosyasına da yazılıyor.

### Kritik bir ek düzeltme: pointer-zincirli girişler artık GERÇEKTEN çalışıyor
Önceki turda `offsets` alanı profile kaydediliyor/yükleniyordu ama **hiçbir
okuma/yazma kodu bu zinciri gerçekten çözmüyordu** — sadece ham `address`
alanına bakılıyordu. Bu, başka bir bilgisayardan içe aktarılan veya
"Pointer Zinciri Bul" ile oluşturulan kalıcı bir cheat'in sessizce hiçbir
şey yapmamasına yol açardı. Eklenen `_resolve_wa_address()` merkezi
fonksiyonu artık her okuma/yazmadan önce (tablo gösterimi, Freeze, hotkey,
satır içi düzenleme) pointer zincirini yeniden çözüyor. Bu, sahte bir
bellek ortamında (`address=0`, sadece `offsets=[0x20, 0x8]`) uçtan uca
test edilerek doğrulandı.


---

## GitHub'a Yükleme ve Tam Otomatik Yayın (CI/CD) Kurulumu

Bu bölüm, projeyi senin `barkinaydemir42-art/GameTrainer` reposuna yükleyip,
her yeni sürümde **otomatik olarak** gerçek bir `Setup.exe` kurulum dosyası
üretecek ve uygulamanın "Güncelleme" sekmesinin göreceği manifesti
güncelleyecek şekilde bağlamanı anlatır. Kurulumdan sonra senin yapman
gereken tek şey her yeni sürümde bir `git tag` push'lamak — gerisi
(derleme, Setup.exe oluşturma, Release açma, manifesti güncelleme)
GitHub Actions tarafından otomatik yapılır.

### 1) Projeyi GitHub reposuna yükle

Bu `.zip`'i açtığın klasörde (`LocalTrainerStudio/`) bir terminal aç:

```bash
cd LocalTrainerStudio
git init
git remote add origin https://github.com/barkinaydemir42-art/GameTrainer.git
git add -A
git commit -m "İlk yükleme: LocalTrainer Studio"
git branch -M main
git push -u origin main
```

(Repo GitHub'da zaten boş/hemen hemen boşsa bu sorunsuz çalışır. İçinde
farklı bir ilk commit varsa `git push -u origin main --force` gerekebilir
ama önce mevcut içeriği kaybetmek istemediğinden emin ol.)

### 2) Uygulamada manifest URL'ini ayarla

Uygulamayı aç → **Güncelleme** sekmesi → Manifest URL alanına şunu yaz:
```
https://raw.githubusercontent.com/barkinaydemir42-art/GameTrainer/main/update_manifest.json
```
**Kaydet**'e bas. Artık uygulama her açıldığında (veya "Kontrol Et"e
bastığında) bu dosyayı kontrol edecek.

### 3) İlk sürümü yayınla

```bash
git tag v1.1.0
git push origin v1.1.0
```

Bu, `.github/workflows/release.yml` içindeki GitHub Actions iş akışını
otomatik tetikler. Arka planda olan biten (senin hiçbir şey yapmana gerek
yok):
1. `updater.py` içindeki `CURRENT_VERSION`, tag'e göre (`1.1.0`) güncellenir
2. `LocalTrainerStudio.exe` PyInstaller ile derlenir
3. `installer.iss` (Inno Setup) ile gerçek bir Windows kurulum sihirbazı
   olan **`LocalTrainerStudio-Setup.exe`** üretilir (Program Files'a kurar,
   Başlat Menüsü + Masaüstü kısayolu ekler, düzgün bir kaldırıcı/uninstaller
   içerir — tıpkı gerçek bir ticari uygulama gibi)
4. Bu `.exe`'nin SHA256'sı hesaplanır, `update_manifest.json` otomatik
   güncellenir ve repoya geri commit'lenir
5. GitHub'da bir **Release** açılır ve `LocalTrainerStudio-Setup.exe`
   oraya yüklenir

İlerlemeyi GitHub reposunun **Actions** sekmesinden izleyebilirsin
(`https://github.com/barkinaydemir42-art/GameTrainer/actions`).
İşlem bitince **Releases** sekmesinde `LocalTrainerStudio-Setup.exe`'yi
görürsün — bunu ilk kurulum için istediğin bilgisayara indirip çalıştırman
yeterli.

### 4) Sonraki her güncelleme için

Kodda değişiklik yap, commit'le, push'la, sonra sadece yeni bir tag at:
```bash
git add -A
git commit -m "Yeni özellik: ..."
git push
git tag v1.2.0
git push origin v1.2.0
```
Zaten kurulu olan kullanıcılar uygulamayı açtığında (veya "Kontrol Et"e
bastığında) yeni sürümü görecek, **"Şimdi Güncelle"** dediklerinde
`LocalTrainerStudio-Setup.exe` sessizce (pencere göstermeden) inecek,
Inno Setup'ın `/CLOSEAPPLICATIONS /RESTARTAPPLICATIONS` bayrakları sayesinde
çalışan uygulamayı kapatıp kurulumu yapacak ve uygulamayı otomatik yeniden
açacak. Yani gerçek bir ticari yazılımın güncelleme deneyimiyle aynı.

### Neden Inno Setup / gerçek Setup.exe?

Önceki tur sadece PyInstaller'ın ürettiği ham `.exe`'yi indirip üzerine
kopyalıyordu (dosya kilidi riskiyle uğraşan kırılgan bir `.bat` script'i
ile). Artık:
- Gerçek bir kurulum sihirbazı var (dil seçimi, lisans/dizin adımları,
  Başlat Menüsü/Masaüstü kısayolu, düzgün bir "Programlar ve Özellikler"
  kaydı, gerçek bir kaldırıcı).
- Güncelleme sırasında dosya kilidi sorunları Inno Setup'ın kendi
  `/CLOSEAPPLICATIONS` mekanizmasıyla çözülüyor — kendi yazdığımız kırılgan
  `.bat` script'ine güvenmiyoruz.
- `installer=false` olan eski (ham `.exe` kopyalama) yöntem de hâlâ kodda
  duruyor, geriye dönük uyumluluk için (manifestte `"installer": false`
  yazarsan o yöntem kullanılır).

### Gereksinimler (bir kereye mahsus)
- GitHub reposu **public** olmalı (raw.githubusercontent.com linkinin
  kimlik doğrulamasız erişilebilir olması için — zaten `GameTrainer`
  reposu ekran görüntünde "Public" görünüyor, bu yeterli).
- Ekstra bir "secret" veya token eklemene gerek yok — GitHub Actions,
  Release oluşturmak ve repoya commit atmak için gereken izni
  (`permissions: contents: write`) iş akışı dosyasının kendisinden alıyor.

---

## Üçüncü Tur Düzeltmeler (Gerçek Kullanımda Bulunan Hatalar)

### 1) KRİTİK: Varsayılan tip `int16` idi, Cheat Engine'in `int32` ("4 Bytes") varsayılanıyla uyuşmuyordu
Cheat Engine'de "4 Bytes" olarak bulduğun bir değeri bizim uygulamada
ararken/eklerken, tip seçim kutuları listedeki **ilk elemanı** (`int16`)
varsayılan gösteriyordu. Küçük sayılarda bu tesadüfen "doğru görünüyordu"
(değerin üst 2 byte'ı sıfır olduğu için), ama gerçekte yanlış boyutta
okuma/yazma yapılıyordu — değer büyüdüğünde veya freeze (dondurma)
kullanıldığında bu, belleğin yanlış kısmına yazıp bozulmaya yol açabilirdi.
**Düzeltme:** `TYPE_MAP` sıralaması `int32` ilk sıraya alınacak şekilde
değiştirildi (Cheat Engine'in "4 Bytes" varsayılanıyla tutarlı).

### 2) Yeni özellik: "Sec: Tip Degistir"
Yanlış tiple eklenmiş bir cheat'i silip yeniden eklemene gerek kalmadan,
Freeze Manager'dan doğrudan doğru tipe (örn. int16 → int32) çevirebilirsin.

### 3) KRİTİK: Derlenmiş `.exe` sürümünde profiller/ayarlar kalıcı değildi
`profile_manager.py`, `config_manager.py` ve log dosyası, modülün
`__file__` konumuna göre bir yol hesaplıyordu. Kaynak koddan çalışırken bu
sorunsuzdu, ama **PyInstaller `--onefile` ile derlenmiş bir `.exe`
çalıştırıldığında, tüm modüller Windows'un geçici (`%TEMP%\_MEIxxxxxx`)
klasöründen çalışır** — yani kaydettiğin her profil, ayar ve log, uygulamayı
kapattığın an Windows tarafından otomatik silinen bir klasöre yazılıyordu!
**Düzeltme:** Yeni `app_paths.py` modülü eklendi — derlenmiş `.exe` halinde
`%LOCALAPPDATA%\LocalTrainerStudio` gibi kalıcı bir klasör kullanılıyor,
kaynak koddan çalışırken eskisi gibi proje klasörünün yanına yazılıyor.
Bu, sahte "frozen" ortam simülasyonuyla gerçek bir testle doğrulandı.

### 4) İyileştirme: `--uac-admin` ile otomatik yönetici yetkisi
Bellek okuma/yazma genelde yönetici yetkisi gerektirir. Kullanıcının her
seferinde "Yönetici olarak çalıştır"ı elle seçmeyi unutma riskini ortadan
kaldırmak için, derlenen `.exe`'ye artık `--uac-admin` bayrağıyla bir
manifest gömülüyor — çift tıklandığında otomatik olarak UAC yükseltme
istiyor.

Bu üç düzeltmeden sonra yeni bir `git tag` (örn. `v1.1.3`) push'layarak
(veya GitHub'da "Create a new release" ile) otomatik olarak dağıtabilirsin;
zaten kurulu kullanıcılar "Güncelleme" sekmesinden bu düzeltmeleri
otomatik alacak.

---

## Dördüncü Tur Düzeltme: "Yanıt Vermiyor" Donması (KRİTİK)

Gerçek kullanımda "Pointer Zinciri Bul" sırasında uygulama "Yanıt Vermiyor"
durumuna düştü. Kök sebep: **First Scan, Next Scan, AOB Tarama, Bilinmeyen
İlk Değer Taraması ve Pointer Zinciri Bul dahil TÜM ağır bellek tarama
işlemleri, ana arayüz (UI) thread'inde çalıştırılıyordu.** Küçük oyunlarda
bu fark edilmeyebiliyordu, ama büyük bir oyunun belleğinde (özellikle
2 seviyeli pointer scan — her aday için belleği baştan tarıyor) bu işlem
saniyelerce/dakikalarca sürdüğünde, Qt'nin olay döngüsü (event loop)
pompalanamadığı için Windows pencereyi "Yanıt Vermiyor" olarak işaretliyordu.
Program çökmüyordu ama kullanıcıya çökmüş gibi görünüyordu.

**Düzeltme:** Yeni bir `ScanWorker(QThread)` sınıfı eklendi — artık First
Scan, Next Scan, AOB Tarama, Bilinmeyen İlk Değer taraması ve Pointer
Zinciri Bul dahil **tüm ağır tarama işlemleri arka plan thread'inde**
çalışıyor. Bu, sahte bir "yavaş" fonksiyonla gerçek bir testle kanıtlandı:
tarama sürerken ana thread'in gerçekten boş kaldığı (bir QTimer'ın düzenli
tik attığı) ölçüldü.

Ek olarak:
- Pointer Zinciri Bul artık **"Hızlı (1 seviye)" / "Detaylı (2 seviye,
  çok yavaş)"** seçimi sunuyor — varsayılan olarak kullanıcı bilinçli
  bir hız/detay tercihi yapıyor.
- 2. seviye pointer taramasındaki aday sınırı 30'dan 12'ye düşürüldü
  (her aday, tüm belleği baştan tarayan ayrı bir işlem tetikliyor).
- Tarama sırasında ilgili butonlar devre dışı bırakılıyor, aynı anda
  birden fazla taramanın çakışması (ve MemoryEngine'in iç durumunun
  bozulması) engelleniyor.

Bu düzeltmeden sonra yeni bir sürüm (örn. `v1.1.4`) yayınlayabilirsin;
"Pointer Zinciri Bul" veya herhangi bir tarama artık ne kadar uzun sürerse
sürsün, pencere donmayacak, "Yanıt Vermiyor" görülmeyecek.

---

## Auto Pointer Repair (RIP-relative anchor ile otomatik onarım)

Bir kalıcı pointer zincirinin ilk adımı (`module_base + offsets[0]`) sabit
bir sayı olarak saklanıyordu. Oyun güncellenip derleyici kodu/verileri
yeniden düzenlediğinde bu sayı (RVA) kayabilir ve zincir tamamen geçersiz
hale gelirdi — kullanıcı her güncellemede pointer zincirini elden
yeniden bulmak zorunda kalıyordu.

**Çözüm:** `MemoryEngine.find_anchor_for_address()`, hedef statik adrese
kodda erişen bir RIP-relative `MOV`/`LEA` instruction'ını (x64: `REX.W +
8B/8D + ModRM(rip-relative) + disp32`, 7 byte) bulur ve `disp32`'yi
wildcard'layarak bir AOB imzası olarak kaydeder (`WatchedAddress.
anchor_pattern` / `anchor_disp_pos` / `anchor_instr_len`). Her okuma/yazmada
`MemoryEngine.resolve_watched_address()`, bu AOB'yi (artık gerçek BMH ile)
yeniden tarar, instruction'ın (muhtemelen kaymış) yeni konumundaki GÜNCEL
`disp32`'sini okuyup doğru statik adresi anında yeniden hesaplar — ayrı bir
"onar" adımı gerekmez, her zaman kendiliğinden günceldir.

Kullanım: Freeze Manager'da önce "Pointer Zinciri Bul" ile kalıcı bir
zincir oluştur, sonra "Sec: Anchor Bul (Auto-Repair)" butonuna bas. Birden
fazla instruction aynı adrese erişiyorsa (nadir değildir) bir seçim listesi
sunulur. Anchor atanan satırlar, adres sütununda `[Anchor]` etiketiyle
gösterilir ve profillere kaydedilir (eski profillerle geriye dönük
uyumludur — bu alanlar yoksa `None` olarak yüklenir, anchor'sız normal
pointer zinciri gibi davranır).

**Bilinen sınır:** bu yalnızca offsets[0]'un (statik pointer'ın KONUMU)
onarımını sağlar. Struct'ın kendisi yeniden düzenlenirse (alan
eklenip/çıkarılırsa) kalan `offsets[1:]` zinciri otomatik düzeltilemez —
bu durumda pointer zinciri yine elden yeniden bulunmalıdır. Ayrıca şu an
sadece x64 RIP-relative adresleme destekleniyor (32-bit mutlak adresleme
kullanan eski/32-bit oyunlarda anchor bulunamaz).
