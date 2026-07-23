"""
script_engine.py
Kisitli bir "makro" dili yorumlayicisi. Guvenlik icin eval()/exec() KULLANMAZ -
sadece asagida tanimli sabit komutlari satir satir ayristirir.

Desteklenen komutlar:
    isim = ScanPattern('A1 ?? ?? ?? ??')
    Freeze(isim, 999)
    Write(isim, 100)
    Log('mesaj')

Ornek script:
    HealthAddr = ScanPattern('A1 ?? ?? ?? ?? 8B 45 FC')
    Freeze(HealthAddr, 999)
    Log('Can dondu')
"""

import re
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

    def _log(self, msg: str):
        self.on_log(msg)

    def run(self, script_text: str):
        """Scripti satir satir calistirir. Hatali/bilinmeyen komutlarda ScriptError firlatir."""
        for lineno, raw_line in enumerate(script_text.splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith("--") or line.startswith("#"):
                continue
            try:
                self._run_line(line)
            except ScriptError:
                raise
            except Exception as e:
                raise ScriptError(f"Satir {lineno}: '{line}' calistirilamadi -> {e}")

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
