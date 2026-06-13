"""
Application-layer encryption for sensitive data at rest (audit #14 /
SECURITY gap #6).

Lab outputs (SOC credentials, SSH commands, IPs) live in the
`deployments.outputs` column. This module encrypts that blob with Fernet
(AES-128-CBC + HMAC-SHA256) before it touches the database, so a leaked DB
file / backup / replica does not hand over lab credentials.

Key
    The `SECRETS_ENCRYPTION_KEY` env var — a urlsafe-base64 32-byte Fernet key
    (generate one with `python -m crypto`). When unset, encryption is DISABLED
    and values pass through in plaintext. This keeps the mock/dev/CI demo and
    existing plaintext rows working unchanged; **production deployments must
    set the key.** `config.validate_config()` warns when it is missing in a
    non-mock run.

Storage format
    An encrypted value is tagged `enc:v1:<token>` so a read can tell ciphertext
    from legacy plaintext and from disabled-mode values. `decrypt()` is
    therefore safe to call on any stored value, encrypted or not.

Follow-ups (intentionally out of scope here)
    Key rotation, and sourcing the key from a KMS / secrets manager rather than
    an env var. The tagged format leaves room for a future `enc:v2:` scheme.
"""
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_PREFIX = "enc:v1:"
_ENV_KEY = "SECRETS_ENCRYPTION_KEY"  # noqa: S105 - env var name, not a secret


class SecretCipher:
    """Fernet wrapper. A `None`/empty key yields a disabled (passthrough) cipher."""

    def __init__(self, key=None):
        if key:
            self._fernet = Fernet(key.encode() if isinstance(key, str) else key)
        else:
            self._fernet = None

    @property
    def enabled(self) -> bool:
        return self._fernet is not None

    def encrypt(self, plaintext):
        """Encrypt and tag a string. Passes through when disabled or given None."""
        if self._fernet is None or plaintext is None:
            return plaintext
        token = self._fernet.encrypt(plaintext.encode()).decode()
        return f"{_PREFIX}{token}"

    def decrypt(self, value):
        """Recover a stored value.

        - `None` / non-string / untagged value -> returned unchanged (legacy
          plaintext or disabled-mode write).
        - tagged value, cipher available -> decrypted plaintext.
        - tagged value but no/ wrong key -> `None` (logged); the caller decides
          on a safe fallback rather than this module assuming a payload shape.
        """
        if value is None or not isinstance(value, str) or not value.startswith(_PREFIX):
            return value
        if self._fernet is None:
            logger.error("Found encrypted value but %s is unset; cannot decrypt", _ENV_KEY)
            return None
        try:
            return self._fernet.decrypt(value[len(_PREFIX):].encode()).decode()
        except InvalidToken:
            logger.error("Failed to decrypt stored secret (wrong or rotated key?)")
            return None


# --- module-level default cipher -------------------------------------------
# Lazily built from the environment and cached, so the key can be set before
# first use (and tests can reset the cache after changing the env).
_default_cipher: SecretCipher | None = None


def _cipher() -> SecretCipher:
    global _default_cipher
    if _default_cipher is None:
        _default_cipher = SecretCipher(os.getenv(_ENV_KEY))
    return _default_cipher


def reset_default_cipher() -> None:
    """Test hook: drop the cached cipher so the next call re-reads the env."""
    global _default_cipher
    _default_cipher = None


def encrypt_secret(plaintext):
    return _cipher().encrypt(plaintext)


def decrypt_secret(value):
    return _cipher().decrypt(value)


def encryption_enabled() -> bool:
    return _cipher().enabled


if __name__ == "__main__":
    # Generate a fresh key for SECRETS_ENCRYPTION_KEY.
    print(Fernet.generate_key().decode())
