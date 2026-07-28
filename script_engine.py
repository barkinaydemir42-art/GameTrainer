"""
script_engine.py
Kisitli bir "makro" dili yorumlayicisi. Guvenlik icin eval()/exec() KULLANMAZ -
sadece asagida tanimli sabit komutlari satir satir ayristirir.

Desteklenen komutlar:
    isim = ScanPattern('A1 ?? ?? ?? ??')
    Freeze(isim, 999)
    Write(isim, 100)
    Log('mesaj')

Kosullu tetikleyici (Trigger) - deger bir esigi gectiginde (kenar tetikleme,
yani kosul FALSE'tan TRUE'ya donunce bir kez) govdeyi calistirir:
    Trigger AdSuyu: HealthAddr < 20
        Write(HealthAddr, 999)
        Log('Can azaldi, dolduruldu')
    EndTrigger

Zamanlayici (Timer) - govdeyi her N saniyede bir tekrar calistirir:
    Timer Periyodik: 5
        Log('5 saniye gecti')
    EndTimer

Trigger ve Timer govdeleri arka plan donguusu (~500ms) her
tick() cagrildiginda kontrol edilir; oyun kapaliyken/attach yokken
calismazlar.

Ornek script:
    HealthAddr = ScanPattern('A1 ?? ?? ?? ?? 8B 45 FC')
    Freeze(HealthAddr, 999)
    Log('Can dondu')
"""

import re
import time
from typing import Callable, Dict

from memory_engine import MemoryEngine


class ScriptError(Exception):
    pass


class ScriptEngine:
    def __init__(self, engine: MemoryEngine, on_log: Callable[[str], None] = None):
        self.engine = engine
        self.variables: Dict[str, int] = {}
        self.on_log = on_log or (lambda msg: None)
        # (address, value_type, value) - freeze edilenler disaridan periyodik uygulanir
        self.frozen: Dict[str, tuple] = {}
        # kosullu tetikleyiciler: isim -> {var, op, value, body, was_true}
        self.triggers: Dict[str, dict] = {}
        # zamanlayicilar: isim -> {interval, body, last_run}
        self.timers: Dict[str, dict] = {}

    def _log(self, msg: str):
        self.on_log(msg)

    _TRIGGER_RE = re.compile(
        r"^Trigger\s+(\w+)\s*:\s*(\w+)\s*(<=|>=|==|!=|<|>)\s*([\-0-9.]+)\s*$"
    )
    _TIMER_RE = re.compile(r"^Timer\s+(\w+)\s*:\s*([0-9.]+)\s*$")

    def run(self, script_text: str):
        """Scripti satir satir calistirir. Hatali/bilinmeyen komutlarda ScriptError firlatir.
        Trigger/Timer bloklari calistirilmaz, sadece tanimlanir (kayda alinir);
        gercek calisma tick() ile arka plan donguusunden yapilir."""
        lines = script_text.splitlines()
        i = 0
        while i < len(lines):
            raw_line = lines[i]
            line = raw_line.strip()
            if not line or line.startswith("--") or line.startswith("#"):
                i += 1
                continue

            m = self._TRIGGER_RE.match(line)
            if m:
                name, var, op, value_str = m.groups()
                body, i = self._read_block(lines, i + 1, "EndTrigger", "Trigger " + name)
                value = float(value_str) if "." in value_str else int(value_str)
                self.triggers[name] = {
                    "var": var, "op": op, "value": value,
                    "body": body, "was_true": False,
                }
                self._log(f"Trigger tanimlandi: {name} ({var} {op} {value_str})")
                continue

            m = self._TIMER_RE.match(line)
            if m:
                name, interval_str = m.groups()
                body, i = self._read_block(lines, i + 1, "EndTimer", "Timer " + name)
                self.timers[name] = {
                    "interval": float(interval_str), "body": body,
                    "last_run": time.time(),
                }
                self._log(f"Zamanlayici tanimlandi: {name} (her {interval_str} sn)")
                continue

            try:
                self._run_line(line)
            except ScriptError:
                raise
            except Exception as e:
                raise ScriptError(f"Satir {i + 1}: '{line}' calistirilamadi -> {e}")
            i += 1

    def _read_block(self, lines, start_i: int, end_keyword: str, block_label: str):
        """start_i'den itibaren end_keyword satirina kadar olan (bos olmayan)
        satirlari govde olarak toplar. (govde, end_keyword'den sonraki index) dondurur."""
        body = []
        i = start_i
        while i < len(lines) and lines[i].strip() != end_keyword:
            if lines[i].strip():
                body.append(lines[i].strip())
            i += 1
        if i >= len(lines):
            raise ScriptError(f"'{block_label}' icin '{end_keyword}' bulunamadi")
        return body, i + 1

    def _run_line(self, line: str):
        # isim = ScanPattern('...')
        m = re.match(r"^(\w+)\s*=\s*ScanPattern\(\s*'([^']*)'\s*\)$", line)
        if m:
            var_name, pattern = m.groups()
            results = self.engine.pattern_scan(pattern, max_results=1)
            if not results:
                self._log(f"UYARI: '{pattern}' icin adres bulunamadi.")
                self.variables[var_name] = None
            else:
                self.variables[var_name] = results[0]
                self._log(f"{var_name} = {hex(results[0])}")
            return

        # Freeze(isim, deger)
        m = re.match(r"^Freeze\(\s*(\w+)\s*,\s*([\-0-9.]+)\s*\)$", line)
        if m:
            var_name, value_str = m.groups()
            addr = self.variables.get(var_name)
            if addr is None:
                raise ScriptError(f"'{var_name}' tanimli degil veya adres bulunamadi")
            value = float(value_str) if "." in value_str else int(value_str)
            self.frozen[var_name] = (addr, "float" if "." in value_str else "int32", value)
            self._log(f"Freeze: {var_name} -> {value}")
            return

        # Write(isim, deger)
        m = re.match(r"^Write\(\s*(\w+)\s*,\s*([\-0-9.]+)\s*\)$", line)
        if m:
            var_name, value_str = m.groups()
            addr = self.variables.get(var_name)
            if addr is None:
                raise ScriptError(f"'{var_name}' tanimli degil veya adres bulunamadi")
            value = float(value_str) if "." in value_str else int(value_str)
            vtype = "float" if "." in value_str else "int32"
            self.engine.write_value(addr, vtype, value)
            self._log(f"Write: {var_name} <- {value}")
            return

        # Log('mesaj')
        m = re.match(r"^Log\(\s*'([^']*)'\s*\)$", line)
        if m:
            self._log(m.group(1))
            return

        raise ScriptError("Bilinmeyen komut")

    def apply_frozen(self):
        """Arka plan dongusunden periyodik cagrilir - frozen degiskenleri tekrar yazar."""
        for var_name, (addr, vtype, value) in self.frozen.items():
            try:
                self.engine.write_value(addr, vtype, value)
            except Exception:
                pass

    def tick(self):
        """Arka plan dongusunden (~500ms) periyodik cagrilir. Tanimli
        Timer'lari (sure dolunca govdeyi tekrar calistirir) ve Trigger'lari
        (kosul FALSE->TRUE olunca govdeyi bir kez calistirir - kenar
        tetikleme, tekrar tekrar tetiklenip loglari/yazmalari spamlemez)
        kontrol eder. engine bagli degilse hicbir sey yapmaz."""
        if not self.engine.attached:
            return

        now = time.time()
        for name, timer in self.timers.items():
            if now - timer["last_run"] >= timer["interval"]:
                timer["last_run"] = now
                self._run_body(timer["body"], f"Timer '{name}'")

        for name, trig in self.triggers.items():
            addr = self.variables.get(trig["var"])
            if addr is None:
                continue
            try:
                current = self.engine.read_value(addr, "int32")
            except Exception:
                continue
            is_true = self._compare(current, trig["op"], trig["value"])
            if is_true and not trig["was_true"]:
                self._log(
                    f"Trigger '{name}' tetiklendi: {current} {trig['op']} {trig['value']}"
                )
                self._run_body(trig["body"], f"Trigger '{name}'")
            trig["was_true"] = is_true

    def _run_body(self, body, context: str):
        for line in body:
            try:
                self._run_line(line)
            except Exception as e:
                self._log(f"{context} icinde hata ('{line}'): {e}")

    @staticmethod
    def _compare(current, op, value) -> bool:
        if op == "<":
            return current < value
        if op == ">":
            return current > value
        if op == "<=":
            return current <= value
        if op == ">=":
            return current >= value
        if op == "==":
            return current == value
        if op == "!=":
            return current != value
        return False

    def reset_triggers(self):
        """Yeni bir script calistirmadan once eski Trigger/Timer tanimlarini
        temizler (attach/detach veya 'Calistir'e tekrar basildiginda kullanilir)."""
        self.triggers.clear()
        self.timers.clear()
