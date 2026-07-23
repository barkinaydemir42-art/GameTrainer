"""
build_scripts/generate_manifest.py
GitHub Actions icinde, derlenen Setup.exe'nin SHA256'si ve surum bilgisiyle
update_manifest.json dosyasini otomatik uretir/gunceller. Bu dosya repo
koklerine yazilir ve CI tarafindan geri commit'lenir, boylece
raw.githubusercontent.com uzerinden okunan manifest her zaman en son
surumu gosterir.

Kullanim:
    python build_scripts/generate_manifest.py \
        --version 1.2.0 \
        --download-url https://github.com/kullanici/repo/releases/download/v1.2.0/LocalTrainerStudio-Setup.exe \
        --sha256-file installer_output/LocalTrainerStudio-Setup.exe \
        --changelog "Bu surumde neler degisti" \
        --output update_manifest.json
"""
import argparse
import hashlib
import json
import sys


def compute_sha256(file_path: str) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(
    version: str,
    download_url: str,
    sha256: str,
    changelog: str = "",
    installer: bool = True,
    silent_args: str = "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS",
) -> dict:
    return {
        "version": version,
        "changelog": changelog,
        "download_url": download_url,
        "sha256": sha256,
        "installer": installer,
        "silent_args": silent_args,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--download-url", required=True)
    parser.add_argument("--sha256-file", help="Bu dosyanin SHA256'si hesaplanip manifeste yazilir")
    parser.add_argument("--sha256", help="Hazir SHA256 degeri (--sha256-file yerine)")
    parser.add_argument("--changelog", default="")
    parser.add_argument("--installer", action="store_true", default=True)
    parser.add_argument(
        "--silent-args",
        default="/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS",
    )
    parser.add_argument("--output", default="update_manifest.json")
    args = parser.parse_args()

    if args.sha256:
        sha256 = args.sha256
    elif args.sha256_file:
        sha256 = compute_sha256(args.sha256_file)
    else:
        print("HATA: --sha256 veya --sha256-file gerekli.", file=sys.stderr)
        sys.exit(1)

    manifest = build_manifest(
        version=args.version,
        download_url=args.download_url,
        sha256=sha256,
        changelog=args.changelog,
        installer=args.installer,
        silent_args=args.silent_args,
    )

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"Manifest yazildi: {args.output}")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
