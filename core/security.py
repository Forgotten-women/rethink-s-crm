import base64
import hashlib
import os
import shutil
from typing import Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Secret key derived from environment variable or local system secret
SECRET_SALT = os.environ.get("APP_SECRET_KEY", "RethinkCharityCRM_SecretKey_2026!").encode("utf-8")


def _get_key_bytes() -> bytes:
    """Derives a 32-byte (256-bit) key from SECRET_SALT using SHA-256."""
    return hashlib.sha256(SECRET_SALT).digest()


def encrypt_string(plain_text: str) -> str:
    """
    Encrypts a plaintext string using authenticated AES-256-GCM.
    Returns payload prefixed with 'aes::'.
    """
    if not plain_text:
        return ""
    key = _get_key_bytes()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)  # 96-bit standard GCM nonce
    data = plain_text.encode("utf-8")
    ciphertext = aesgcm.encrypt(nonce, data, None)
    return "aes::" + base64.b64encode(nonce + ciphertext).decode("utf-8")


def decrypt_string(cipher_text: str) -> str:
    """
    Decrypts an AES-256-GCM encrypted payload ('aes::...').
    Maintains backward compatibility with legacy XOR payloads ('enc::...') and plaintext strings.
    """
    if not cipher_text:
        return ""

    # Modern AES-256-GCM format
    if cipher_text.startswith("aes::"):
        try:
            raw = base64.b64decode(cipher_text[5:])
            if len(raw) < 12:
                return cipher_text
            nonce = raw[:12]
            ciphertext = raw[12:]
            key = _get_key_bytes()
            aesgcm = AESGCM(key)
            plain_bytes = aesgcm.decrypt(nonce, ciphertext, None)
            return plain_bytes.decode("utf-8")
        except Exception as e:
            print(f"[Security Notice] Failed to decrypt AES-256 string: {e}")
            return cipher_text

    # Legacy XOR format backward-compatibility
    if cipher_text.startswith("enc::"):
        try:
            raw_b64 = cipher_text[5:]
            data = base64.b64decode(raw_b64)
            key = _get_key_bytes()
            plain_bytes = bytearray()
            for idx, byte in enumerate(data):
                plain_bytes.append(byte ^ key[idx % len(key)])
            return plain_bytes.decode("utf-8")
        except Exception:
            return cipher_text

    # Plaintext fallback
    return cipher_text


def encrypt_file(source_path: str, dest_path: str) -> bool:
    """
    Encrypts an entire file to dest_path using authenticated AES-256-GCM.
    Writes atomically via a temporary file.
    """
    if not os.path.exists(source_path):
        return False

    key = _get_key_bytes()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)

    with open(source_path, "rb") as f:
        plaintext_data = f.read()

    ciphertext = aesgcm.encrypt(nonce, plaintext_data, None)

    temp_dest = dest_path + ".tmp"
    with open(temp_dest, "wb") as f:
        # Magic header (4 bytes) + Nonce (12 bytes) + Ciphertext with GCM tag
        f.write(b"AGYC")
        f.write(nonce)
        f.write(ciphertext)

    os.replace(temp_dest, dest_path)
    return True


def decrypt_file(source_path: str, dest_path: str) -> bool:
    """
    Decrypts an AES-256-GCM encrypted file to dest_path.
    Writes atomically via a temporary file.
    """
    if not os.path.exists(source_path):
        return False

    key = _get_key_bytes()
    aesgcm = AESGCM(key)

    with open(source_path, "rb") as f:
        magic = f.read(4)
        if magic != b"AGYC":
            return False
        nonce = f.read(12)
        ciphertext = f.read()

    try:
        plaintext_data = aesgcm.decrypt(nonce, ciphertext, None)
    except Exception as e:
        print(f"[Security Notice] Failed to decrypt file {source_path}: {e}")
        return False

    temp_dest = dest_path + ".tmp"
    with open(temp_dest, "wb") as f:
        f.write(plaintext_data)

    os.replace(temp_dest, dest_path)
    return True


def ensure_cache_decrypted(base_dir: Optional[str] = None) -> bool:
    """
    Cold-start check: If donations_cache.parquet is missing or empty,
    but donations_cache.parquet.enc exists, decrypt it automatically.
    Returns True on successful check/restoration.
    """
    if not base_dir:
        from config.settings import BASE_DIR
        base_dir = BASE_DIR

    cache_files = [
        "donations_cache.parquet",
        "payouts_cache.parquet",
        "paysuite_payouts_cache.parquet",
    ]

    all_ok = True
    for fname in cache_files:
        plain_path = os.path.join(base_dir, fname)
        enc_path = os.path.join(base_dir, fname + ".enc")

        if (not os.path.exists(plain_path) or os.path.getsize(plain_path) == 0) and os.path.exists(enc_path):
            print(f"[Security] Cold-start decrypting {fname}.enc -> {fname}...")
            ok = decrypt_file(enc_path, plain_path)
            if ok:
                print(f"[Security] Successfully restored {fname}.")
            else:
                print(f"[Security Error] Failed to decrypt {fname}.enc. Check APP_SECRET_KEY.")
                all_ok = False

    return all_ok
