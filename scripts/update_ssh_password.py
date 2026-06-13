#!/usr/bin/env python3
"""
SSH sifresini tek yerden guncelle: scripts/.deploy.secrets
Tum bat dosyalari (PROMETHEUS_*, DURUM_KONTROL, REBUILD_*) bu dosyayi okur.
"""
from __future__ import annotations

import getpass
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / "scripts" / ".deploy.secrets"
SECRETS_EXAMPLE = ROOT / "scripts" / ".deploy.secrets.example"

# Eski sifre metni gecen dosyalarda tara (git'e girmemis yerel dosyalar)
SCAN_DIRS = ("scripts",)
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".next", "dist", "build"}
SKIP_FILES = {".deploy.secrets.example"}


def read_secrets(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip().strip('"').strip("'")
    return data


def write_secrets(path: Path, data: dict[str, str], order: list[str] | None = None) -> None:
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    else:
        lines = SECRETS_EXAMPLE.read_text(encoding="utf-8").splitlines()

    keys_written: set[str] = set()
    out: list[str] = []
    for line in lines:
        if "=" in line and not line.strip().startswith("#"):
            k = line.split("=", 1)[0].strip()
            if k in data:
                out.append(f"{k}={data[k]}")
                keys_written.add(k)
                continue
        out.append(line)

    for k, v in data.items():
        if k not in keys_written:
            out.append(f"{k}={v}")

    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def iter_scan_files() -> list[Path]:
    found: list[Path] = []
    roots = [ROOT]
    for sub in SCAN_DIRS:
        if sub != ".":
            p = ROOT / sub
            if p.exists():
                roots.append(p)

    for base in roots:
        if base == ROOT:
            candidates = list(base.glob("*.bat")) + list(base.glob("*.ps1")) + list(base.glob("*.py"))
        else:
            candidates = list(base.rglob("*"))
        for p in candidates:
            if not p.is_file():
                continue
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            if p.name in SKIP_FILES:
                continue
            name = p.name.lower()
            if p.suffix.lower() in {".py", ".bat", ".ps1", ".sh", ".md"}:
                found.append(p)
            elif name.startswith(".env") or name.endswith(".secrets"):
                found.append(p)

    uniq = {str(p.resolve()): p for p in found}
    return sorted(uniq.values(), key=lambda x: str(x))


def replace_literal_in_file(path: Path, old: str, new: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return False
    if old not in text:
        return False
    path.write_text(text.replace(old, new), encoding="utf-8")
    return True


def upsert_vps_pass_line(text: str, new_pass: str) -> str:
    if re.search(r"^VPS_PASS=.*$", text, re.MULTILINE):
        return re.sub(r"^VPS_PASS=.*$", f"VPS_PASS={new_pass}", text, count=1, flags=re.MULTILINE)
    return text.rstrip() + f"\nVPS_PASS={new_pass}\n"


def main() -> int:
    print()
    print("=" * 58)
    print("  SSH SIFRE GUNCELLEME")
    print("  Kaynak: scripts\\.deploy.secrets")
    print("=" * 58)
    print()
    print("  ONEMLI: Once sunucu panelinden SSH sifresini degistirin,")
    print("  sonra buraya YENI sifreyi yazin.")
    print()

    current = read_secrets(SECRETS)
    old_pass = current.get("VPS_PASS", "")

    if old_pass:
        print(f"  Mevcut kayitli sifre: {'*' * min(len(old_pass), 12)} ({len(old_pass)} karakter)")
    else:
        print("  Mevcut: scripts/.deploy.secrets yok veya VPS_PASS bos")
        if SECRETS_EXAMPLE.exists() and not SECRETS.exists():
            print("  Ornek dosyadan olusturulacak.")
    print()

    new_pass = getpass.getpass("  Yeni SSH sifresi: ")
    if not new_pass:
        print("HATA: Bos sifre.")
        return 1
    new_pass2 = getpass.getpass("  Tekrar (dogrulama): ")
    if new_pass != new_pass2:
        print("HATA: Sifreler eslesmiyor.")
        return 1

    # 1) Ana dosya
    if not SECRETS.exists() and SECRETS_EXAMPLE.exists():
        SECRETS.write_text(SECRETS_EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")

    data = read_secrets(SECRETS)
    data["VPS_PASS"] = new_pass
    if "VPS_HOST" not in data:
        data["VPS_HOST"] = "194.163.181.39"
    if "VPS_USER" not in data:
        data["VPS_USER"] = "root"
    write_secrets(SECRETS, data)
    print(f"\n  [OK] {SECRETS.relative_to(ROOT)}")

    # 2) VPS_PASS= satiri olan diger dosyalar
    extra_updated: list[str] = []
    for path in iter_scan_files():
        if path.resolve() == SECRETS.resolve():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "VPS_PASS=" not in text:
            continue
        new_text = upsert_vps_pass_line(text, new_pass)
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            extra_updated.append(str(path.relative_to(ROOT)))

    if extra_updated:
        print("  [OK] VPS_PASS satiri guncellenen dosyalar:")
        for f in extra_updated:
            print(f"       - {f}")

    # 3) Eski sifre duz metin olarak baska dosyalarda varsa degistir
    if old_pass and old_pass != new_pass:
        sweep = input("\n  Eski sifreyi tum projede metin olarak da degistireyim mi? [E/h]: ").strip().lower()
        if sweep in ("", "e", "evet", "y", "yes"):
            swept: list[str] = []
            for path in iter_scan_files():
                if path.resolve() == SECRETS.resolve():
                    continue
                if replace_literal_in_file(path, old_pass, new_pass):
                    swept.append(str(path.relative_to(ROOT)))
            if swept:
                print("  [OK] Eski sifre metni silinen dosyalar:")
                for f in swept:
                    print(f"       - {f}")
            else:
                print("  [OK] Baska dosyada eski sifre metni bulunamadi.")

    print()
    print("=" * 58)
    print("  TAMAM — su bat dosyalari otomatik yeni sifreyi kullanir:")
    print("    PROMETHEUS_AYAGA_KALDIR.bat")
    print("    PROMETHEUS_SKIP.bat")
    print("    DURUM_KONTROL.bat")
    print("    REBUILD_ESKI_IMAJ.bat")
    print("=" * 58)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
VPS_PASS=q204Y5u9C8jk8zfuC8jk8zfuQ5u8jkQ5u8jk8zfBdflu5
