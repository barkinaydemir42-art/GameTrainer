"""
build_scripts/set_version.py
Git tag'inden (ornek: v1.2.0) gelen surum numarasini updater.py icindeki
CURRENT_VERSION sabitine yazar. GitHub Actions bunu her release'de otomatik
calistirir, boylece kod icinde elle surum guncellemesi gerekmez.

Kullanim:
    python build_scripts/set_version.py 1.2.0
"""
import re
import sys
import os

UPDATER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "updater.py")


def set_version(new_version: str, updater_path: str = UPDATER_PATH) -> str:
    if not re.match(r"^\d+\.\d+\.\d+$", new_version):
        raise ValueError(f"Gecersiz surum formati: '{new_version}' (beklenen: X.Y.Z)")

    with open(updater_path, "r", encoding="utf-8") as f:
        content = f.read()

    new_content, count = re.subn(
        r'CURRENT_VERSION = "[^"]*"',
        f'CURRENT_VERSION = "{new_version}"',
        content,
        count=1,
    )
    if count == 0:
        raise ValueError("updater.py icinde CURRENT_VERSION satiri bulunamadi.")

    with open(updater_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    return new_content


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Kullanim: python set_version.py 1.2.0")
        sys.exit(1)
    version_arg = sys.argv[1].lstrip("v")  # 'v1.2.0' -> '1.2.0'
    set_version(version_arg)
    print(f"updater.py CURRENT_VERSION = \"{version_arg}\" olarak guncellendi.")
