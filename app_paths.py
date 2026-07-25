"""
app_paths.py
Uygulamanin profil/ayar/log gibi KALICI verilerini nereye yazacagini
dogru sekilde hesaplar.

KRITIK SORUN (bu modul olmadan): PyInstaller --onefile ile derlenmis bir
.exe calistirildiginda, kendini bir GECICI klasore (%TEMP%\\_MEIxxxxxx)
acar ve butun bundled .py modulleri o gecici klasorden calisir. Yani
bir modulun __file__'ina bakarak "yaninda bir 'profiles' klasoru olustur"
gibi bir mantik kurarsan, bu klasor GECICI klasorun icinde olusur ve
UYGULAMA KAPANINCA WINDOWS TARAFINDAN OTOMATIK SILINIR. Sonuc: kullanici
Freeze Manager'a cheat ekleyip "Profili Kaydet" dese bile, uygulamayi
kapatip actiginda profil sessizce KAYBOLUR - cunku hicbir zaman kalici
bir yere yazilmamistir.

Bu modul, derlenmis (.exe) halde calisirken kalici ve yazma izni olan
%LOCALAPPDATA%\\LocalTrainerStudio klasorunu kullanir. Kaynak koddan
(python main.py) calisirken ise eskisi gibi proje klasorunun yanina yazar
(gelistirme sirasinda profiles/ klasorunu repo icinde gormek daha kullanisli).
"""

import os
import sys


def get_app_data_dir() -> str:
    """
    Profiller, ayarlar ve loglar icin KALICI, yazma izni garantili klasoru
    dondurur. Klasor yoksa olusturur.
    """
    if getattr(sys, "frozen", False):
        # Derlenmis .exe: %LOCALAPPDATA%\LocalTrainerStudio kullan (her
        # zaman yazma izni olan, kullaniciya ozel, kalici bir konum).
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
        app_dir = os.path.join(base, "LocalTrainerStudio")
    else:
        # Kaynak koddan calisirken: script'in yaninda (eskisi gibi, gelistirme
        # sirasinda profiles/ klasorunu repo icinde gormek daha kullanisli).
        app_dir = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(app_dir, exist_ok=True)
    return app_dir
