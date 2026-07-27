# main.py — Signature Cache patch

## 1) `_load_profile_data` — cache'ten anında çözme

Eskisini şununla değiştir:

```python
    def _load_profile_data(self, data: Optional[dict]):
        if not data:
            return
        self.current_game_label = data.get("game_label", self.engine.process_name or "")
        self.watched.clear()
        permanent_count = 0
        cached_count = 0
        temp_count = 0
        for c in data.get("cheats", []):
            offsets = c.get("offsets", [])
            wa = WatchedAddress(
                name=c["name"], address=c.get("address", 0), value_type=c["value_type"],
                offsets=offsets, hotkey=c.get("hotkey"),
            )
            wa.aob_pattern = c.get("aob_pattern")
            wa.cache_module_offset = c.get("cache_module_offset")
            wa.cache_exe_fingerprint = c.get("cache_exe_fingerprint")
            if offsets:
                permanent_count += 1
            elif wa.cache_module_offset is not None and self.engine.attached:
                # AOB imza cache'i: exe ayni surumdeyse yeniden AOB
                # taramasi yapmadan dogrudan cozulur (base + kayitli offset).
                cached = self.engine.resolve_cached_address(
                    wa.cache_module_offset, wa.cache_exe_fingerprint,
                    verify_pattern=wa.aob_pattern,
                )
                if cached is not None:
                    wa.address = cached
                    cached_count += 1
                else:
                    temp_count += 1
            else:
                temp_count += 1
            self.watched.append(wa)
            if wa.hotkey:
                self._bind_hotkey(wa)
        self._refresh_freeze_table()
        self.log(f"'{self.current_game_label}' profili yuklendi ({len(self.watched)} cheat).")
        if cached_count:
            self.log(f" -> {cached_count} tanesi imza cache'inden aninda cozuldu (AOB taramasi ATLANDI).")
        if temp_count:
            self.log(
                f" -> {temp_count} tanesi ham adres (pointer zinciri/gecerli cache yok); "
                "bu oyun kapatilip yeniden acildiysa gecersiz olabilir."
            )
        if permanent_count:
            self.log(f" -> {permanent_count} tanesi kalici pointer zinciri, her zaman gecerli.")
```

Not: eski sürümde her `wa.hotkey` için `self._bind_hotkey(wa)` çağrısı
zaten `_load_profile_data` dışında yapılmıyordu — kontrol et, eğer
zaten başka bir yerde bağlanıyorsa yukarıdaki döngüdeki
`if wa.hotkey: self._bind_hotkey(wa)` satırını tekrar eklemene gerek yok.

## 2) `_add_aob_result_to_watchlist` — bulunca cache'e yaz

Eskisini şununla değiştir:

```python
    def _add_aob_result_to_watchlist(self, item: QListWidgetItem):
        address = int(item.text(), 16)
        name, ok = QInputDialog.getText(self, "Isim ver", "Bu AOB sonucu icin isim:")
        if not ok or not name:
            return
        vtype, ok2 = QInputDialog.getItem(
            self, "Deger tipi", "Bu adresteki deger tipi:",
            ALL_TYPES, editable=False,
        )
        if not ok2:
            vtype = "int32"
        wa = WatchedAddress(name=name, address=address, value_type=vtype)
        # Imza cache: bu adresi bulan pattern + o anki exe fingerprint'i
        # sakla, boylece bir sonraki attach'te (exe ayniysa) AOB taramasi
        # tekrar calismadan address = yeni_base + module_offset ile cozulur.
        pattern = self.aob_pattern_edit.text().strip()
        module_offset = self.engine.to_module_offset(address)
        if pattern and module_offset is not None:
            wa.aob_pattern = pattern
            wa.cache_module_offset = module_offset
            wa.cache_exe_fingerprint = self.engine.get_exe_fingerprint()
        self.watched.append(wa)
        self._refresh_freeze_table()
        self.log(f"'{name}' (AOB) Freeze Manager'a eklendi.")
```

## Sonuç

- İlk AOB taraması aynı şekilde çalışır.
- "Profili Kaydet" dediğinde pattern + module-offset + exe fingerprint
  de kaydedilir.
- Bir sonraki attach + profil yüklemede: exe aynıysa (fingerprint
  eşleşirse) adres AOB taraması hiç çalıştırılmadan anında hesaplanır
  ve doğrulanır (pattern hâlâ o adreste mi diye tek okuma ile kontrol).
- Oyun güncellenip exe değişirse fingerprint uyuşmaz, otomatik olarak
  eski (session'a özel, geçersiz olabilecek) davranışa döner — kullanıcı
  yeniden AOB tarar.
