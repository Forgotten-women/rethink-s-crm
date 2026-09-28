#!/usr/bin/env python3
"""
scripts/secure_cache_sync.py
Automated AES-256-GCM Parquet Cache Encryption, Backup, and Cold-Start Recovery Utility.

Allows safe tracking and synchronization of Parquet donor datasets without exposing donor PII.
Raw `.parquet` files are ignored in Git, while `.parquet.enc` and `cache_manifest.json` are tracked.
"""

import os
import sys
import json
import hashlib
import argparse
from datetime import datetime

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.security import encrypt_file, decrypt_file, ensure_cache_decrypted
from config.settings import PARQUET_PATH

CACHE_FILES = [
    ("donations_cache.parquet", "donations_cache.parquet.enc"),
    ("payouts_cache.parquet", "payouts_cache.parquet.enc"),
    ("paysuite_payouts_cache.parquet", "paysuite_payouts_cache.parquet.enc"),
]

MANIFEST_FILE = os.path.join(PROJECT_ROOT, "cache_manifest.json")


def _compute_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def get_parquet_row_count(filepath: str) -> int:
    try:
        import pyarrow.parquet as pq
        parquet_file = pq.ParquetFile(filepath)
        return parquet_file.metadata.num_rows
    except Exception:
        try:
            import pandas as pd
            df = pd.read_parquet(filepath, columns=[])
            return len(df)
        except Exception:
            return -1


def encrypt_caches():
    """Encrypts all existing raw .parquet files into .parquet.enc and updates manifest."""
    manifest = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "algorithm": "AES-256-GCM",
        "caches": {}
    }

    encrypted_count = 0
    for raw_name, enc_name in CACHE_FILES:
        raw_path = os.path.join(PROJECT_ROOT, raw_name)
        enc_path = os.path.join(PROJECT_ROOT, enc_name)

        if not os.path.exists(raw_path):
            continue

        raw_size = os.path.getsize(raw_path)
        row_count = get_parquet_row_count(raw_path)
        print(f"🔒 Encrypting '{raw_name}' ({raw_size:,} bytes, {row_count:,} records)...")

        success = encrypt_file(raw_path, enc_path)
        if success:
            enc_size = os.path.getsize(enc_path)
            enc_sha = _compute_sha256(enc_path)
            manifest["caches"][raw_name] = {
                "encrypted_file": enc_name,
                "encrypted_sha256": enc_sha,
                "encrypted_size_bytes": enc_size,
                "raw_size_bytes": raw_size,
                "record_count": row_count,
                "updated_at": datetime.utcnow().isoformat() + "Z"
            }
            encrypted_count += 1
            print(f"   ✅ Saved: '{enc_name}' ({enc_size:,} bytes, sha256: {enc_sha[:12]}...)")
        else:
            print(f"   ❌ Failed to encrypt '{raw_name}'")

    with open(MANIFEST_FILE, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\n✨ Manifest saved to '{os.path.basename(MANIFEST_FILE)}'. Total encrypted: {encrypted_count}")


def decrypt_caches():
    """Decrypts all .parquet.enc files into raw .parquet."""
    decrypted_count = 0
    for raw_name, enc_name in CACHE_FILES:
        raw_path = os.path.join(PROJECT_ROOT, raw_name)
        enc_path = os.path.join(PROJECT_ROOT, enc_name)

        if not os.path.exists(enc_path):
            continue

        enc_size = os.path.getsize(enc_path)
        print(f"🔓 Decrypting '{enc_name}' ({enc_size:,} bytes)...")

        success = decrypt_file(enc_path, raw_path)
        if success:
            raw_size = os.path.getsize(raw_path)
            row_count = get_parquet_row_count(raw_path)
            print(f"   ✅ Restored: '{raw_name}' ({raw_size:,} bytes, {row_count:,} records)")
            decrypted_count += 1
        else:
            print(f"   ❌ Failed to decrypt '{enc_name}'. Check your APP_SECRET_KEY in .env.")

    print(f"\n✨ Decryption complete. Total decrypted: {decrypted_count}")


def status():
    """Prints the current status of all raw and encrypted cache files."""
    print("=" * 70)
    print("  PARQUET CACHE SECURITY & TRACKING STATUS")
    print("=" * 70)

    for raw_name, enc_name in CACHE_FILES:
        raw_path = os.path.join(PROJECT_ROOT, raw_name)
        enc_path = os.path.join(PROJECT_ROOT, enc_name)

        raw_exists = os.path.exists(raw_path)
        enc_exists = os.path.exists(enc_path)

        raw_info = f"{os.path.getsize(raw_path):,} bytes" if raw_exists else "MISSING"
        enc_info = f"{os.path.getsize(enc_path):,} bytes" if enc_exists else "MISSING"

        print(f"\n📦 Dataset: {raw_name}")
        print(f"   Raw Parquet:       {'✅' if raw_exists else '❌'} {raw_info}")
        print(f"   Encrypted Archive: {'✅' if enc_exists else '❌'} {enc_info}")

    if os.path.exists(MANIFEST_FILE):
        with open(MANIFEST_FILE, "r") as f:
            manifest = json.load(f)
        print(f"\n📄 Manifest: Generated at {manifest.get('generated_at', 'unknown')}")
    else:
        print("\n📄 Manifest: No cache_manifest.json found.")
    print("=" * 70)


def verify():
    """Verifies that encryption and decryption round-trip correctly without data corruption."""
    print("🔍 Testing AES-256-GCM encryption round-trip integrity...")
    test_raw = os.path.join(PROJECT_ROOT, "test_cache.tmp")
    test_enc = os.path.join(PROJECT_ROOT, "test_cache.tmp.enc")
    test_out = os.path.join(PROJECT_ROOT, "test_cache_out.tmp")

    try:
        sample_data = b"AntigravityParquetTestData::" + os.urandom(1024)
        with open(test_raw, "wb") as f:
            f.write(sample_data)

        if not encrypt_file(test_raw, test_enc):
            print("❌ Encryption test failed.")
            return False

        if not decrypt_file(test_enc, test_out):
            print("❌ Decryption test failed.")
            return False

        with open(test_out, "rb") as f:
            recovered_data = f.read()

        if sample_data == recovered_data:
            print("✅ Verification passed! Data matches byte-for-byte with authenticated GCM tag.")
            return True
        else:
            print("❌ Verification failed! Data mismatch.")
            return False
    finally:
        for p in [test_raw, test_enc, test_out]:
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass


def main():
    parser = argparse.ArgumentParser(description="Secure Parquet Cache Sync Utility")
    parser.add_argument("command", choices=["encrypt", "decrypt", "status", "verify", "auto-restore"],
                        help="Action to perform: encrypt, decrypt, status, verify, auto-restore")

    args = parser.parse_args()

    if args.command == "encrypt":
        encrypt_caches()
    elif args.command == "decrypt":
        decrypt_caches()
    elif args.command == "status":
        status()
    elif args.command == "verify":
        verify()
    elif args.command == "auto-restore":
        ensure_cache_decrypted()
        status()


if __name__ == "__main__":
    main()
