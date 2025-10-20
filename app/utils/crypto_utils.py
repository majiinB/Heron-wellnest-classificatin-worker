import hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def get_key(secret: str) -> bytes:
    """Derive a 32-byte key (same as Node.js getKey)"""
    return hashlib.sha256(secret.encode()).digest()

def is_valid_hex_key(secret: str) -> bool:
    """Check if secret is a 32-byte hex key (like in Node.js)"""
    import re
    return bool(re.fullmatch(r"[0-9a-fA-F]{64}", secret))

def decrypt(encrypted: dict, secret: str) -> str:
    """
    Decrypts AES-256-GCM data encrypted from Node.js crypto module.
    `encrypted` = { 'iv': str, 'content': str, 'tag': str }
    """
    iv = bytes.fromhex(encrypted["iv"])
    ciphertext = bytes.fromhex(encrypted["content"])
    tag = bytes.fromhex(encrypted["tag"])

    # Node concatenates ciphertext + tag manually (Python expects it together)
    ciphertext_with_tag = ciphertext + tag

    # Prepare the key
    key = bytes.fromhex(secret) if is_valid_hex_key(secret) else get_key(secret)

    # Decrypt
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(iv, ciphertext_with_tag, None)

    return plaintext.decode("utf-8")
