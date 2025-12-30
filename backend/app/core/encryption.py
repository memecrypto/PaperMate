import base64
import hashlib
from cryptography.fernet import Fernet
from app.core.config import get_settings

settings = get_settings()


def _get_fernet() -> Fernet:
    """Derive a Fernet key from JWT_SECRET_KEY."""
    key_bytes = settings.jwt_secret_key.encode("utf-8")
    derived = hashlib.sha256(key_bytes).digest()
    fernet_key = base64.urlsafe_b64encode(derived)
    return Fernet(fernet_key)


def encrypt_value(plaintext: str) -> str:
    """Encrypt a string value and return base64-encoded ciphertext."""
    if not plaintext:
        return ""
    fernet = _get_fernet()
    encrypted = fernet.encrypt(plaintext.encode("utf-8"))
    return encrypted.decode("utf-8")


def decrypt_value(ciphertext: str) -> str:
    """Decrypt a base64-encoded ciphertext and return plaintext."""
    if not ciphertext:
        return ""
    fernet = _get_fernet()
    decrypted = fernet.decrypt(ciphertext.encode("utf-8"))
    return decrypted.decode("utf-8")


def mask_api_key(key: str, visible_chars: int = 4) -> str:
    """Mask an API key, showing only the last N characters."""
    if not key or len(key) <= visible_chars:
        return "*" * 8
    return "*" * 8 + key[-visible_chars:]
